"""Credenciais do cTrader por cliente: app (Client ID/Secret) + tokens OAuth da conta, com renovação automática."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.config import get_settings
from app.core.redis import get_redis
from app.models import ExchangeCredential
from app.services.brokers.base import BrokerError

log = logging.getLogger(__name__)
REFRESH_BEFORE = timedelta(days=3)


def credential_aad(cred: ExchangeCredential) -> str:
    return f"{cred.user_id}:{cred.id}"


def app_keys(cred: ExchangeCredential) -> tuple[str, str]:
    """App do próprio cliente quando informado; senão, o app da plataforma."""
    aad = credential_aad(cred)
    if cred.client_id_enc and cred.client_secret_enc:
        return crypto.decrypt(cred.client_id_enc, aad), crypto.decrypt(cred.client_secret_enc, aad)
    s = get_settings()
    if not (s.ctrader_client_id and s.ctrader_client_secret):
        raise BrokerError("Credencial cTrader sem Client ID/Secret e a plataforma não tem app configurado")
    return s.ctrader_client_id, s.ctrader_client_secret


async def token_request(params: dict, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Troca de código ou renovação de token. A documentação mostra GET; aceitamos POST como alternativa."""
    url = get_settings().ctrader_token_url
    async with httpx.AsyncClient(timeout=15, transport=transport) as client:
        resp = await client.get(url, params=params, headers={"Accept": "application/json"})
        if resp.status_code in (404, 405):
            resp = await client.post(url, params=params, headers={"Accept": "application/json"})
    try:
        data = resp.json()
    except ValueError:
        raise BrokerError(f"Resposta inválida do cTrader ({resp.status_code})", retryable=resp.status_code >= 500) from None
    if resp.status_code >= 400 or data.get("errorCode") or not data.get("accessToken"):
        raise BrokerError(f"cTrader recusou o token: {data.get('description') or data.get('errorCode') or resp.status_code}")
    return data


def store_tokens(cred: ExchangeCredential, access_token: str, refresh_token: str, expires_in: int | None) -> None:
    aad = credential_aad(cred)
    cred.api_key_enc = crypto.encrypt(access_token, aad)
    cred.api_secret_enc = crypto.encrypt(refresh_token, aad)
    cred.token_expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in or 2_628_000))


async def access_token(db: AsyncSession, cred: ExchangeCredential) -> str:
    """Devolve um token válido, renovando-o perto do vencimento (o refresh token não expira)."""
    aad = credential_aad(cred)
    token = crypto.decrypt(cred.api_key_enc, aad)
    expires = cred.token_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires is None or expires - datetime.now(UTC) > REFRESH_BEFORE:
        return token
    # Um único processo renova por vez (o refresh token antigo é invalidado na renovação).
    if not await get_redis().set(f"lock:ctrader-refresh:{cred.user_id}", "1", ex=60, nx=True):
        return token
    client_id, secret = app_keys(cred)
    old_refresh = crypto.decrypt(cred.api_secret_enc, aad)
    try:
        data = await token_request({"grant_type": "refresh_token", "refresh_token": old_refresh, "client_id": client_id, "client_secret": secret})
    except BrokerError:
        log.exception("Falha ao renovar token cTrader da credencial %s", cred.id)
        return token  # ainda válido por alguns dias; tenta de novo no próximo ciclo
    # O mesmo token vale para todas as contas autorizadas juntas, e o antigo deixa de valer:
    # atualiza todas as credenciais do cliente que usavam o mesmo refresh token.
    siblings = await db.scalars(
        select(ExchangeCredential).where(ExchangeCredential.user_id == cred.user_id, ExchangeCredential.exchange == "ctrader")
    )
    for other in siblings:
        try:
            same = crypto.decrypt(other.api_secret_enc, credential_aad(other)) == old_refresh
        except crypto.CryptoError:
            same = False
        if same or other.id == cred.id:
            store_tokens(other, data["accessToken"], data["refreshToken"], data.get("expiresIn"))
    await db.commit()
    return data["accessToken"]
