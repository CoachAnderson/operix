from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update

from app.api.deps import DB, AdminUser, current_clause, is_admin
from app.api.routes.billing import process_mp_event
from app.core.ratelimit import client_ip
from app.engine.risk import kill_switch_state, set_kill_switch
from app.models import (
    AuditLog,
    Bot,
    BotStatus,
    Order,
    Plan,
    SubStatus,
    Subscription,
    User,
    UserStatus,
    Venue,
    WebhookEvent,
)
from app.schemas import (
    AccessOut,
    AdminStats,
    AdminUserOut,
    AdminUserUpdate,
    AuditOut,
    BotOut,
    KillSwitchIn,
    PlanIn,
    PlanOut,
)
from app.services.audit import audit
from app.services.mercadopago import MercadoPagoClient, MercadoPagoError

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminSubscriptionOut(BaseModel):
    id: uuid.UUID
    user_email: str
    plan_name: str
    price: Decimal
    status: SubStatus
    mp_preapproval_id: str | None
    next_payment_at: datetime | None
    created_at: datetime


class AdminBotOut(BotOut):
    user_id: uuid.UUID


class GrantPlanIn(BaseModel):
    plan_id: uuid.UUID
    note: str = Field("", max_length=300)
    days: int | None = Field(None, ge=1, le=3650)  # None = sem prazo (até o admin cancelar)


class RevokeIn(BaseModel):
    note: str = Field("", max_length=300)
    cancel_billing: bool = True  # também cancela a cobrança recorrente no Mercado Pago


def _access(user: User, sub: Subscription | None) -> AccessOut:
    if is_admin(user):
        return AccessOut(source="admin", plan_name="Administrador (ilimitado)")
    if not sub:
        return AccessOut(source="none")
    return AccessOut(source=sub.source, plan_name=sub.plan.name, expires_at=sub.expires_at, subscription_id=sub.id)


async def _current_subs(db, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, Subscription]:
    """Assinatura vigente mais recente de cada usuário."""
    if not user_ids:
        return {}
    rows = await db.scalars(
        select(Subscription).where(Subscription.user_id.in_(user_ids), current_clause()).order_by(Subscription.created_at)
    )
    return {s.user_id: s for s in rows}  # a mais recente sobrescreve as anteriores


@router.get("/stats", response_model=AdminStats)
async def stats(_: AdminUser, db: DB) -> AdminStats:
    since = datetime.now(UTC) - timedelta(hours=24)
    mrr = await db.scalar(
        select(func.coalesce(func.sum(Plan.price_monthly), 0))
        .select_from(Subscription)
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(Subscription.status == SubStatus.active, Subscription.mp_preapproval_id.is_not(None))
    )
    ks = await kill_switch_state(db)
    return AdminStats(
        users_total=await db.scalar(select(func.count(User.id)).where(User.status != UserStatus.deleted)) or 0,
        subscriptions_active=await db.scalar(select(func.count(Subscription.id)).where(current_clause())) or 0,
        mrr=Decimal(str(mrr or 0)),
        bots_running=await db.scalar(select(func.count(Bot.id)).where(Bot.status == BotStatus.running)) or 0,
        bots_live=await db.scalar(
            select(func.count(Bot.id)).where(Bot.status == BotStatus.running, Bot.venue == Venue.live)
        ) or 0,
        orders_24h=await db.scalar(select(func.count(Order.id)).where(Order.created_at >= since)) or 0,
        kill_switch=bool(ks.get("enabled")),
    )


# ---------------- Usuários ----------------
@router.get("/users", response_model=list[AdminUserOut])
async def list_users(_: AdminUser, db: DB, q: str = "", limit: int = Query(100, le=500), offset: int = 0) -> list[AdminUserOut]:
    query = select(User).where(User.status != UserStatus.deleted)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(or_(func.lower(User.email).like(like), func.lower(User.name).like(like)))
    users = list(await db.scalars(query.order_by(User.created_at.desc()).limit(limit).offset(offset)))
    subs = await _current_subs(db, [u.id for u in users])
    out = []
    for u in users:
        row = AdminUserOut.model_validate(u)
        row.access = _access(u, subs.get(u.id))
        out.append(row)
    return out


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def update_user(user_id: uuid.UUID, body: AdminUserUpdate, admin: AdminUser, request: Request, db: DB) -> User:
    user = await db.get(User, user_id)
    if not user or user.status == UserStatus.deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado")
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Você não pode alterar a própria conta por aqui")
    changes = body.model_dump(exclude_unset=True)
    if body.status == UserStatus.suspended:
        user.token_version += 1  # derruba sessões
        await db.execute(
            update(Bot).where(Bot.user_id == user.id).values(status=BotStatus.stopped, status_reason="Conta suspensa")
        )
    for k, v in changes.items():
        setattr(user, k, v)
    await audit(db, "admin.user_updated", admin.id, target=str(user.id), ip=client_ip(request), **{k: str(v) for k, v in changes.items()})
    await db.commit()
    return user


