"""Qualidade de execução: atraso do sinal à execução, escorregamento e operação dividida em preço × taxa."""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.engine.runner import run_tick
from app.models import Bot, BotStatus, ExecMode, Order, SubStatus, Subscription, User, Venue
from tests.test_api import register
from tests.test_engine import CROSS_UP, NOW, factory_for, market_with_forming_candle


async def test_atraso_escorregamento_e_taxas(client, db, plans, fake_market):
    await register(client)
    user = await db.scalar(select(User))
    db.add(Subscription(user_id=user.id, plan_id=plans["pro"].id, status=SubStatus.active))
    bot = Bot(user_id=user.id, name="R", symbol="BTCUSDT", strategy="ema_cross_day", params={"timeframe": "1m", "fast": 3, "slow": 8},
              exec_mode=ExecMode.auto, venue=Venue.paper, status=BotStatus.running, order_size_quote=Decimal("100"),
              stop_loss_pct=Decimal("2"), max_trades_per_day=10, paper_quote_balance=Decimal("1000"), paper_base_balance=Decimal("0"))
    db.add(bot)
    await db.commit()

    market = market_with_forming_candle(fake_market, CROSS_UP)  # último candle fechado: 80
    market.price = Decimal("80.4")  # o preço já andou 0,5% quando a ordem sai
    res = await run_tick(db, bot, factory_for(market), NOW)
    assert res.action == "executed", res
    buy = await db.scalar(select(Order).where(Order.bot_id == bot.id))
    assert buy.ref_price == Decimal("80") and buy.signal_at is not None and buy.filled_at is not None

    market.price = Decimal("80.5")  # sobe um pouco: ganha no preço, mas a taxa de 0,1% por lado come o ganho
    from app.engine import executor
    from app.services.brokers.paper import PaperAccount, PaperBroker
    broker = PaperBroker(market, PaperAccount(bot.paper_quote_balance, bot.paper_base_balance), fee_rate=0.001, slippage_bps=0)
    await executor.execute(db, bot, broker, executor.closing_side((await executor.get_position(db, bot.id)).side), "teste",
                           ref_price=Decimal("80.5"), signal_at=NOW + timedelta(minutes=1))

    r = await client.get(f"/api/v1/bots/{bot.id}/execution")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["orders"] == 2 and d["trades"] == 1 and d["trades_with_fees"] == 1
    assert d["slip_avg_pct"] == pytest.approx((0.5 + 0.0) / 2, abs=1e-6)  # entrada 0,5% pior que o sinal; saída no preço
    t = d["rows"][0]
    assert t["exit"] and t["gross"] > 0 and t["net"] < 0  # ganhou no preço e perdeu na taxa
    assert d["price_ok_fee_loss"] == 1 and d["fees_total"] == pytest.approx(0.2, rel=0.02)
    assert d["currency"] == "USDT"

    other = (await client.get(f"/api/v1/bots/{uuid.uuid4()}/execution")).status_code
    assert other == 404
