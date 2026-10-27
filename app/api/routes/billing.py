from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import ADMIN_PLAN_ID, DB, CurrentUser, active_subscription, admin_plan, is_admin
from app.core.config import get_settings
from app.core.ratelimit import client_ip
from app.db import SessionLocal
from app.models import Payment, Plan, SubStatus, Subscription, WebhookEvent
from app.schemas import CheckoutIn, CheckoutOut, PlanOut, SubscriptionOut
from app.services.audit import audit
from app.services.mercadopago import (
    PREAPPROVAL_STATUS,
    MercadoPagoClient,
    MercadoPagoError,
    verify_webhook_signature,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/plans", response_model=list[PlanOut])
async def list_plans(db: DB) -> list[Plan]:
    res = await db.scalars(select(Plan).where(Plan.active.is_(True)).order_by(Plan.sort_order, Plan.price_monthly))
    return list(res)


@router.get("/subscription", response_model=SubscriptionOut | None)
async def my_subscription(user: CurrentUser, db: DB) -> Subscription | SubscriptionOut | None:
    if is_admin(user):
        # Administrador: acesso ilimitado, sem cobrança.
        return SubscriptionOut(id=ADMIN_PLAN_ID, status=SubStatus.active, plan=PlanOut.model_validate(admin_plan()),
                               next_payment_at=None, created_at=user.created_at, source="admin")
    sub = await active_subscription(db, user.id)
    if sub:
        return sub
    return await db.scalar(
        select(Subscription).where(Subscription.user_id == user.id).order_by(Subscription.created_at.desc()).limit(1)
    )


@router.post("/checkout", response_model=CheckoutOut)
async def checkout(body: CheckoutIn, user: CurrentUser, request: Request, db: DB) -> CheckoutOut:
    plan = await db.get(Plan, body.plan_id)
    if not plan or not plan.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plano não encontrado")

    if is_admin(user):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Administradores já têm acesso ilimitado, sem assinatura")
    current = await active_subscription(db, user.id)
    if current and current.plan_id == plan.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Você já assina este plano")

    pending = await db.scalar(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.plan_id == plan.id,
            Subscription.status == SubStatus.pending,
            Subscription.init_point.is_not(None),
        )
    )
    if pending and pending.init_point:
        return CheckoutOut(subscription_id=pending.id, checkout_url=pending.init_point)

    sub = Subscription(user_id=user.id, plan_id=plan.id, status=SubStatus.pending)
    db.add(sub)
    await db.flush()
    s = get_settings()
    try:
        async with MercadoPagoClient() as mp:
            pre = await mp.create_preapproval(
                reason=f"{s.app_name} - Plano {plan.name}",
                amount=plan.price_monthly,
                payer_email=user.email,
                external_reference=str(sub.id),
                back_url=f"{s.public_url}/painel/assinatura?retorno=1",
            )
    except MercadoPagoError as exc:
        await db.rollback()
        log.error("Falha ao criar assinatura no MP: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Não foi possível iniciar o pagamento. Tente novamente.") from exc

    sub.mp_preapproval_id = pre["id"]
    sub.init_point = pre["init_point"]
    await audit(db, "billing.checkout", user.id, target=str(sub.id), ip=client_ip(request), plan=plan.code)
    await db.commit()
    return CheckoutOut(subscription_id=sub.id, checkout_url=pre["init_point"])


@router.post("/cancel", status_code=204, response_model=None)
async def cancel(user: CurrentUser, request: Request, db: DB) -> None:
    sub = await active_subscription(db, user.id)
    if not sub or not sub.mp_preapproval_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nenhuma assinatura ativa")
    try:
        async with MercadoPagoClient() as mp:
            await mp.cancel_preapproval(sub.mp_preapproval_id)
    except MercadoPagoError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Não foi possível cancelar agora. Tente novamente.") from exc
    sub.status = SubStatus.cancelled
    await audit(db, "billing.cancel", user.id, target=str(sub.id), ip=client_ip(request))
    await db.commit()