@router.post("/users/{user_id}/grant-plan", status_code=201)
async def grant_plan(user_id: uuid.UUID, body: GrantPlanIn, admin: AdminUser, request: Request, db: DB) -> dict:
    """Libera acesso sem cobrança (cortesia, parceria, teste), com ou sem prazo. Robôs pausados por falta de plano voltam sozinhos."""
    user = await db.get(User, user_id)
    plan = await db.get(Plan, body.plan_id)
    if not user or user.status == UserStatus.deleted or not plan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário ou plano não encontrado")
    if is_admin(user):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Administradores já têm acesso ilimitado")
    await db.execute(
        update(Subscription)
        .where(Subscription.user_id == user.id, Subscription.status == SubStatus.active, Subscription.mp_preapproval_id.is_(None))
        .values(status=SubStatus.cancelled)
    )
    expires_at = datetime.now(UTC) + timedelta(days=body.days) if body.days else None
    sub = Subscription(user_id=user.id, plan_id=plan.id, status=SubStatus.active, expires_at=expires_at)
    db.add(sub)
    await db.flush()
    await audit(db, "admin.plan_granted", admin.id, target=str(user.id), ip=client_ip(request), plan=plan.code,
                days=body.days or "sem prazo", note=body.note)
    await db.commit()
    return {"subscription_id": str(sub.id), "expires_at": expires_at.isoformat() if expires_at else None}


@router.post("/users/{user_id}/revoke-access")
async def revoke_access(user_id: uuid.UUID, body: RevokeIn, admin: AdminUser, request: Request, db: DB) -> dict:
    """Cancela o acesso do usuário aos robôs sem bloquear o login: encerra a liberação manual e (opcionalmente) a
    assinatura paga, e pausa os robôs. O cliente continua vendo histórico e relatórios e pode assinar de novo."""
    user = await db.get(User, user_id)
    if not user or user.status == UserStatus.deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado")
    if is_admin(user):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Administradores têm acesso ilimitado. Mude o papel para Assinante antes.")
    subs = list(await db.scalars(select(Subscription).where(Subscription.user_id == user.id, Subscription.status == SubStatus.active)))
    paid = [s for s in subs if s.mp_preapproval_id]
    if paid and not body.cancel_billing:
        raise HTTPException(status.HTTP_409_CONFLICT, "O usuário tem assinatura paga ativa. Marque para cancelar a cobrança também.")
    if paid:
        async with MercadoPagoClient() as mp:
            for s in paid:
                try:
                    await mp.cancel_preapproval(s.mp_preapproval_id)
                except (MercadoPagoError, httpx.HTTPError) as exc:
                    await db.commit()  # guarda as cobranças que já foram canceladas
                    raise HTTPException(status.HTTP_502_BAD_GATEWAY, "O Mercado Pago não respondeu ao cancelar a cobrança. O acesso não foi cancelado; tente de novo.") from exc
                s.status = SubStatus.cancelled
    for s in subs:
        s.status = SubStatus.cancelled
    res = await db.execute(
        update(Bot)
        .where(Bot.user_id == user.id, Bot.status == BotStatus.running)
        .values(status=BotStatus.paused_billing, status_reason="Acesso cancelado pela administração")
    )
    await audit(db, "admin.access_revoked", admin.id, target=str(user.id), ip=client_ip(request),
                cancelled=len(subs), paid_cancelled=len(paid), bots_paused=res.rowcount or 0, note=body.note)
    await db.commit()
    return {"cancelled": len(subs), "paid_cancelled": len(paid), "bots_paused": res.rowcount or 0}


# ---------------- Assinaturas ----------------
@router.get("/subscriptions", response_model=list[AdminSubscriptionOut])
async def list_subscriptions(_: AdminUser, db: DB, status_filter: SubStatus | None = Query(None, alias="status"), limit: int = Query(200, le=1000)) -> list[AdminSubscriptionOut]:
    q = (
        select(Subscription, User.email, Plan.name, Plan.price_monthly)
        .join(User, User.id == Subscription.user_id)
        .join(Plan, Plan.id == Subscription.plan_id)
    )
    if status_filter:
        q = q.where(Subscription.status == status_filter)
    rows = (await db.execute(q.order_by(Subscription.created_at.desc()).limit(limit))).all()
    return [
        AdminSubscriptionOut(
            id=s.id,
            user_email=email,
            plan_name=name,
            price=price,
            status=s.status,
            mp_preapproval_id=s.mp_preapproval_id,
            next_payment_at=s.next_payment_at,
            created_at=s.created_at,
        )
        for s, email, name, price in rows
    ]


