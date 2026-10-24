"""Scalp de volta à média, estatísticas do período e martingale simulado no backtest."""
from typing import Literal

import pytest

from app.engine.backtest import BacktestConfig, run_backtest
from app.services.brokers.base import Candle
from app.strategies.base import Decision, Strategy, StrategyParams
from app.strategies.library import get_strategy

STEP = 60_000
MONTH = 31 * 86_400_000


def mk(pares, step=STEP, start=0):
    return [Candle(start + i * step, o, max(o, c), min(o, c), c, 1, start + (i + 1) * step - 1) for i, (o, c) in enumerate(pares)]


# ---------------------------------------------------------------- estratégia de scalp
def test_scalp_entra_abaixo_da_banda_e_sai_na_media():
    s = get_strategy("scalp_media")
    p = s.parse_params({"timeframe": "5m", "trend_ema": 0})
    closes = [100 + (0.3 if i % 2 else -0.3) for i in range(40)] + [99.0, 98.0, 96.5]  # lateral e uma queda forte no fim
    cs = mk([(c, c) for c in closes])
    d = s.decide(cs, "flat", p)
    assert d.target == "long" and d.tag == "compra" and "abaixo da banda" in d.reason
    back = mk([(c, c) for c in closes[:-1] + [100.4]])
    assert s.decide(back, "long", p).target == "flat"  # voltou à média: sai
    assert s.decide(cs, "long", p).target is None  # ainda abaixo da média: segura
    p_trend = s.parse_params({"timeframe": "5m", "trend_ema": 20})
    falling = mk([(c, c) for c in [120 - i for i in range(40)] + [70.0]])
    assert s.decide(falling, "flat", p_trend).target is None  # contra a tendência: não compra


# ---------------------------------------------------------------- estatísticas e martingale
class EveryBar(Strategy):
    """Compra em todo candle e fica 1 candle (para controlar o resultado de cada operação)."""

    code = "teste_todo_candle"
    name = "Teste"
    style = "day"
    description = ""
    trade_bars = 1

    class Params(StrategyParams):
        timeframe: Literal["1m"] = "1m"

    def required_candles(self, params) -> int:  # type: ignore[override]
        return 1

    def decide(self, candles, position, params, allow_short=False):  # type: ignore[override]
        return Decision("long", "teste")


def _seq(results, step=STEP):
    """Candles cuja operação no candle i+1 ganha (W) ou perde (L) 1 ponto."""
    pares = [(100.0, 100.0), (100.0, 100.0)]
    for r in results:
        pares.append((100.0, 101.0 if r == "W" else 99.0))
    return mk(pares, step)


def cfg(**kw):
    base = dict(initial_balance=100_000, order_units=1.0, allow_short=False, fee_rate=0.0, slippage_bps=0.0, max_trades_per_day=3000, timeframe="1m")
    return BacktestConfig(**{**base, **kw})


def test_estatisticas_do_periodo():
    s = EveryBar()
    # 3 meses: +2, -1, +1 (cada "candle" aqui dura um mês para separar os meses)
    r = run_backtest(s, s.parse_params({}), _seq(["W", "W", "L", "W", "L", "L", "W", "W", "W"]), cfg())
    m = r.metrics
    assert (m.wins, m.losses, m.max_consecutive_wins, m.max_consecutive_losses) == (6, 3, 3, 2)
    assert m.breakeven_win_rate_pct == pytest.approx(50.0)  # ganho médio = perda média
    r2 = run_backtest(s, s.parse_params({}), _seq(["W", "L", "W"], step=MONTH), cfg())
    assert (r2.metrics.months_total, r2.metrics.months_positive, r2.metrics.months_negative) == (3, 2, 1)


def test_martingale_dobra_depois_da_perda_e_volta_apos_ganho_ou_ciclo_perdido():
    s = EveryBar()
    seq = ["W", "L", "L", "L", "W", "L", "W"]
    r = run_backtest(s, s.parse_params({}), _seq(seq), cfg(martingale_mult=2.0, martingale_levels=2))
    assert [t.qty for t in r.trades] == [1, 1, 2, 4, 1, 1, 2]  # 3ª perda seguida fecha o ciclo e volta a 1
    mg = r.martingale
    assert mg["cycles_lost"] == 1 and mg["worst_cycle_loss"] == pytest.approx(-7.0)  # 1 + 2 + 4 pontos
    assert mg["max_factor"] == 4 and mg["max_factor_possible"] == 4 and mg["cycle_loss_in_base_stops"] == 7
    assert r.metrics.net_pnl == pytest.approx(1 - 1 - 2 - 4 + 1 - 1 + 2)
    plain = run_backtest(s, s.parse_params({}), _seq(seq), cfg())
    assert plain.martingale == {} and plain.metrics.net_pnl == pytest.approx(3 - 4)
    # a taxa de perda observada vira "um ciclo perdido a cada X ciclos"
    assert mg["cycles_won"] == 3 and mg["cycle_hit_pct"] == pytest.approx(75.0)  # 3 ciclos ganhos, 1 perdido
    assert mg["losses_to_bust"] == 3 and mg["bust_every_cycles"] == pytest.approx(1 / (4 / 7) ** 3)


def test_martingale_a_vista_limitado_ao_saldo():
    s = EveryBar()
    c = BacktestConfig(initial_balance=300, order_size_quote=100, fee_rate=0.0, slippage_bps=0.0, max_trades_per_day=3000, timeframe="1m",
                       martingale_mult=2.0, martingale_levels=3)
    r = run_backtest(s, s.parse_params({}), _seq(["L", "L", "L", "L"]), c)
    notionals = [round(t.qty * t.entry_price, 2) for t in r.trades]
    assert notionals[0] == 100 and notionals[1] == pytest.approx(200, rel=1e-6)
    assert notionals[2] <= 297.01  # pediria 400, mas só há o saldo que sobrou
