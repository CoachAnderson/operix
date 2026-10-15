"""MetaTrader 5 (futuros da B3): conexões do assinante e as rotas usadas pelo Conector OráculoInvest.

Assinante (cookie de sessão):
  POST /mt5/connections                → cria a conexão e mostra o token do conector UMA vez
  POST /mt5/connections/{id}/token     → gera token novo (o anterior para de funcionar na hora)
  GET  /mt5/status                     → conector online, conta, corretora, limites

Conector (Authorization: Bearer <token>):
  POST /mt5/agent/hello                → identifica a conta do MT5 (confere demo × real)
  GET  /mt5/agent/poll?wait=25         → espera comandos
  POST /mt5/agent/result               → devolve o resultado de um comando
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.api.deps import DB, ActivePlan, CurrentUser
from app.core.ratelimit import client_ip, hit
from app.models import ExchangeCredential, Venue
from app.schemas import CredentialOut
from app.services import mt5_bridge
from app.services.audit import audit

router = APIRouter(prefix="/mt5", tags=["MetaTrader 5"])

DEMO_MODES = {0, 1}  # ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_CONTEST
REAL_MODE = 2  # ACCOUNT_TRADE_MODE_REAL


# ---------------- assinante ----------------
class ConnectionIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    venue: Venue

    @field_validator("venue")
    @classmethod
    def no_paper(cls, v: Venue) -> Venue:
        if v == Venue.paper:
            raise ValueError("Escolha conta demo ou conta real")
        return v


class ConnectionOut(BaseModel):
    credential: CredentialOut
    token: str


async def _own_mt5(db, user, cred_id: uuid.UUID) -> ExchangeCredential:
    cred = await db.get(ExchangeCredential, cred_id)
    if not cred or cred.user_id != user.id or cred.exchange != "mt5":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conexão do MetaTrader 5 não encontrada")
    return cred


@router.post("/connections", response_model=ConnectionOut, status_code=201)
async def create_connection(body: ConnectionIn, user: CurrentUser, plan: ActivePlan, request: Request, db: DB) -> ConnectionOut:
    await hit(f"cred:{user.id}", limit=10, window_seconds=3600)
    if body.venue == Venue.live and not plan.allow_live:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Seu plano não inclui operação em conta real")
    cred = ExchangeCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        label=body.label,
        exchange="mt5",
        venue=body.venue,
        api_key_enc="",
        api_secret_enc="",
        key_last4="",
        can_trade=False,
        ip_restricted=False,
        verified_at=None,  # vira verificada quando o conector se apresentar com a conta certa
    )
    token = mt5_bridge.new_token(cred)
    db.add(cred)
    await audit(db, "credential.added", user.id, target=str(cred.id), ip=client_ip(request), exchange="mt5", venue=body.venue.value)
    await db.commit()
    return ConnectionOut(credential=CredentialOut.model_validate(cred), token=token)


@router.post("/connections/{cred_id}/token", response_model=ConnectionOut)
async def regenerate_token(cred_id: uuid.UUID, user: CurrentUser, request: Request, db: DB) -> ConnectionOut:
    await hit(f"cred:{user.id}", limit=10, window_seconds=3600)
    cred = await _own_mt5(db, user, cred_id)
    token = mt5_bridge.new_token(cred)
    await audit(db, "credential.token_rotated", user.id, target=str(cred.id), ip=client_ip(request))
    await db.commit()
    return ConnectionOut(credential=CredentialOut.model_validate(cred), token=token)


@router.get("/status")
async def connections_status(user: CurrentUser, db: DB) -> list[dict]:
    creds = await db.scalars(
        select(ExchangeCredential).where(ExchangeCredential.user_id == user.id, ExchangeCredential.exchange == "mt5").order_by(ExchangeCredential.created_at)
    )
    out = []
    for c in creds:
        info = await mt5_bridge.agent_info(c.id)
        out.append(
            {
                "credential_id": str(c.id),
                "online": bool(info),
                "last_seen": datetime.fromtimestamp(info["last_seen"], UTC).isoformat() if info else None,
                "account": (info or {}).get("account"),
                "terminal": (info or {}).get("terminal"),
                "limits": (info or {}).get("limits"),
                "agent_version": (info or {}).get("agent_version"),
            }
        )
    return out


# ---------------- conector ----------------
async def agent_credential(request: Request, db: DB) -> ExchangeCredential:
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    cred_id = mt5_bridge.credential_id_from_token(token)
    cred = await db.get(ExchangeCredential, cred_id) if cred_id else None
    if not cred or cred.exchange != "mt5" or not mt5_bridge.token_matches(cred, token):
        await hit(f"mt5-auth:{client_ip(request)}", limit=30, window_seconds=600)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token do conector inválido. Gere um novo no painel (Corretora → MetaTrader 5).")
    return cred


class AccountInfo(BaseModel):
    login: int
    server: str = ""
    company: str = ""
    name: str = ""
    currency: str = "BRL"
    trade_mode: int
    trade_allowed: bool = False
    margin_mode: int | None = None


class TerminalInfo(BaseModel):
    trade_allowed: bool = False  # botão "Algo Trading" do MetaTrader 5
    connected: bool = True
    build: int | None = None


class HelloIn(BaseModel):
    agent_version: str = Field(max_length=20)
    account: AccountInfo
    terminal: TerminalInfo
    limits: dict[str, Any] = Field(default_factory=dict)


@router.post("/agent/hello")
async def agent_hello(body: HelloIn, request: Request, db: DB, cred: ExchangeCredential = Depends(agent_credential)) -> dict:
    mode = body.account.trade_mode
    if cred.venue == Venue.live and mode != REAL_MODE:
        raise HTTPException(status.HTTP_409_CONFLICT, "Este conector é de CONTA REAL, mas o MetaTrader 5 está numa conta demo. Entre na conta real ou use o conector da conta demo.")
    if cred.venue != Venue.live and mode not in DEMO_MODES:
        raise HTTPException(status.HTTP_409_CONFLICT, "Este conector é de CONTA DEMO, mas o MetaTrader 5 está numa conta REAL. Por segurança, nada será executado. Crie um conector de conta real no painel.")
    login = str(body.account.login)
    if cred.external_account_id and cred.external_account_id != login:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Este conector está ligado à conta {cred.external_account_id}, mas o MetaTrader 5 está na conta {login}. Crie outra conexão no painel para usar outra conta.",
        )
    first = cred.verified_at is None
    cred.external_account_id = login
    cred.broker_name = (body.account.company or body.account.server)[:80] or None
    cred.can_trade = bool(body.account.trade_allowed and body.terminal.trade_allowed and body.terminal.connected)
    if first:
        cred.verified_at = datetime.now(UTC)
        await audit(db, "credential.verified", cred.user_id, target=str(cred.id), ip=client_ip(request), exchange="mt5", login=login)
    await db.commit()
    await mt5_bridge.mark_seen(cred.id, body.model_dump() | {"ip": client_ip(request)})
    return {"ok": True, "credential": str(cred.id), "venue": cred.venue.value, "can_trade": cred.can_trade}


@router.get("/agent/poll")
async def agent_poll(wait: float = Query(25, ge=0, le=25), cred: ExchangeCredential = Depends(agent_credential)) -> dict:
    if not await mt5_bridge.agent_info(cred.id):
        raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, "hello")
    await mt5_bridge.mark_seen(cred.id)
    cmds = await mt5_bridge.next_commands(cred.id, wait)
    await mt5_bridge.mark_seen(cred.id)
    return {"commands": cmds}


class ResultIn(BaseModel):
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    ok: bool
    data: Any = None
    error: str | None = Field(None, max_length=1000)
    retryable: bool = False
    code: int | None = None


@router.post("/agent/result")
async def agent_result(body: ResultIn, cred: ExchangeCredential = Depends(agent_credential)) -> dict:
    await mt5_bridge.push_result(cred.id, body.id, body.model_dump())
    await mt5_bridge.mark_seen(cred.id)
    return {"ok": True}