# ---------------- Planos ----------------
@router.get("/plans", response_model=list[PlanOut])
async def list_all_plans(_: AdminUser, db: DB) -> list[Plan]:
    return list(await db.scalars(select(Plan).order_by(Plan.sort_order, Plan.price_monthly)))


@router.post("/plans", response_model=PlanOut, status_code=201)
async def create_plan(body: PlanIn, admin: AdminUser, request: Request, db: DB) -> Plan:
    if await db.scalar(select(Plan.id).where(Plan.code == body.code)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe um plano com esse código")
    plan = Plan(**body.model_dump())
    db.add(plan)
    await audit(db, "admin.plan_created", admin.id, target=body.code, ip=client_ip(request))
    await db.commit()
    return plan


@router.put("/plans/{plan_id}", response_model=PlanOut)
async def update_plan(plan_id: uuid.UUID, body: PlanIn, admin: AdminUser, request: Request, db: DB) -> Plan:
    """Alterar o preço só vale para novas assinaturas; as existentes no MP mantêm o valor contratado."""
    plan = await db.get(Plan, plan_id)
    if not plan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plano não encontrado")
    for k, v in body.model_dump().items():
        setattr(plan, k, v)
    await audit(db, "admin.plan_updated", admin.id, target=plan.code, ip=client_ip(request))
    await db.commit()
    return plan


# ---------------- Robôs ----------------
@router.get("/bots", response_model=list[AdminBotOut])
async def list_all_bots(_: AdminUser, db: DB, status_filter: BotStatus | None = Query(None, alias="status"), limit: int = Query(200, le=1000)) -> list[Bot]:
    q = select(Bot)
    if status_filter:
        q = q.where(Bot.status == status_filter)
    return list(await db.scalars(q.order_by(Bot.updated_at.desc()).limit(limit)))


@router.post("/bots/{bot_id}/stop", response_model=AdminBotOut)
async def admin_stop_bot(bot_id: uuid.UUID, admin: AdminUser, request: Request, db: DB) -> Bot:
    bot = await db.get(Bot, bot_id)
    if not bot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Robô não encontrado")
    bot.status = BotStatus.stopped
    bot.status_reason = "Parado pela administração"
    await audit(db, "admin.bot_stopped", admin.id, target=str(bot.id), ip=client_ip(request))
    await db.commit()
    return bot


# ---------------- Kill switch ----------------
@router.get("/kill-switch")
async def get_kill_switch(_: AdminUser, db: DB) -> dict:
    return await kill_switch_state(db)


@router.post("/kill-switch")
async def post_kill_switch(body: KillSwitchIn, admin: AdminUser, request: Request, db: DB) -> dict:
    state = await set_kill_switch(db, body.enabled, body.reason)
    await audit(db, "admin.kill_switch", admin.id, ip=client_ip(request), enabled=body.enabled, reason=body.reason)
    await db.commit()
    return state


# ---------------- Auditoria e webhooks ----------------
@router.get("/audit", response_model=list[AuditOut])
async def audit_log(_: AdminUser, db: DB, action: str = "", limit: int = Query(200, le=1000)) -> list[AuditLog]:
    q = select(AuditLog)
    if action:
        q = q.where(AuditLog.action.like(f"{action}%"))
    return list(await db.scalars(q.order_by(AuditLog.created_at.desc()).limit(limit)))


@router.get("/webhooks/failed")
async def failed_webhooks(_: AdminUser, db: DB) -> list[dict]:
    rows = await db.scalars(
        select(WebhookEvent).where(WebhookEvent.processed.is_(False)).order_by(WebhookEvent.created_at.desc()).limit(100)
    )
    return [
        {"id": str(e.id), "topic": e.topic, "resource_id": e.resource_id, "error": e.error, "created_at": e.created_at}
        for e in rows
    ]


@router.post("/webhooks/{event_id}/reprocess", status_code=202)
async def reprocess_webhook(event_id: uuid.UUID, admin: AdminUser, background: BackgroundTasks, db: DB) -> dict:
    if not await db.get(WebhookEvent, event_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    background.add_task(process_mp_event, event_id)
    return {"status": "queued"}
