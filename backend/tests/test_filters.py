"""Filtros de entrada, stop/alvo pelo ATR e backtest com período de confirmação."""
import math
import random
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.engine.backtest import BacktestConfig, run_backtest
from app.engine.runner import run_tick
from app.models import ExecMode, Position
from app.services.brokers.base import Candle
from app.strategies import filters as flt
from app.strategies.library import get_strategy
from tests.test_api import csrf, register
from tests.test_engine import CROSS_UP, NOW, factory_for, make_bot, make_user_with_plan, market_with_forming_candle

H = 3_600_000


def series(regimes: list[tuple], seed: int = 7, step: int = H, start: int = 1_700_000_000_000) -> list[Candle]:
    """Candles sintéticos: cada regime = (quantidade, tendência por candle, ruído[, volta ao centro])."""
    rnd = random.Random(seed)
    out, price, t = [], 100.0, start - start % step
    for n, drift, vol, *rest in regimes:
        pull, center = (rest[0] if rest else 0.0), price
        for _ in range(n):
            o = price
            c = o * (1 + drift + rnd.gauss(0, vol)) + pull * (center - o)
            out.append(Candle(t, o, max(o, c) * (1 + abs(rnd.gauss(0, vol / 2))), min(o, c) * (1 - abs(rnd.gauss(0, vol / 2))), c, 1, t + step - 1))
            price, t = c, t + step
    return out


# ---------------- unidades ----------------
def test_filter_config_validation():
    assert not flt.BotFilters().active
    with pytest.raises(ValidationError):
        flt.BotFilters(hours_start="09:30")  # sem fim
    with pytest.raises(ValidationError):
        flt.BotFilters(hours_start="9h", hours_end="17:00")
    with pytest.raises(ValueError, match="maior"):
        flt.BotFilters(htf="5m").validate_for("1h")
    flt.BotFilters(htf="1h").validate_for("5m")


def test_regime_hours_volatility_and_htf():
    trend = series([(150, 0.004, 0.003)])
    flat = series([(150, 0.0, 0.004, 0.3)], seed=11)  # lateral: o preço volta para o meio
    f = flt.BotFilters(regime=True, adx_level=20)
    now = trend[-1].close_time + 1
    assert flt.entry_block(f, "trend", "long", trend, None, now) is None
    assert "sem tendência" in flt.entry_block(f, "trend", "long", flat, None, now)
    assert "reversão arriscada" in flt.entry_block(f, "reversion", "long", trend, None, now)

    # Horário (Brasília): 12:00 UTC = 09:00 em Brasília
    noon = int(datetime(2026, 10, 12, 12, 0, tzinfo=UTC).timestamp() * 1000)
    assert "fora do horário" in flt.entry_block(flt.BotFilters(hours_start="10:00", hours_end="17:00"), "trend", "long", trend, None, noon)
    assert flt.entry_block(flt.BotFilters(hours_start="08:30", hours_end="17:00"), "trend", "long", trend, None, noon) is None
    assert flt.entry_block(flt.BotFilters(hours_start="22:00", hours_end="10:00"), "trend", "long", trend, None, noon) is None  # cruza a meia-noite

    # Volatilidade: ATR em % do preço
    assert "baixa demais" in flt.entry_block(flt.BotFilters(atr_min_pct=5), "trend", "long", trend, None, now)

    # Tempo maior: tendência de alta no 4h libera compra e barra venda
    f4 = flt.BotFilters(htf="4h", htf_ema=10)
    big = flt.resample(trend, "4h", now)
    assert flt.entry_block(f4, "trend", "long", trend, big, now) is None
    assert "não vende contra a maré" in flt.entry_block(f4, "trend", "short", trend, big, now)


def test_resample_never_uses_unfinished_candle():
    c = series([(10, 0.001, 0.001)], start=0)
    # 10 candles de 1h = 2 blocos de 4h completos + 1 incompleto (2 candles)
    assert len(flt.resample(c, "4h", c[-1].close_time + 1)) == 2
    assert len(flt.resample(c[:8], "4h", c[7].close_time + 1)) == 2  # o 2º fecha exatamente aqui
    assert len(flt.resample(c[:7], "4h", c[6].close_time + 1)) == 1


def test_atr_levels():
    f = flt.BotFilters(stop_atr=1.5, take_atr=3)
    assert flt.atr_levels(f, "long", 100, 2) == (97, 106)
    assert flt.atr_levels(f, "short", 100, 2) == (103, 94)
    assert flt.atr_levels(flt.BotFilters(stop_atr=1), "long", 100, math.nan) == (None, None)


