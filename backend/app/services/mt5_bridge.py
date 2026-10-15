"""Ponte entre o servidor e o Conector OráculoInvest que roda no computador do cliente, ao lado do MetaTrader 5.

Por que assim: o MetaTrader 5 só roda no Windows do cliente, logado na corretora dele. O conector abre
conexões de SAÍDA para o servidor (HTTPS, "long polling"): não precisa abrir porta no roteador e o login e
a senha da corretora nunca saem do computador do cliente.

Fluxo de um comando (ex.: abrir posição):
  worker → RPUSH mt5:q:<credencial>  →  conector busca em GET /mt5/agent/poll  →  executa no MT5
  conector → POST /mt5/agent/result  →  RPUSH mt5:r:<comando>  →  worker recebe (BLPOP) e segue.

Comandos têm prazo: o que não for entregue a tempo é descartado pelo servidor, para o conector nunca
executar uma ordem velha depois de uma reconexão.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Any

from app.core import crypto
from app.core.redis import get_redis
from app.models import ExchangeCredential
from app.services.brokers.base import BrokerError, OrderUnknownError

TOKEN_PREFIX = "oimt5"
SEEN_TTL = 75  # o conector consulta a cada ~25 s; sem sinal por 75 s = desconectado
QUEUE_TTL = 120
RESULT_TTL = 60
# Comandos que mexem em posição: sem resposta = estado desconhecido (reconciliar), nunca "falhou".
TRADING = {"open", "close"}


def _q(cred_id: uuid.UUID | str) -> str:
    return f"mt5:q:{cred_id}"


def _r(cred_id: uuid.UUID | str, cmd_id: str) -> str:
    # A resposta fica no espaço da credencial: um conector só consegue responder aos próprios comandos.
    return f"mt5:r:{cred_id}:{cmd_id}"


def _seen(cred_id: uuid.UUID | str) -> str:
    return f"mt5:seen:{cred_id}"


def credential_aad(cred: ExchangeCredential) -> str:
    return f"{cred.user_id}:{cred.id}"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token(cred: ExchangeCredential) -> str:
    """Gera o token do conector e guarda só o hash (cifrado). O token aparece uma única vez para o cliente."""
    token = f"{TOKEN_PREFIX}_{cred.id.hex}_{secrets.token_urlsafe(32)}"
    aad = credential_aad(cred)
    cred.api_key_enc = crypto.encrypt(_digest(token), aad)
    cred.api_secret_enc = crypto.encrypt("", aad)
    cred.key_last4 = token[-4:]
    return token


def credential_id_from_token(token: str) -> uuid.UUID | None:
    parts = token.split("_", 2)
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        return None
    try:
        return uuid.UUID(hex=parts[1])
    except ValueError:
        return None


def token_matches(cred: ExchangeCredential, token: str) -> bool:
    try:
        stored = crypto.decrypt(cred.api_key_enc, credential_aad(cred))
    except Exception:  # noqa: BLE001 - chave rotacionada/corrompida = token inválido
        return False
    return hmac.compare_digest(stored, _digest(token))


# ---------------- estado do conector ----------------
async def mark_seen(cred_id: uuid.UUID, info: dict | None = None) -> None:
    r = get_redis()
    if info is None:
        raw = await r.get(_seen(cred_id))
        info = json.loads(raw) if raw else {}
    info["last_seen"] = time.time()
    await r.set(_seen(cred_id), json.dumps(info), ex=SEEN_TTL)


async def agent_info(cred_id: uuid.UUID) -> dict | None:
    raw = await get_redis().get(_seen(cred_id))
    return json.loads(raw) if raw else None


# ---------------- lado do servidor (worker/API) ----------------
async def call(cred_id: uuid.UUID, kind: str, args: dict[str, Any] | None = None, timeout: float = 15) -> Any:
    """Envia um comando ao conector e espera a resposta."""
    if not await agent_info(cred_id):
        raise BrokerError(
            "Conector do MetaTrader 5 desconectado. Abra o MetaTrader 5 e o Conector OráculoInvest no computador ou VPS.",
            retryable=True,
        )
    r = get_redis()
    cmd_id = uuid.uuid4().hex
    cmd = {"id": cmd_id, "type": kind, "args": args or {}, "exp": time.time() + timeout}
    await r.rpush(_q(cred_id), json.dumps(cmd))
    if hasattr(r, "expire"):
        await r.expire(_q(cred_id), QUEUE_TTL)
    got = await r.blpop([_r(cred_id, cmd_id)], timeout=max(1, int(timeout)))
    await r.delete(_r(cred_id, cmd_id))
    if got is None:
        if kind in TRADING:
            raise OrderUnknownError("O conector do MetaTrader 5 não confirmou a ordem a tempo", retryable=True)
        raise BrokerError("O conector do MetaTrader 5 não respondeu a tempo", retryable=True)
    res = json.loads(got[1])
    if not res.get("ok"):
        raise BrokerError(f"MetaTrader 5: {res.get('error') or 'erro desconhecido'}", retryable=bool(res.get("retryable")), code=res.get("code"))
    return res.get("data")


# ---------------- lado do conector (rotas /mt5/agent) ----------------
async def next_commands(cred_id: uuid.UUID, wait: float, max_items: int = 10) -> list[dict]:
    """Espera até `wait` segundos pelo primeiro comando e devolve os que estiverem na fila (sem os vencidos)."""
    r = get_redis()
    out: list[dict] = []
    first = await r.blpop([_q(cred_id)], timeout=max(1, int(wait)))
    raw_items = [first[1]] if first else []
    while first and len(raw_items) < max_items:
        nxt = await r.lpop(_q(cred_id))
        if nxt is None:
            break
        raw_items.append(nxt)
    now = time.time()
    for raw in raw_items:
        cmd = json.loads(raw)
        if cmd.get("exp", 0) > now:
            out.append(cmd)
    return out


async def push_result(cred_id: uuid.UUID, cmd_id: str, payload: dict) -> None:
    r = get_redis()
    await r.rpush(_r(cred_id, cmd_id), json.dumps(payload))
    if hasattr(r, "expire"):
        await r.expire(_r(cred_id, cmd_id), RESULT_TTL)
