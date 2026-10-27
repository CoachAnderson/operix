from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select, update

from app.api.deps import DB, ActivePlan, CurrentUser
from app.core import crypto
from app.core.ratelimit import client_ip, hit
from app.models import Bot, BotStatus, ExchangeCredential, Venue
from app.schemas import CredentialIn, CredentialOut
from app.services.audit import audit
from app.services.brokers.base import BrokerError
from app.services.brokers.binance import BinanceClient
from app.services.brokers.factory import credential_aad

router = APIRouter(prefix="/credentials", tags=["credenciais"])


async def verify_binance_key(venue: Venue, api_key: str, api_secret: str) -> tuple[bool, bool]:
    """Valida a chave na Binance. Retorna (pode_negociar, ip_restrito). Recusa chave com saque habilitado."""
    client = BinanceClient(venue.value, api_key, api_secret)
    try:
        await client.sync_time()
        account = await client.account()
        restrictions = await client.api_restrictions()
    except BrokerError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"A Binance recusou a chave: {exc}") from exc
    finally:
        await client.close()

    if restrictions is not None:
        if restrictions.get("enableWithdrawals"):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Por segurança, não aceitamos chaves com permissão de SAQUE. Crie uma chave só com leitura e negociação Spot.",
            )
        can_trade = bool(restrictions.get("enableSpotAndMarginTrading")) and bool(account.get("canTrade"))
        return can_trade, bool(restrictions.get("ipRestrict"))
    return bool(account.get("canTrade")), False


@router.get("", response_model=list[CredentialOut])
async def list_credentials(user: CurrentUser, db: DB) -> list[ExchangeCredential]:
    res = await db.scalars(
        select(ExchangeCredential).where(ExchangeCredential.user_id == user.id).order_by(ExchangeCredential.created_at)
    )
    return list(res)


@router.post("", response_model=CredentialOut, status_code=201)
async def add_credential(body: CredentialIn, user: CurrentUser, plan: ActivePlan, request: Request, db: DB) -> ExchangeCredential:
    await hit(f"cred:{user.id}", limit=10, window_seconds=3600)
    if body.venue == Venue.live and not plan.allow_live:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Seu plano não inclui operação em conta real")
    api_key, api_secret = body.api_key.strip(), body.api_secret.strip()
    can_trade, ip_restricted = await verify_binance_key(body.venue, api_key, api_secret)
    if not can_trade:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A chave não tem permissão de negociação Spot habilitada")

    cred = ExchangeCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        label=body.label,
        exchange="binance",
        venue=body.venue,
        api_key_enc="",
        api_secret_enc="",
        key_last4=api_key[-4:],
        can_trade=can_trade,
        ip_restricted=ip_restricted,
        verified_at=datetime.now(UTC),
    )
    aad = credential_aad(cred)
    cred.api_key_enc = crypto.encrypt(api_key, aad)
    cred.api_secret_enc = crypto.encrypt(api_secret, aad)
    db.add(cred)
    await audit(db, "credential.added", user.id, target=str(cred.id), ip=client_ip(request), venue=body.venue.value)
    await db.commit()
    return cred


@router.delete("/{cred_id}", status_code=204, response_model=None)
async def delete_credential(cred_id: uuid.UUID, user: CurrentUser, request: Request, db: DB) -> None:
    cred = await db.get(ExchangeCredential, cred_id)
    if not cred or cred.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Credencial não encontrada")
    # Robôs que usavam a credencial param imediatamente.
    await db.execute(
        update(Bot)
        .where(Bot.credential_id == cred.id)
        .values(status=BotStatus.stopped, status_reason="Credencial removida", credential_id=None)
    )
    await db.delete(cred)
    await audit(db, "credential.deleted", user.id, target=str(cred_id), ip=client_ip(request))
    await db.commit()
