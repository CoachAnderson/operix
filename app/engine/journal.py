"""Diário do motor: cada decisão de cada robô e o "sinal de vida" do worker, para o painel de diagnóstico.

- Diário por robô (Redis, lista `bot:{id}:journal`): as últimas 100 decisões, com horário, tipo, resultado e motivo.
  Guarda todas as decisões de candle (inclusive "sem sinal") e, das conferências de risco, só as que fizeram algo.
- Sinal de vida do worker (`worker:heartbeat`): atualizado a cada 15 s, com quantos robôs ele vigia, o último erro
  ao ler os robôs do banco e a diferença do relógio do servidor para o da Binance.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from app.core.redis import get_redis

JOURNAL_MAX = 100
JOURNAL_TTL = 3 * 86400
HEARTBEAT_KEY = "worker:heartbeat"
HEARTBEAT_TTL = 300


def _key(bot_id: uuid.UUID | str) -> str:
    return f"bot:{bot_id}:journal"


async def record(bot_id: uuid.UUID | str, kind: str, action: str, detail: str = "") -> None:
    entry = json.dumps({"at": int(time.time() * 1000), "kind": kind, "action": action, "detail": (detail or "")[:300]}, ensure_ascii=False)
    r = get_redis()
    try:
        await r.lpush(_key(bot_id), entry)
        await r.ltrim(_key(bot_id), 0, JOURNAL_MAX - 1)
        await r.expire(_key(bot_id), JOURNAL_TTL)
    except Exception:  # noqa: BLE001 - o diário nunca atrapalha a operação
        pass


async def read(bot_id: uuid.UUID | str, n: int = 50) -> list[dict[str, Any]]:
    try:
        raw = await get_redis().lrange(_key(bot_id), 0, n - 1)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for item in raw:
        try:
            out.append(json.loads(item))
        except ValueError:
            continue
    return out


async def beat(state: dict[str, Any]) -> None:
    try:
        await get_redis().set(HEARTBEAT_KEY, json.dumps({**state, "at": time.time()}), ex=HEARTBEAT_TTL)
    except Exception:  # noqa: BLE001
        pass


async def worker_state() -> dict[str, Any] | None:
    try:
        raw = await get_redis().get(HEARTBEAT_KEY)
    except Exception:  # noqa: BLE001
        return None
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None
