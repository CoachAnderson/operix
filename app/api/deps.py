from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db import get_session
from app.models import Plan, Role, SubStatus, Subscription, User, UserStatus

DB = Annotated[AsyncSession, Depends(get_session)]

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "x-csrf-token"


def _token_from_request(request: Request) -> str | None:
    token = request.cookies.get(ACCESS_COOKIE)
    if token:
        return token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return None


async def get_current_user(request: Request, db: DB) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida ou expirada")
    token = _token_from_request(request)
    data = decode_token(token, "access") if token else None
    if not data:
        raise unauthorized
    try:
        user_id = uuid.UUID(data["sub"])
    except ValueError:
        raise unauthorized from None
    user = await db.get(User, user_id)
    if not user or user.status != UserStatus.active or user.token_version != data.get("ver"):
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso restrito ao administrador")
    if not user.totp_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ative a verificação em duas etapas para acessar o painel admin")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def current_clause(now: datetime | None = None):
    """Assinatura ativa e dentro do prazo (acesso liberado pelo admin pode ter data de fim)."""
    now = now or datetime.now(UTC)
    return (Subscription.status == SubStatus.active) & or_(Subscription.expires_at.is_(None), Subscription.expires_at > now)


async def active_subscription(db: AsyncSession, user_id: uuid.UUID) -> Subscription | None:
    res = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id, current_clause())
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


ADMIN_PLAN_ID = uuid.UUID(int=0)


def admin_plan() -> Plan:
    """Plano virtual do administrador: acesso ilimitado, sem cobrança. Não é gravado no banco."""
    return Plan(
        id=ADMIN_PLAN_ID, code="admin", name="Administrador (ilimitado)",
        description="Acesso completo a todos os robôs e recursos, sem cobrança.",
        price_monthly=Decimal("0"), max_bots=1000, allow_auto=True, allow_live=True, active=False, sort_order=0,
    )


def is_admin(user: User | None) -> bool:
    return bool(user and user.role == Role.admin)


async def effective_plan(db: AsyncSession, user: User | None) -> Plan | None:
    """Plano que vale para o usuário agora: ilimitado para admin; senão o da assinatura ativa (ou nenhum)."""
    if user is None:
        return None
    if is_admin(user):
        return admin_plan()
    sub = await active_subscription(db, user.id)
    return sub.plan if sub else None


async def require_plan(user: CurrentUser, db: DB) -> Plan:
    plan = await effective_plan(db, user)
    if not plan:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "Assinatura inativa. Escolha um plano para continuar.")
    return plan


ActivePlan = Annotated[Plan, Depends(require_plan)]
