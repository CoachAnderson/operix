"""Tamanho pelo risco, limite de alavancagem e prévia."""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.engine.backtest import BacktestConfig, run_backtest
from app.engine.runner import run_tick
from app.engine.sizing import SizingBlocked, compute
from app.models import Bot, ExecMode, Market, Order
from app.services.brokers.base import SymbolRules
from app.services.brokers.paper import PaperAccount, PaperBroker
from app.strategies.library import get_strategy
from tests.conftest import RULES
from tests.test_api import csrf, register
from tests.test_engine import CROSS_UP, NOW, factory_for, make_bot, make_user_with_plan, market_with_forming_candle
from tests.test_filters import series

WIN = SymbolRules("WIN", "WIN", "BRL", Decimal("0.2"), Decimal("0.2"), Decimal("100"), Decimal("0"), 2, lot_size=Decimal("0.2"), allow_short=True, currency="BRL")
EURUSD = SymbolRules("EURUSD", "EUR", "USD", Decimal("1000"), Decimal("1000"), Decimal("1e8"), Decimal("0"), 5, lot_size=Decimal("100000"), allow_short=True)


def bot(**kw) -> Bot:
    base = dict(market=Market.b3, sizing_mode="fixed", risk_pct=None, max_leverage=None, order_lots=None, order_size_quote=None)
    return Bot(**{**base, **kw})


def test_risk_sizing_b3_contracts():
    b = bot(sizing_mode="risk", risk_pct=Decimal("1"))
    # Stop de 650 pontos: cada contrato arrisca 650 × R$ 0,20 = R$ 130
    with pytest.raises(SizingBlocked, match="1 contrato já arrisca 130,00 \\(1,3% do saldo\\)"):
        compute(b, WIN, Decimal("130000"), Decimal("129350"), Decimal("10000"))
    p = compute(b, WIN, Decimal("130000"), Decimal("129350"), Decimal("50000"))
    assert p.lots == Decimal("3.00")  # R$ 500 de risco ÷ R$ 130 por contrato = 3,8 → 3 contratos
    assert p.risk_money == Decimal("390.0") and p.risk_pct == Decimal("0.78")
    assert p.notional == Decimal("78000.0") and p.leverage == Decimal("1.56")


def test_leverage_cap_forex_and_spot():
    b = bot(market=Market.forex, order_lots=Decimal("1"), max_leverage=Decimal("10"))
    p = compute(b, EURUSD, Decimal("1.1"), None, Decimal("1000"))
    assert p.capped and p.units == Decimal("9000") and p.lots == Decimal("0.09")  # 1 lote seria 110×
    assert p.leverage <= 10 and "alavancagem" in p.note
    b2 = bot(market=Market.forex, order_lots=Decimal("0.01"), max_leverage=Decimal("0.5"))
    with pytest.raises(SizingBlocked, match="limite de alavancagem cortou demais"):
        compute(b2, EURUSD, Decimal("1.1"), None, Decimal("1000"))

    c = bot(market=Market.crypto, sizing_mode="risk", risk_pct=Decimal("1"))
    assert compute(c, RULES, Decimal("100"), Decimal("98"), Decimal("1000")).quote_amount == Decimal("500")
    c.risk_pct = Decimal("5")  # 2.500 USDT > saldo: à vista não gasta mais do que tem
    p = compute(c, RULES, Decimal("100"), Decimal("98"), Decimal("1000"))
    assert p.capped and p.quote_amount == Decimal("1000") and p.note == "Reduzido ao saldo disponível"
    with pytest.raises(SizingBlocked, match="precisa de um stop"):
        compute(c, RULES, Decimal("100"), None, Decimal("1000"))


async def test_runner_risk_sizing_paper(db, plans, fake_market):
    user = await make_user_with_plan(db, plans["pro"])
    b = await make_bot(db, user, ExecMode.auto)  # stop de 2%
    b.sizing_mode, b.risk_pct = "risk", Decimal("1")
    await db.commit()
    market = market_with_forming_candle(fake_market, CROSS_UP[:-1] + [80.0])
    res = await run_tick(db, b, factory_for(market), NOW)
    assert res.action == "executed", res
    order = (await db.scalars(select(Order).where(Order.bot_id == b.id))).one()
    # Saldo 1.000, risco 1% = 10; stop 2% abaixo de 80 = 1,60 por unidade → 6,25 unidades = 500 USDT
    assert order.quote_qty == Decimal("500")
    assert b.paper_quote_balance == Decimal("500")


def test_backtest_risk_sizing_keeps_loss_near_risk():
    candles = series([(300, 0.0, 0.01, 0.2), (200, -0.002, 0.01)], seed=4)
    st = get_strategy("ema_cross_day")
    params = st.parse_params({"timeframe": "1h", "fast": 5, "slow": 13})
    r = run_backtest(st, params, candles, BacktestConfig(initial_balance=10_000, order_units=1, allow_short=True, stop_loss_pct=2,
                                                        risk_pct=1, fee_rate=0, slippage_bps=0, timeframe="1h"))
    stops = [t for t in r.trades if t.exit_reason == "Stop loss"]
    assert stops
    for t in stops:  # cada stop perde cerca de 1% do saldo do momento (gaps podem passar um pouco)
        assert -0.03 * 10_000 < t.pnl < 0


async def test_preview_api(client, db, plans, fake_market, monkeypatch):
    from app.api.routes import bots as route

    await register(client)
    me = (await client.get("/api/v1/me")).json()
    import uuid

    from app.models import SubStatus, Subscription

    db.add(Subscription(user_id=uuid.UUID(me["id"]), plan_id=plans["pro"].id, status=SubStatus.active))
    await db.commit()
    market = fake_market([100.0] * 40, price=100.0)

    async def fake_broker(db_, bot_):
        return PaperBroker(market, PaperAccount(bot_.paper_quote_balance, Decimal("0")))

    monkeypatch.setattr(route, "broker_for_bot", fake_broker)
    body = {"symbol": "BTCUSDT", "strategy": "ema_cross_day", "sizing_mode": "risk", "risk_pct": "2", "stop_loss_pct": "4", "paper_quote_balance": "1000"}
    r = await client.post("/api/v1/bots/sizing-preview", json=body, headers=csrf(client))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] and Decimal(d["quote_amount"]) == Decimal("500") and Decimal(d["risk_money"]) == Decimal("20")
    assert Decimal(d["leverage"]) == Decimal("0.5")
    r = await client.post("/api/v1/bots/sizing-preview", json={**body, "stop_loss_pct": None}, headers=csrf(client))
    assert r.status_code == 422  # pelo risco sem stop
