"""Cliente Redis compartilhado, com fallback em memória para testes/desenvolvimento sem Redis."""
from __future__ import annotations

import asyncio
import time

from redis.asyncio import Redis

from app.core.config import get_settings


class MemoryRedis:
    """Implementa só o subconjunto usado pela aplicação (incr/expire/set nx/get/delete e filas simples)."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}
        self._lists: dict[str, list[str]] = {}

    def _alive(self, key: str) -> bool:
        item = self._data.get(key)
        if not item:
            return False
        if item[1] is not None and item[1] < time.monotonic():
            del self._data[key]
            return False
        return True

    async def get(self, key: str) -> str | None:
        return self._data[key][0] if self._alive(key) else None

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        if nx and self._alive(key):
            return False
        self._data[key] = (str(value), time.monotonic() + ex if ex else None)
        return True

    async def incr(self, key: str) -> int:
        val = int(await self.get(key) or 0) + 1
        exp = self._data[key][1] if self._alive(key) else None
        self._data[key] = (str(val), exp)
        return val

    async def expire(self, key: str, seconds: int) -> bool:
        if key in self._lists:
            return True  # listas em memória não expiram (só testes e desenvolvimento)
        if self._alive(key):
            self._data[key] = (self._data[key][0], time.monotonic() + seconds)
            return True
        return False

    async def delete(self, *keys: str) -> int:
        return sum(1 for k in keys if self._data.pop(k, None) is not None or self._lists.pop(k, None) is not None)

    # Filas (usadas pelo conector do MetaTrader 5). Sem expiração: o chamador limpa o que cria.
    async def rpush(self, key: str, *values: str) -> int:
        lst = self._lists.setdefault(key, [])
        lst.extend(str(v) for v in values)
        return len(lst)

    async def lpush(self, key: str, *values: str) -> int:
        lst = self._lists.setdefault(key, [])
        for v in values:
            lst.insert(0, str(v))
        return len(lst)

    async def ltrim(self, key: str, start: int, end: int) -> bool:
        lst = self._lists.get(key)
        if lst is not None:
            self._lists[key] = lst[start : (None if end == -1 else end + 1)]
        return True

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        lst = self._lists.get(key, [])
        return lst[start : (None if end == -1 else end + 1)]

    async def lpop(self, key: str) -> str | None:
        lst = self._lists.get(key)
        return lst.pop(0) if lst else None

    async def blpop(self, keys: list[str] | str, timeout: float = 0) -> tuple[str, str] | None:
        keys = [keys] if isinstance(keys, str) else list(keys)
        deadline = time.monotonic() + (timeout or 0)
        while True:
            for k in keys:
                v = await self.lpop(k)
                if v is not None:
                    return k, v
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(0.02)

    async def ping(self) -> bool:
        return True


_client: Redis | MemoryRedis | None = None


def get_redis() -> Redis | MemoryRedis:
    global _client
    if _client is None:
        s = get_settings()
        _client = MemoryRedis() if s.environment == "test" or s.redis_url == "memory://" else Redis.from_url(
            s.redis_url, decode_responses=True
        )
    return _client


def set_redis(client: Redis | MemoryRedis | None) -> None:
    global _client
    _client = client
