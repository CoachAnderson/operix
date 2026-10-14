"""Conexão de contas cTrader (forex). Dois caminhos, ambos com as credenciais do próprio cliente:

1. App próprio do cliente: ele cria um app em openapi.ctrader.com e cola Client ID, Client Secret,
   Access Token e Refresh Token (gerados para a conta dele no portal).
2. App da plataforma (opcional, se CTRADER_CLIENT_ID estiver configurado): o cliente clica em
   "Conectar com cTrader", faz login no cTrader e autoriza a própria conta (OAuth).
"""
from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.core import crypto
from app.core.config import get_settings
from app.core.ratelimit import client_ip, hit
from app.core.redis import get_redis
from app.models import ExchangeCredential, Venue
from app.schemas import CredentialOut, CTraderCredentialIn
from app.services import ctrader_auth
from app.services.audit import audit
from app.services.brokers.base import BrokerError
from app.services.brokers.ctrader import list_accounts

router = APIRouter(prefix="/ctrader", tags=["cTrader"])


def _redirect_uri() -> str:
    s = get_settings()
    return s.ctrader_redirect_uri or f"{s.api_public_url}/api/v1/ctrader/callback"


async def _save_accounts(
    db, user, *, label: str, client_id: str | None, client_secret: str | None, access_token: str, refresh_token: str, expires_in: int | None, ip: str
) -> list[ExchangeCredential]:
    app_id, app_secret = (client_id, client_secret) if client_id else (get_settings().ctrader_client_id, get_settings().ctrader_client_secret)
    try:
        accounts, can_trade = await list_accounts(app_id, app_secret, access_token)
    except BrokerError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"O cTrader recusou as credenciais: {exc}") from exc
    if not accounts:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nenhuma conta liberada para este token. Gere o token marcando as contas desejadas.")

    created: list[ExchangeCredential] = []
    rows = await db.execute(
        select(ExchangeCredential.external_account_id, ExchangeCredential.venue).where(
            ExchangeCredential.user_id == user.id, ExchangeCredential.exchange == "ctrader"
        )
    )
    existing = {(a, v) for a, v in rows.all()}
    for acc in accounts:
        account_id = str(int(acc["ctidTraderAccountId"]))
        venue = Venue.live if acc.get("isLive") else Venue.testnet
        if (account_id, venue) in existing:
            continue
        broker = acc.get("brokerTitleShort") or "cTrader"
        login = acc.get("traderLogin", "")
        cred = ExchangeCredential(
            id=uuid.uuid4(),
            user_id=user.id,
            label=f"{label} {broker} {login}".strip()[:80],
            exchange="ctrader",
            venue=venue,
            api_key_enc="",
            api_secret_enc="",
            key_last4=str(login)[-4:] or account_id[-4:],
            can_trade=can_trade,
            ip_restricted=False,
            verified_at=datetime.now(UTC),
            external_account_id=account_id,
            broker_name=broker[:80],
        )
        aad = ctrader_auth.credential_aad(cred)
        if client_id:
            cred.client_id_enc = crypto.encrypt(client_id, aad)
            cred.client_secret_enc = crypto.encrypt(client_secret or "", aad)
        ctrader_auth.store_tokens(cred, access_token, refresh_token, expires_in)
        db.add(cred)
        created.append(cred)
        await audit(db, "credential.added", user.id, target=str(cred.id), ip=ip, exchange="ctrader", venue=venue.value)
    await db.commit()
    return created


@router.get("/status")
async def ctrader_status() -> dict:
    """Informa ao painel se o botão de login com app da plataforma está disponível."""
    s = get_settings()
    return {"platform_app": bool(s.ctrader_client_id and s.ctrader_client_secret), "redirect_uri": _redirect_uri()}


@router.post("/credentials", response_model=list[CredentialOut], status_code=201)
async def add_own_app(body: CTraderCredentialIn, user: CurrentUser, request: Request, db: DB) -> list[ExchangeCredential]:
    """Cliente cola as credenciais do app dele. Cria uma credencial por conta liberada pelo token."""
    await hit(f"cred:{user.id}", limit=10, window_seconds=3600)
    created = await _save_accounts(
        db,
        user,
        label=body.label,
        client_id=body.client_id.strip(),
        client_secret=body.client_secret.strip(),
        access_token=body.access_token.strip(),
        refresh_token=body.refresh_token.strip(),
        expires_in=None,  # o portal não informa: assume os 30 dias padrão e renova antes de vencer
        ip=client_ip(request),
    )
    if not created:
        raise HTTPException(status.HTTP_409_CONFLICT, "Essas contas cTrader já estão conectadas")
    return created


@router.get("/connect")
async def connect(user: CurrentUser) -> dict:
    s = get_settings()
    if not (s.ctrader_client_id and s.ctrader_client_secret):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Login com cTrader não configurado. Use as credenciais do seu próprio app.")
    state = secrets.token_urlsafe(24)
    await get_redis().set(f"ctrader_state:{state}", str(user.id), ex=600)
    query = urlencode({"client_id": s.ctrader_client_id, "redirect_uri": _redirect_uri(), "scope": "trading", "product": "web", "state": state})
    return {"url": f"{s.ctrader_auth_url}?{query}"}


@router.get("/callback", include_in_schema=False)
async def callback(user: CurrentUser, request: Request, db: DB, code: str = Query(""), state: str = Query("")) -> RedirectResponse:
    s = get_settings()
    back = f"{s.public_url}/painel/corretora"
    r = get_redis()
    owner = await r.get(f"ctrader_state:{state}") if state else None
    await r.delete(f"ctrader_state:{state}")
    if not code or owner != str(user.id):
        return RedirectResponse(f"{back}?ctrader=erro", status_code=303)
    try:
        data = await ctrader_auth.token_request(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": _redirect_uri(), "client_id": s.ctrader_client_id, "client_secret": s.ctrader_client_secret}
        )
        await _save_accounts(
            db,
            user,
            label="cTrader",
            client_id=None,
            client_secret=None,
            access_token=data["accessToken"],
            refresh_token=data["refreshToken"],
            expires_in=data.get("expiresIn"),
            ip=client_ip(request),
        )
    except (BrokerError, HTTPException):
        return RedirectResponse(f"{back}?ctrader=erro", status_code=303)
    return RedirectResponse(f"{back}?ctrader=ok", status_code=303)
