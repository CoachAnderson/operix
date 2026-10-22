"""Processo do motor de robôs. Executar com:  python -m app.engine.worker

Orientado a eventos (ver app/engine/scheduler.py): decide ~1 s após cada fechamento de candle e vigia
stop/alvo com preço em tempo real. Pode rodar em várias réplicas: cada robô é protegido por lock no Redis.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import uuid
from decimal import Decimal

from app.core.config import get_settings
from app.core.redis import get_redis
from app.db import SessionLocal
from app.engine.pricefeed import BinanceFeed
from app.engine.runner import expire_signals, mark_error, run_risk_tick, run_tick
from app.engine.scheduler import Scheduler, load_state
from app.models import Bot, BotStatus
from app.services.brokers.base import BrokerError

log = logging.getLogger("worker")
MAX_CONCURRENCY = 20
_sem: asyncio.Semaphore | None = None


async def run_bot(bot_id: uuid.UUID, kind: str, price: Decimal | None = None) -> None:
    """Executa uma decisão completa ("decision") ou só a conferência de risco ("risk") de um robô."""
    global _sem
    _sem = _sem or asyncio.Semaphore(MAX_CONCURRENCY)
    r = get_redis()
    lock_key = f"lock:tick:{bot_id}"
    if not await r.set(lock_key, "1", ex=120, nx=True):
        return  # outra réplica está processando este robô
    try:
        async with _sem, SessionLocal() as db:
            bot = await db.get(Bot, bot_id)
            if not bot or bot.status not in (BotStatus.running, BotStatus.paused_billing):
                return
            try:
                # Sem wait_for de propósito: cancelar no meio de um envio deixaria a ordem sem desfecho.
                result = await (run_tick(db, bot) if kind == "decision" else run_risk_tick(db, bot, price=price))
                if result.action not in ("hold", "skipped"):
                    log.info("robô=%s %s %s %s", bot_id, kind, result.action, result.detail)
            except Exception as exc:  # noqa: BLE001
                if isinstance(exc, BrokerError) and exc.retryable:
                    log.warning("robô=%s %s: %s (tenta de novo)", bot_id, kind, exc)
                else:
                    log.error("Falha no robô %s (%s): %s", bot_id, kind, exc, exc_info=not isinstance(exc, BrokerError))
                await db.rollback()
                bot = await db.get(Bot, bot_id, populate_existing=True)  # recarrega depois do rollback
                if bot is not None:
                    await mark_error(db, bot, exc)
    except Exception:  # noqa: BLE001 - uma tarefa nunca derruba o agendador
        log.exception("Erro inesperado ao processar o robô %s", bot_id)
    finally:
        await r.delete(lock_key)


async def _expire_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        with contextlib.suppress(Exception):
            async with SessionLocal() as db:
                await expire_signals(db)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=30)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = get_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass

    scheduler = Scheduler(run_bot)
    tasks = [asyncio.create_task(_expire_loop(stop))]
    if s.price_feed:
        scheduler.feeds = {
            "live": BinanceFeed("live", s.binance_ws_live, scheduler.on_price),
            "testnet": BinanceFeed("testnet", s.binance_ws_testnet, scheduler.on_price),
        }
        tasks += [asyncio.create_task(f.run(stop)) for f in scheduler.feeds.values()]

    log.info(
        "Worker iniciado: decisão %.1fs após cada fechamento de candle, conferência completa a cada %ss, preço em tempo real %s",
        s.candle_close_delay_ms / 1000, s.worker_interval_seconds, "ligado" if s.price_feed else "desligado",
    )
    await scheduler.run(stop, lambda: load_state(SessionLocal))
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    log.info("Worker encerrado")


if __name__ == "__main__":
    asyncio.run(main())
