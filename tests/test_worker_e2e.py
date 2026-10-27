"""Ponta a ponta: o worker de verdade (agendador + run_bot + banco + Redis) abre a posição quando a estratégia manda."""
import asyncio
import time
from decimal import Decimal

from sqlalchemy import select

from app.db import SessionLocal
from app.engine import worker
from app.engine.scheduler import Scheduler, load_state
from app.models import Bot, BotStatus, ExecMode, Order, Position, Signal, Venue
from app.services.brokers import factory
from app.services.brokers.base import Candle
from tests.conftest import RULES
from tests.test_engine import CROSS_UP, make_user_with_plan


class LiveLikeMarket:
    """Candles de 1 minuto alinhados ao relógio: todos fechados, menos o último; cruzamento de alta no último fechado."""

    def __init__(self, *a, **k):
        pass

    async def get_klines(self, symbol, interval, limit=200):
        now = int(time.time() * 1000)
        cur = now // 60_000 * 60_000
        closes = CROSS_UP[-limit:]
        n = len(closes)
        out = []
        for i, c in enumerate(closes):
            t = cur - (n - 1 - i) * 60_000
            out.append(Candle(t, c, c * 1.001, c * 0.999, c, 1, t + 59_999))
        return out

    async def get_price(self, symbol):
        return Decimal("80")

    async def get_rules(self, symbol):
        return RULES

    async def close(self):
        pass


async def _run_worker(seconds: float) -> None:
    sch = Scheduler(worker.run_bot)
    stop = asyncio.Event()
    task = asyncio.create_task(sch.run(stop, lambda: load_state(SessionLocal), refresh_every=0.5))
    await asyncio.sleep(seconds)
    stop.set()
    await asyncio.wait_for(task, 10)


async def test_worker_abre_posicao_no_automatico_e_cria_sinal_no_modo_sinais(db, plans, monkeypatch):
    monkeypatch.setattr(factory, "BinanceClient", LiveLikeMarket)
    user = await make_user_with_plan(db, plans["pro"])
    auto = Bot(user_id=user.id, name="Auto", symbol="BTCUSDT", strategy="ema_cross_day", params={"timeframe": "1m", "fast": 3, "slow": 8},
               exec_mode=ExecMode.auto, venue=Venue.paper, status=BotStatus.running, order_size_quote=Decimal("100"),
               max_trades_per_day=10, paper_quote_balance=Decimal("1000"), paper_base_balance=Decimal("0"))
    sig = Bot(user_id=user.id, name="Sinais", symbol="BTCUSDT", strategy="ema_cross_day", params={"timeframe": "1m", "fast": 3, "slow": 8},
              exec_mode=ExecMode.signals, venue=Venue.paper, status=BotStatus.running, order_size_quote=Decimal("100"),
              max_trades_per_day=10, paper_quote_balance=Decimal("1000"), paper_base_balance=Decimal("0"))
    db.add_all([auto, sig])
    await db.commit()

    await _run_worker(2.5)

    async with SessionLocal() as s:
        pos = await s.scalar(select(Position).where(Position.bot_id == auto.id))
        orders = (await s.scalars(select(Order).where(Order.bot_id == auto.id))).all()
        signals = (await s.scalars(select(Signal).where(Signal.bot_id == sig.id))).all()
        fresh = await s.get(Bot, auto.id)
    assert pos is not None and len(orders) == 1, "o robô automático deveria ter comprado"
    assert len(signals) == 1 and not (await db.scalars(select(Order).where(Order.bot_id == sig.id))).all()
    assert fresh.status == BotStatus.running and fresh.last_tick_at is not None


async def test_worker_registra_decisoes_no_diario(db, plans, monkeypatch):
    from app.engine import journal

    monkeypatch.setattr(factory, "BinanceClient", LiveLikeMarket)
    user = await make_user_with_plan(db, plans["pro"])
    bot = Bot(user_id=user.id, name="Auto", symbol="BTCUSDT", strategy="ema_cross_day", params={"timeframe": "1m", "fast": 3, "slow": 8},
              exec_mode=ExecMode.auto, venue=Venue.paper, status=BotStatus.running, order_size_quote=Decimal("100"),
              max_trades_per_day=10, paper_quote_balance=Decimal("1000"), paper_base_balance=Decimal("0"))
    db.add(bot)
    await db.commit()
    await _run_worker(1.5)
    entries = await journal.read(bot.id)
    assert entries and entries[-1]["kind"] == "decision" and entries[-1]["action"] == "executed"