# ---------------- Webhook ----------------
@router.post("/webhook/mercadopago")
async def mercadopago_webhook(request: Request, background: BackgroundTasks, db: DB) -> dict[str, str]:
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST) from None

    topic = str(body.get("type") or body.get("topic") or "")
    data_id = request.query_params.get("data.id") or str((body.get("data") or {}).get("id") or "")
    request_id = request.headers.get("x-request-id", "")
    if not verify_webhook_signature(
        x_signature=request.headers.get("x-signature", ""), x_request_id=request_id, data_id=data_id
    ):
        log.warning("Webhook MP com assinatura inválida (ip=%s)", client_ip(request))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    if topic not in ("subscription_preapproval", "subscription_authorized_payment"):
        return {"status": "ignored"}

    event = WebhookEvent(provider="mercadopago", topic=topic, resource_id=data_id, request_id=request_id)
    db.add(event)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return {"status": "duplicate"}

    # Responde 200 já; processa depois. O processamento é idempotente (consulta o estado atual no MP).
    background.add_task(process_mp_event, event.id)
    return {"status": "accepted"}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def process_mp_event(event_id: uuid.UUID, mp: MercadoPagoClient | None = None) -> None:
    async with SessionLocal() as db:
        event = await db.get(WebhookEvent, event_id)
        if not event or event.processed:
            return
        client = mp or MercadoPagoClient()
        try:
            if event.topic == "subscription_preapproval":
                await _sync_preapproval(db, client, event.resource_id)
            elif event.topic == "subscription_authorized_payment":
                await _sync_authorized_payment(db, client, event.resource_id)
            event.processed = True
            event.error = None
        except Exception as exc:  # noqa: BLE001 - registra e segue; o MP reenvia em falhas de entrega
            log.exception("Erro processando evento MP %s", event_id)
            event.error = str(exc)[:1000]
        finally:
            if mp is None:
                await client.__aexit__()
        await db.commit()


async def _sync_preapproval(db, mp: MercadoPagoClient, preapproval_id: str) -> None:
    pre = await mp.get_preapproval(preapproval_id)
    sub = await db.scalar(select(Subscription).where(Subscription.mp_preapproval_id == pre["id"]))
    if not sub and pre.get("external_reference"):
        try:
            sub = await db.get(Subscription, uuid.UUID(pre["external_reference"]))
        except ValueError:
            sub = None
    if not sub:
        raise ValueError(f"Assinatura não encontrada para preapproval {preapproval_id}")

    new_status = SubStatus(PREAPPROVAL_STATUS.get(pre.get("status", ""), sub.status.value))
    sub.mp_preapproval_id = pre["id"]
    sub.next_payment_at = _parse_dt(pre.get("next_payment_date"))
    if new_status != sub.status:
        await audit(db, "billing.status_changed", sub.user_id, target=str(sub.id), old=sub.status.value, new=new_status.value)
        sub.status = new_status

    if new_status == SubStatus.active:
        # Troca de plano: cancela assinaturas ativas anteriores do mesmo usuário.
        older = await db.scalars(
            select(Subscription).where(
                Subscription.user_id == sub.user_id, Subscription.status == SubStatus.active, Subscription.id != sub.id
            )
        )
        for old in older:
            if old.mp_preapproval_id:
                try:
                    await mp.cancel_preapproval(old.mp_preapproval_id)
                except MercadoPagoError:
                    log.exception("Falha ao cancelar assinatura antiga %s", old.id)
                    continue
            old.status = SubStatus.cancelled
            await audit(db, "billing.replaced", sub.user_id, target=str(old.id), by=str(sub.id))


async def _sync_authorized_payment(db, mp: MercadoPagoClient, payment_id: str) -> None:
    ap = await mp.get_authorized_payment(payment_id)
    sub = await db.scalar(select(Subscription).where(Subscription.mp_preapproval_id == ap.get("preapproval_id")))
    if not sub:
        raise ValueError(f"Assinatura não encontrada para cobrança {payment_id}")

    pay_status = str((ap.get("payment") or {}).get("status") or ap.get("status") or "unknown")
    payment = await db.scalar(select(Payment).where(Payment.mp_authorized_payment_id == str(ap["id"])))
    if not payment:
        payment = Payment(
            subscription_id=sub.id,
            mp_authorized_payment_id=str(ap["id"]),
            amount=Decimal(str(ap.get("transaction_amount") or 0)),
            status=pay_status,
        )
        db.add(payment)
    payment.status = pay_status
    if pay_status == "approved":
        payment.paid_at = _parse_dt(ap.get("date_created")) or payment.paid_at
        if sub.status in (SubStatus.past_due, SubStatus.pending):
            sub.status = SubStatus.active
    elif pay_status == "rejected" and sub.status == SubStatus.active:
        sub.status = SubStatus.past_due
        await audit(db, "billing.past_due", sub.user_id, target=str(sub.id), payment=str(ap["id"]))
