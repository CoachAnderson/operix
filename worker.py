"""Processo do motor de robôs. Executar com:  python -m app.engine.worker

Pode rodar em várias réplicas: cada robô é protegido por lock no Redis a cada ciclo.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import uuid

from sqlalchemy import select

from app.core.config import get_settings
from app.core.redis import get_redis
from app.db import SessionLocal
from app.engine.runner import expire_signals, mark_error, run_tick
from app.models import Bot, BotStatus

log = logging.getLogger("worker")
MAX_CONCURRENCY = 10


async def _tick_bot(bot_id: uuid.UUID, interval: int, sem: asyncio.Semaphore) -> None:
    r = get_redis()
    lock_key = f"lock:tick:{bot_id}"
    if not await r.set(lock_key, "1", ex=max(interval * 3, 60), nx=True):
        return  # outra réplica está processando este robô
    try:
        async with sem, SessionLocal() as db:
            bot = await db.get(Bot, bot_id)
            if not bot or bot.status not in (BotStatus.running, BotStatus.paused_billing):
                return
            try:
                # Sem wait_for de propósito: cancelar no meio de um envio deixaria a ordem sem desfecho.
                # Os limites de tempo ficam nos clientes HTTP (10 s).
                result = await run_tick(db, bot)
                if result.action not in ("hold", "skipped"):
                    log.info("robô=%s %s %s", bot_id, result.action, result.detail)
            except Exception as exc:  # noqa: BLE001
                log.exception("Falha no robô %s", bot_id)
                await db.rollback()
                await mark_error(db, bot, exc)
    finally:
        await r.delete(lock_key)


async def run_cycle(interval: int) -> None:
    async with SessionLocal() as db:
        await expire_signals(db)
        ids = list(
            await db.scalars(select(Bot.id).where(Bot.status.in_([BotStatus.running, BotStatus.paused_billing])))
        )
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    await asyncio.gather(*(_tick_bot(i, interval, sem) for i in ids))


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    interval = get_settings().worker_interval_seconds
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass

    log.info("Worker iniciado (intervalo %ss)", interval)
    while not stop.is_set():
        try:
            await run_cycle(interval)
        except Exception:  # noqa: BLE001 - o worker nunca deve morrer por um ciclo ruim
            log.exception("Erro no ciclo do worker")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
    log.info("Worker encerrado")


if __name__ == "__main__":
    asyncio.run(main())
