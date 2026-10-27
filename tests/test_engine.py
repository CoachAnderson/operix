from datetime import UTC, datetime
from decimal import Decimal

import pytest

from sqlalchemy import select

from app.core.security import hash_password
from app.engine.risk import set_kill_switch
from app.engine.runner import run_tick
from app.models import Bot, BotStatus, ExecMode, Order, Position, Signal, SubStatus, Subscription, User, Venue
from app.services.brokers.paper import PaperAccount, PaperBroker

# Série que termina com cruzamento de alta da EMA3 sobre a EMA8 no último candle fechado.
CROSS_UP = [100 - i for i in range(30)] + [80.0, 0.0]  # o último é o candle "em formação" (descartado)


async def make_user_with_plan(db, plan) -> User:
    user = User(email="a@b.com", name="Ana", password_hash=hash_password("x1234567890"))
    db.add(user)
    await db.flush()
    db.add(Subscription(user_id=user.id, plan_id=plan.id, status=SubStatus.active))
    await db.commit()
    return user


async def make_bot(db, user, mode: ExecMode) -> Bot:
    bot = Bot(
        user_id=user.id,
        name="Teste",
        symbol="BTCUSDT",
        strategy="ema_cross_day",
        params={"timeframe": "1m", "fast": 3, "slow": 8},
        exec_mode=mode,
        venue=Venue.paper,
        status=BotStatus.running,
        order_size_quote=Decimal("100"),
        stop_loss_pct=Decimal("2"),
        max_trades_per_day=10,
        paper_quote_balance=Decimal("1000"),
        paper_base_balance=Decimal("0"),
    )
    db.add(bot)
    await db.commit()
    return bot


def factory_for(market):
    async def factory(db, bot):
        return PaperBroker(market, PaperAccount(bot.paper_quote_balance, bot.paper_base_balance), fee_rate=0.001, slippage_bps=0)

    return factory


NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
# close_time do penúltimo candle < agora; do último >= agora (em formação)


def market_with_forming_candle(fake_market, closes):
    m = fake_market(closes, price=80.0)
    orig = m.get_klines

    async def klines(symbol, interval, limit=200):
        cs = await orig(symbol, interval, limit)
        now_ms = int(NOW.timestamp() * 1000)
        # reposiciona o tempo: todos fechados exceto o último
        from app.services.brokers.base import Candle

        n = len(cs)
        return [
            Candle(c.open_time, c.open, c.high, c.low, c.close, c.volume, now_ms - (n - i) * 60_000 if i < n - 1 else now_ms + 30_000)
            for i, c in enumerate(cs)
        ]

    m.get_klines = klines
    return m


async def test_auto_mode_buys_and_stop_loss_sells(db, plans, fake_market):
    user = await make_user_with_plan(db, plans["pro"])
    bot = await make_bot(db, user, ExecMode.auto)
    market = market_with_forming_candle(fake_market, CROSS_UP)

    result = await run_tick(db, bot, factory_for(market), NOW)
    assert result.action == "executed", result
    pos = await db.scalar(select(Position).where(Position.bot_id == bot.id))
    assert pos and pos.qty > 0
    assert bot.paper_quote_balance == Decimal("900")

    # Preço cai 5%: stop loss de 2% dispara a venda
    market.price = Decimal("76")
    result = await run_tick(db, bot, factory_for(market), NOW)
    assert result.action == "executed" and "Stop loss" in result.detail
    orders = (await db.scalars(select(Order).where(Order.bot_id == bot.id))).all()
    assert len(orders) == 2
    assert orders[-1].realized_pnl is not None and orders[-1].realized_pnl < 0


