import math
import uuid

import pytest

from app.engine.backtest import BacktestConfig, run_backtest
from app.models import SubStatus, Subscription
from app.services.brokers.base import Candle
from app.strategies.base import Decision, Strategy, StrategyParams
from app.strategies.library import get_strategy

H = 3_600_000


def bar(i, o, h=None, low=None, c=None):
    c = o if c is None else c
    return Candle(i * H, o, h if h is not None else max(o, c), low if low is not None else min(o, c), c, 1.0, i * H + H - 1)


class Scripted(Strategy):
    """Compra quando vê o fechamento marcado em `buy_at` e vende em `sell_at` (posições pelo close)."""

    code = "scripted"
    name = "teste"
    style = "day"
    description = ""

    class Params(StrategyParams):
        timeframe: str = "1h"  # type: ignore[assignment]

    def __init__(self, buy_at: set[float], sell_at: set[float] = frozenset(), short_at: set[float] = frozenset()):
        self.buy_at, self.sell_at, self.short_at = buy_at, sell_at, short_at
        self.seen_lengths: list[int] = []

    def required_candles(self, params):
        return 2

    def decide(self, candles, position, params, allow_short=False):
        self.seen_lengths.append(candles[-1].open_time)
        last = candles[-1].close
        if last in self.buy_at:
            return Decision("long", "teste")
        if last in self.short_at:
            return Decision("short", "teste")
        if last in self.sell_at:
            return Decision("flat", "teste")
        return Decision.hold()


NOFEE = dict(fee_rate=0.0, slippage_bps=0.0)


def test_entry_happens_on_next_open_no_lookahead():
    candles = [bar(0, 100), bar(1, 100), bar(2, 100), bar(3, 101, c=105), bar(4, 110, c=111), bar(5, 120), bar(6, 120)]
    s = Scripted(buy_at={105}, sell_at={111})
    r = run_backtest(s, s.Params(), candles, BacktestConfig(order_size_quote=100, **NOFEE))
    t = r.trades[0]
    assert t.entry_price == 110  # abertura do candle seguinte ao sinal, não o fechamento 105
    assert t.exit_price == 120  # idem para a saída
    assert t.pnl == pytest.approx(100 / 110 * 120 - 100)
    # a estratégia nunca recebeu candle além do atual
    assert s.seen_lengths == sorted(s.seen_lengths)


def test_fees_and_slippage_make_flat_trade_lose():
    candles = [bar(i, 100) for i in range(4)] + [bar(4, 100, c=99.99), bar(5, 100), bar(6, 100, c=100.01), bar(7, 100), bar(8, 100)]
    s = Scripted(buy_at={99.99}, sell_at={100.01})
    r = run_backtest(s, s.Params(), candles, BacktestConfig(order_size_quote=100, fee_rate=0.001, slippage_bps=5))
    assert r.metrics.trades == 1
    assert r.trades[0].pnl == pytest.approx(-0.3, abs=0.02)  # ~0,1% + 0,1% de taxa + 0,05% x2 de slippage
    assert r.metrics.fees_total == pytest.approx(0.2, abs=0.01)


def test_stop_wins_when_stop_and_target_hit_same_candle():
    candles = [bar(0, 100), bar(1, 100), bar(2, 100), bar(3, 100, c=101), bar(4, 100), bar(5, 100, h=120, low=80), bar(6, 100)]
    s = Scripted(buy_at={101})
    r = run_backtest(s, s.Params(), candles, BacktestConfig(order_size_quote=100, stop_loss_pct=5, take_profit_pct=5, **NOFEE))
    assert r.trades[0].exit_reason == "Stop loss"
    assert r.trades[0].exit_price == pytest.approx(95)


def test_gap_below_stop_fills_at_open():
    candles = [bar(0, 100), bar(1, 100), bar(2, 100), bar(3, 100, c=101), bar(4, 100), bar(5, 70, h=72, low=68), bar(6, 70)]
    s = Scripted(buy_at={101})
    r = run_backtest(s, s.Params(), candles, BacktestConfig(order_size_quote=100, stop_loss_pct=5, **NOFEE))
    assert r.trades[0].exit_price == 70  # abriu abaixo do stop: executa na abertura, não no nível do stop


def test_short_position_profits_when_price_falls_and_stop_is_above():
    candles = [bar(0, 100), bar(1, 100), bar(2, 100), bar(3, 100, c=99), bar(4, 100), bar(5, 90), bar(6, 90, c=91), bar(7, 90), bar(8, 90)]
    s = Scripted(buy_at=set(), sell_at={91}, short_at={99})
    cfg = BacktestConfig(order_units=10, allow_short=True, **NOFEE)
    r = run_backtest(s, s.Params(), candles, cfg)
    t = r.trades[0]
    assert t.side == "short" and t.entry_price == 100 and t.exit_price == 90
    assert t.pnl == pytest.approx(100)  # (100 - 90) x 10 unidades
    # vendido: stop acima da entrada
    up = [bar(0, 100), bar(1, 100), bar(2, 100), bar(3, 100, c=99), bar(4, 100), bar(5, 101, h=110, low=100), bar(6, 100)]
    r2 = run_backtest(Scripted(set(), short_at={99}), s.Params(), up, BacktestConfig(order_units=10, allow_short=True, stop_loss_pct=5, **NOFEE))
    assert r2.trades[0].exit_reason == "Stop loss" and r2.trades[0].exit_price == pytest.approx(105)