# ---------------- backtest ----------------
def test_backtest_regime_filter_split_and_reasons():
    candles = series([(300, 0.0, 0.006, 0.3), (250, 0.003, 0.004), (300, 0.0, 0.006, 0.3), (250, -0.003, 0.004)], seed=5)
    strategy = get_strategy("ema_cross_swing")
    params = strategy.parse_params({"timeframe": "1h", "fast": 9, "slow": 21})
    split = candles[len(candles) * 7 // 10].open_time
    base = run_backtest(strategy, params, candles, BacktestConfig(order_units=1, allow_short=True, fee_rate=0.0005, split_time=split, timeframe="1h"))
    filt = run_backtest(
        strategy, params, candles,
        BacktestConfig(order_units=1, allow_short=True, fee_rate=0.0005, split_time=split, timeframe="1h", filters=flt.BotFilters(regime=True, adx_level=25)),
    )
    assert filt.filtered_entries > 0 and filt.metrics.trades < base.metrics.trades
    assert filt.filter_reasons[0]["reason"] == "Mercado sem tendência (ADX)"
    assert [s.label for s in filt.segments] == ["Ajuste", "Confirmação"]
    assert sum(s.trades for s in filt.segments) == filt.metrics.trades
    # O retorno dos dois trechos encadeados bate com o total
    total = (1 + filt.segments[0].return_pct / 100) * (1 + filt.segments[1].return_pct / 100) - 1
    assert total * 100 == pytest.approx(filt.metrics.return_pct, abs=0.01)


def test_backtest_atr_stop_and_htf_filter():
    candles = series([(400, 0.002, 0.006), (300, -0.002, 0.006)], seed=9)
    strategy = get_strategy("ema_cross_day")
    params = strategy.parse_params({"timeframe": "1h", "fast": 5, "slow": 13})
    r = run_backtest(strategy, params, candles, BacktestConfig(order_units=1, allow_short=True, fee_rate=0, slippage_bps=0, timeframe="1h",
                                                               filters=flt.BotFilters(stop_atr=1.0, take_atr=2.0)))
    exits = {t.exit_reason for t in r.trades}
    assert {"Stop loss", "Alvo de lucro"} & exits
    # Com ATR de alvo 2× o stop, cada alvo rende cerca do dobro de cada stop
    stops = [t for t in r.trades if t.exit_reason == "Stop loss"]
    takes = [t for t in r.trades if t.exit_reason == "Alvo de lucro"]
    if stops and takes:
        assert sum(abs(t.pnl) for t in takes) / len(takes) > sum(abs(t.pnl) for t in stops) / len(stops)

    # Filtro de tempo maior: menos operações contra a tendência do diário... aqui, do 4h
    h = run_backtest(strategy, params, candles, BacktestConfig(order_units=1, allow_short=True, timeframe="1h", filters=flt.BotFilters(htf="4h", htf_ema=20)))
    assert h.filtered_entries > 0
    assert "Contra o tempo gráfico maior" in {x["reason"] for x in h.filter_reasons}


# ---------------- robô ao vivo ----------------
async def test_runner_entry_filter_and_atr_stop(db, plans, fake_market):
    user = await make_user_with_plan(db, plans["pro"])
    bot = await make_bot(db, user, ExecMode.auto)
    bot.filters = {"hours_start": "10:00", "hours_end": "17:00"}  # NOW = 09:00 em Brasília
    await db.commit()
    closes = CROSS_UP[:-1] + [80.0]
    market = market_with_forming_candle(fake_market, closes)
    res = await run_tick(db, bot, factory_for(market), NOW)
    assert res.action == "hold" and "Entrada filtrada: fora do horário" in res.detail
    assert await db.scalar(select(Position).where(Position.bot_id == bot.id)) is None

    # Libera o horário e liga stop/alvo pelo ATR
    bot.filters = {"hours_start": "08:30", "hours_end": "17:00", "stop_atr": 1.0, "take_atr": 2.0}
    await db.commit()
    from app.core.redis import get_redis

    await get_redis().delete(f"bot:{bot.id}:last_candle")
    res = await run_tick(db, bot, factory_for(market), NOW)
    assert res.action == "executed", res
    pos = await db.scalar(select(Position).where(Position.bot_id == bot.id))
    assert pos.stop_price is not None and pos.take_price is not None
    assert pos.stop_price < pos.avg_price < pos.take_price
    gap = pos.avg_price - pos.stop_price
    assert float(pos.take_price - pos.avg_price) == pytest.approx(2 * float(gap), rel=1e-6)

    market.price = pos.stop_price - Decimal("0.01")
    res = await run_tick(db, bot, factory_for(market), NOW)
    assert res.action == "executed" and "Stop pelo ATR" in res.detail


async def test_bot_api_filters(client, db, plans):
    await register(client)
    me = (await client.get("/api/v1/me")).json()
    import uuid

    from app.models import SubStatus, Subscription

    db.add(Subscription(user_id=uuid.UUID(me["id"]), plan_id=plans["pro"].id, status=SubStatus.active))
    await db.commit()
    body = {"name": "F", "symbol": "BTCUSDT", "strategy": "ema_cross_day", "order_size_quote": "50", "filters": {"htf": "1m"}}
    r = await client.post("/api/v1/bots", json=body, headers=csrf(client))
    assert r.status_code == 422 and "maior" in r.text  # 1m não é maior que 5m
    body["filters"] = {"regime": True, "htf": "1h", "hours_start": "09:30", "hours_end": "17:00", "stop_atr": 1.5}
    r = await client.post("/api/v1/bots", json=body, headers=csrf(client))
    assert r.status_code == 201, r.text
    saved = r.json()["filters"]
    assert saved == {"regime": True, "htf": "1h", "hours_start": "09:30", "hours_end": "17:00", "stop_atr": 1.5}
    r = await client.patch(f"/api/v1/bots/{r.json()['id']}", json={"filters": {"take_atr": 3}}, headers=csrf(client))
    assert r.status_code == 200 and r.json()["filters"] == {"take_atr": 3.0}
    s = (await client.get("/api/v1/strategies")).json()
    assert {x["code"]: x["family"] for x in s}["rsi_reversion"] == "reversion"