async def test_signals_mode_creates_single_signal(db, plans, fake_market):
    user = await make_user_with_plan(db, plans["sinais"])
    bot = await make_bot(db, user, ExecMode.signals)
    market = market_with_forming_candle(fake_market, CROSS_UP)

    first = await run_tick(db, bot, factory_for(market), NOW)
    second = await run_tick(db, bot, factory_for(market), NOW)
    assert first.action == "signal"
    assert second.action == "hold"
    assert len((await db.scalars(select(Signal))).all()) == 1
    assert (await db.scalars(select(Order))).all() == []


async def test_plan_without_auto_pauses_bot(db, plans, fake_market):
    user = await make_user_with_plan(db, plans["sinais"])
    bot = await make_bot(db, user, ExecMode.auto)
    result = await run_tick(db, bot, factory_for(fake_market(CROSS_UP)), NOW)
    assert result.action == "skipped"
    assert bot.status == BotStatus.paused_billing


async def test_kill_switch_blocks(db, plans, fake_market):
    user = await make_user_with_plan(db, plans["pro"])
    bot = await make_bot(db, user, ExecMode.auto)
    await set_kill_switch(db, True, "teste")
    await db.commit()
    result = await run_tick(db, bot, factory_for(fake_market(CROSS_UP)), NOW)
    assert result.action == "skipped"


# ---------------------------------------------------------------- forex: vendido em conta de margem simulada
CROSS_DOWN = [1.0 + i * 0.001 for i in range(30)] + [1.017, 0.0]  # queda forte no último candle fechado


async def test_forex_paper_short_with_take_profit(db, plans, fake_market):
    from dataclasses import replace

    from app.models import Market, PosSide
    from tests.conftest import RULES

    fx_rules = replace(RULES, symbol="EURUSD", lot_size=Decimal("100000"), step_size=Decimal("1000"), min_qty=Decimal("1000"), min_notional=Decimal("0"), allow_short=True)
    from app.models import ExchangeCredential

    user = await make_user_with_plan(db, plans["pro"])
    cred = ExchangeCredential(user_id=user.id, label="demo", exchange="ctrader", venue=Venue.testnet, api_key_enc="-", api_secret_enc="-",
                              key_last4="0001", verified_at=NOW, can_trade=True, external_account_id="42")
    db.add(cred)
    await db.flush()
    bot = Bot(
        user_id=user.id, name="FX", credential_id=cred.id, market=Market.forex, symbol="EURUSD", strategy="ema_cross_day",
        params={"timeframe": "1m", "fast": 3, "slow": 8}, exec_mode=ExecMode.auto, venue=Venue.paper,
        status=BotStatus.running, allow_short=True, order_lots=Decimal("0.10"), take_profit_pct=Decimal("1"),
        max_trades_per_day=10, paper_quote_balance=Decimal("10000"), paper_base_balance=Decimal("0"),
    )
    db.add(bot)
    await db.commit()
    market = market_with_forming_candle(fake_market, CROSS_DOWN)
    market.price = Decimal("1.0170")

    async def get_rules(symbol):
        return fx_rules

    market.get_rules = get_rules

    async def factory(db_, bot_):
        return PaperBroker(market, PaperAccount(bot_.paper_quote_balance, Decimal("0")), fee_rate=0, slippage_bps=0, margin=True)

    result = await run_tick(db, bot, factory, NOW)
    assert result.action == "executed", result
    pos = await db.scalar(select(Position).where(Position.bot_id == bot.id))
    assert pos.side == PosSide.short and pos.qty == Decimal("10000")  # 0,10 lote x 100.000

    market.price = Decimal("1.0050")  # caiu mais de 1%: alvo do vendido
    result = await run_tick(db, bot, factory, NOW)
    assert "Take profit" in result.detail
    last = (await db.scalars(select(Order).where(Order.bot_id == bot.id).order_by(Order.created_at))).all()[-1]
    assert last.realized_pnl == pytest.approx(Decimal("120.0"), abs=Decimal("0.01"))  # (1,0170 - 1,0050) x 10.000
    assert bot.paper_quote_balance == pytest.approx(Decimal("10120.0"), abs=Decimal("0.01"))