def test_short_ignored_when_not_allowed():
    candles = [bar(0, 100), bar(1, 100), bar(2, 100), bar(3, 100, c=99), bar(4, 100), bar(5, 90), bar(6, 90)]
    s = Scripted(buy_at=set(), short_at={99})
    r = run_backtest(s, s.Params(), candles, BacktestConfig(order_units=10, allow_short=False, **NOFEE))
    assert r.metrics.trades == 0


def test_reversal_long_to_short_same_open():
    candles = [bar(0, 100), bar(1, 100), bar(2, 100), bar(3, 100, c=101), bar(4, 100), bar(5, 105, c=99), bar(6, 104), bar(7, 104)]
    s = Scripted(buy_at={101}, short_at={99})
    r = run_backtest(s, s.Params(), candles, BacktestConfig(order_units=1, allow_short=True, **NOFEE))
    assert [t.side for t in r.trades] == ["long", "short"]
    assert r.trades[0].exit_time == r.trades[1].entry_time  # inverteu na mesma abertura


def test_open_position_is_closed_at_end_and_metrics_are_finite():
    candles = [bar(i, 100 + i) for i in range(3)] + [bar(3, 103, c=104)] + [bar(i, 100 + i) for i in range(4, 9)]
    s = Scripted(buy_at={104})
    r = run_backtest(s, s.Params(), candles, BacktestConfig(**NOFEE))
    assert r.open_position_closed_at_end
    assert r.trades[-1].exit_reason == "Fim do período"
    d = r.to_dict()
    assert all(v is None or not isinstance(v, float) or math.isfinite(v) for v in d["metrics"].values())


def test_real_strategy_runs_on_random_walk():
    import random

    rnd = random.Random(7)
    price, candles = 100.0, []
    for i in range(3000):
        o = price
        price = max(1.0, price * (1 + rnd.gauss(0, 0.01)))
        candles.append(Candle(i * H, o, max(o, price) * 1.002, min(o, price) * 0.998, price, 1, i * H + H - 1))
    s = get_strategy("ema_cross_swing")
    r = run_backtest(s, s.parse_params({"timeframe": "1h"}), candles, BacktestConfig(stop_loss_pct=3, take_profit_pct=6))
    m = r.metrics
    assert m.trades > 20
    assert m.wins + m.losses == m.trades
    assert 0 <= m.win_rate_pct <= 100
    assert m.max_drawdown_pct >= 0
    assert len(r.equity) <= 400
    assert sum(x["trades"] for x in r.monthly) == m.trades


# ---------------- API ----------------
async def test_backtest_api(client, db, plans, monkeypatch):
    import random

    from app.api.routes import backtest as route

    async def fake_load(symbol, interval, start_ms, end_ms, source=None):
        rnd, price, out, step = random.Random(1), 100.0, [], route.INTERVAL_MS[interval]
        t = start_ms
        while t < end_ms:
            o = price
            price *= 1 + rnd.gauss(0, 0.01)
            out.append(Candle(t, o, max(o, price), min(o, price), price, 1, t + step - 1))
            t += step
        return out

    monkeypatch.setattr(route, "load_candles", fake_load)
    r = await client.post(
        "/api/v1/auth/register",
        json={"name": "Bia", "email": "bia@example.com", "password": "senhaForte123", "accept_terms": True},
    )
    db.add(Subscription(user_id=uuid.UUID(r.json()["id"]), plan_id=plans["pro"].id, status=SubStatus.active))
    await db.commit()
    headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}

    body = {"strategy": "rsi_reversion", "params": {"timeframe": "1h"}, "symbol": "BTCUSDT", "start": "2025-01-01", "end": "2025-06-30", "stop_loss_pct": 2}
    res = await client.post("/api/v1/backtest", json=body, headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert {"metrics", "trades", "equity", "monthly", "warnings", "ohlc"} <= data.keys()
    assert len(data["ohlc"][0]) == 5
    assert data["timeframe"] == "1h"

    body.update(params={"timeframe": "1m"}, start="2024-01-01")
    res = await client.post("/api/v1/backtest", json=body, headers=headers)
    assert res.status_code == 400  # período longo demais para 1 minuto

    # Com filtros: período de confirmação e comparação com a versão sem filtros
    body.update(params={"timeframe": "1h"}, start="2025-01-01", filters={"regime": True, "htf": "4h", "stop_atr": 1.5, "take_atr": 3}, oos_pct=30)
    res = await client.post("/api/v1/backtest", json=body, headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert [s["label"] for s in data["segments"]] == ["Ajuste", "Confirmação"]
    assert "baseline" in data and data["baseline"]["metrics"]["trades"] >= data["metrics"]["trades"]
    assert data["filtered_entries"] >= 0 and isinstance(data["filter_reasons"], list)
    res = await client.post("/api/v1/backtest", json={**body, "filters": {"htf": "15m"}}, headers=headers)
    assert res.status_code == 422  # tempo maior precisa ser maior que 1h
