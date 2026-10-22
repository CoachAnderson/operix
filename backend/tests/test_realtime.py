"""Motor orientado a eventos: agenda no fechamento do candle, preço em tempo real e saída imediata."""
import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import websockets
from sqlalchemy import select

from app.engine.pricefeed import BinanceFeed
from app.engine.runner import run_risk_tick, run_tick
from app.engine.scheduler import Scheduler, next_close
from app.models import Bot, ExecMode, Market, Order, Position, PosSide, Venue
from tests.test_engine import CROSS_UP, NOW, factory_for, make_bot, make_user_with_plan, market_with_forming_candle


class Clock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self) -> float:
        return self.t


def mkbot(**kw) -> Bot:
    base = dict(id=uuid.uuid4(), symbol="BTCUSDT", strategy="ema_cross_day", params={"timeframe": "5m"}, market=Market.crypto,
                venue=Venue.paper, stop_loss_pct=Decimal("2"), take_profit_pct=Decimal("4"))
    return Bot(**{**base, **kw})


def test_next_close():
    t = datetime(2026, 10, 22, 12, 3, 10, tzinfo=UTC).timestamp()
    assert next_close(t, "5m") == datetime(2026, 10, 22, 12, 5, tzinfo=UTC).timestamp()
    assert next_close(t, "1h") == datetime(2026, 10, 22, 13, 0, tzinfo=UTC).timestamp()


async def test_decision_right_after_candle_close():
    calls = []

    async def runner(bot_id, kind, price):
        calls.append((kind, clock.t))

    clock = Clock(datetime(2026, 10, 22, 12, 4, 30, tzinfo=UTC).timestamp())  # 30 s antes do fechamento do candle de 5 min
    sch = Scheduler(runner, clock)
    b = mkbot()
    sch.load([b], {})
    assert sch.due() == [(b.id, "decision")]  # robô novo: decide já
    sch.dispatch()
    await asyncio.sleep(0.01)  # deixa a tarefa terminar
    w = sch.watches[b.id]
    close = datetime(2026, 10, 22, 12, 5, tzinfo=UTC).timestamp()
    assert w.due_decision == pytest.approx(close + 1.2)  # 1,2 s depois do fechamento, não 20 s
    clock.t = close + 1.0
    assert sch.due() == []
    clock.t = close + 1.25
    assert sch.due() == [(b.id, "decision")]


async def test_price_crossing_stop_triggers_immediately():
    got = []

    async def runner(bot_id, kind, price):
        got.append((kind, price))

    clock = Clock(1_000_000.0)
    sch = Scheduler(runner, clock)
    b = mkbot()
    pos = Position(bot_id=b.id, side=PosSide.long, qty=Decimal("0.01"), avg_price=Decimal("100000"))
    sch.load([b], {b.id: pos})
    w = sch.watches[b.id]
    w.due_decision = clock.t + 300
    w.next_risk = clock.t + 10
    assert w.stop == pytest.approx(98000) and w.take == pytest.approx(104000)
    sch.on_price("live", "BTCUSDT", 98500, 98510)  # ainda acima do stop
    assert sch.due() == []
    sch.on_price("live", "BTCUSDT", 97990, 98000)  # bid cruzou o stop
    assert sch.wake.is_set() and sch.due() == [(b.id, "risk")]
    sch.dispatch()
    await asyncio.sleep(0)
    assert got == [("risk", Decimal("97990"))]  # saída de comprado avaliada pelo bid

    # Forex/B3 fora da simulação: stop na corretora, conferência a cada 5 s
    fx = mkbot(market=Market.forex, venue=Venue.testnet, symbol="EURUSD")
    sch.load([fx], {fx.id: Position(bot_id=fx.id, side=PosSide.short, qty=Decimal("1000"), avg_price=Decimal("1.1"))})
    assert sch.watches[fx.id].broker_protected and sch._risk_interval(sch.watches[fx.id]) == 5.0


async def test_binance_feed_with_local_server():
    received_subs = []

    async def handler(ws):
        received_subs.append(json.loads(await ws.recv()))
        for bid in (101.0, 100.5, 99.0):
            await ws.send(json.dumps({"u": 1, "s": "BTCUSDT", "b": str(bid), "B": "1", "a": str(bid + 0.1), "A": "1"}))
            await asyncio.sleep(0.01)
        await asyncio.sleep(1)

    prices = []
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        feed = BinanceFeed("live", f"ws://127.0.0.1:{port}", lambda f, s, b, a: prices.append((s, b)))
        feed.set_symbols({"BTCUSDT"})
        stop = asyncio.Event()
        task = asyncio.create_task(feed.run(stop))
        for _ in range(100):
            if len(prices) >= 3:
                break
            await asyncio.sleep(0.02)
        stop.set()
        await asyncio.wait_for(task, 5)
    assert received_subs[0]["method"] == "SUBSCRIBE" and received_subs[0]["params"] == ["btcusdt@bookTicker"]
    assert prices == [("BTCUSDT", 101.0), ("BTCUSDT", 100.5), ("BTCUSDT", 99.0)]
    assert feed.quotes["BTCUSDT"].bid == 99.0


async def test_risk_tick_closes_on_stop_without_candles(db, plans, fake_market):
    user = await make_user_with_plan(db, plans["pro"])
    bot = await make_bot(db, user, ExecMode.auto)
    market = market_with_forming_candle(fake_market, CROSS_UP[:-1] + [80.0])
    assert (await run_tick(db, bot, factory_for(market), NOW)).action == "executed"
    calls = {"klines": 0}
    orig = market.get_klines

    async def counting(*a, **k):
        calls["klines"] += 1
        return await orig(*a, **k)

    market.get_klines = counting
    res = await run_risk_tick(db, bot, factory_for(market), price=Decimal("78.3"), now=NOW)  # stop de 2% abaixo de 80
    assert res.action == "executed" and "Stop loss" in res.detail
    assert calls["klines"] == 0  # caminho rápido: não baixa candles
    assert await db.scalar(select(Position).where(Position.bot_id == bot.id)) is None
    assert len((await db.scalars(select(Order).where(Order.bot_id == bot.id))).all()) == 2


async def test_end_to_end_latency_from_price_to_runner():
    """Do preço cruzando o stop até a tarefa de saída começar: poucos milissegundos."""
    started = asyncio.Event()
    t_start = {}

    async def runner(bot_id, kind, price):
        t_start[kind] = time.perf_counter()
        started.set()

    sch = Scheduler(runner)
    b = mkbot()
    pos = Position(bot_id=b.id, side=PosSide.long, qty=Decimal("0.01"), avg_price=Decimal("100000"))

    async def load_state():
        return [b], {b.id: pos}

    stop = asyncio.Event()
    loop_task = asyncio.create_task(sch.run(stop, load_state, refresh_every=60))
    await asyncio.sleep(0.05)
    started.clear()
    t_start.clear()
    w = sch.watches[b.id]
    w.due_decision = time.time() + 300
    w.next_risk = time.time() + 300
    t0 = time.perf_counter()
    sch.on_price("live", "BTCUSDT", 97000, 97001)
    await asyncio.wait_for(started.wait(), 1)
    stop.set()
    await asyncio.wait_for(loop_task, 5)
    assert t_start["risk"] - t0 < 0.05
