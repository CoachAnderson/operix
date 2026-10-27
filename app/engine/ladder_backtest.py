"""Backtest dos robôs de grade (Grid) e compra programada (DCA), com as mesmas regras do robô ao vivo.

Dentro de cada candle o preço percorre abertura → mínima → máxima → fechamento (candle de alta) ou
abertura → máxima → mínima → fechamento (de baixa). A cada ponto, os níveis cruzados executam no próprio nível
(como a ordem a mercado disparada quando o preço cruza); se o preço já abriu além do nível (salto), executa no
ponto. Taxa (cobrada no ativo comprado, como na Binance) e escorregamento entram em todas as compras e vendas.

Cada "operação" do relatório é um lote completo: no Grid, a compra numa grade e a venda na grade de cima; na DCA,
um ciclo inteiro (todas as compras até a venda). Lotes ainda abertos no fim são vendidos no último preço.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.engine.backtest import (
    BacktestConfig,
    BacktestResult,
    SegmentStats,
    Trade,
    _downsample,
    _metrics,
    _monthly,
    _segment,
    _warnings,
)
from app.services.brokers.base import Candle
from app.strategies import ladder as L
from app.strategies.base import Strategy


@dataclass
class _Lot:
    qty: float  # líquida (já sem a taxa cobrada no ativo)
    cost: float  # dinheiro pago
    fee: float  # taxa da compra, em moeda de cotação
    price: float  # preço pago (com escorregamento)
    raw: float  # preço de mercado sem escorregamento
    time: int


def _path(bar: Candle) -> list[tuple[float, int]]:
    mid = bar.open_time + (bar.close_time - bar.open_time) // 2
    if bar.close >= bar.open:
        return [(bar.open, bar.open_time), (bar.low, mid), (bar.high, mid), (bar.close, bar.close_time)]
    return [(bar.open, bar.open_time), (bar.high, mid), (bar.low, mid), (bar.close, bar.close_time)]


def _exec_price(level: float | None, prev: float, pt: float) -> float:
    """Executa no nível se o trecho prev→pt passou por ele; senão no próprio ponto (salto de preço)."""
    if level is not None and min(prev, pt) <= level <= max(prev, pt):
        return level
    return pt


def run_ladder_backtest(strategy: Strategy, params, candles: list[Candle], cfg: BacktestConfig) -> BacktestResult:
    if len(candles) < 10:
        raise ValueError(f"São necessários pelo menos 10 candles; o período tem {len(candles)}.")
    fee_rate = cfg.fee_rate
    slip = cfg.slippage_bps / 10_000
    size = cfg.order_size_quote
    grid = isinstance(strategy, L.GridSpot)

    cash = cfg.initial_balance
    trades: list[Trade] = []
    equity: list[tuple[int, float, float]] = []
    peak, max_dd = cash, 0.0
    bars_holding = 0
    skipped = 0  # compras que não couberam no saldo
    max_held = 0
    stopped_at: int | None = None

    first = candles[0]
    capital = L.capital_needed(strategy, params, size) or size
    bh_units = min(capital, cfg.initial_balance) / first.open

    def buy(quote: float, raw: float, when: int) -> _Lot | None:
        nonlocal cash, skipped
        if quote > cash + 1e-9:
            skipped += 1
            return None
        price = raw * (1 + slip)
        gross = quote / price
        fee_base = gross * fee_rate
        cash -= quote
        return _Lot(qty=gross - fee_base, cost=quote, fee=fee_base * price, price=price, raw=raw, time=when)

    def sell(lots: list[_Lot], raw: float, when: int, reason: str) -> float:
        """Vende os lotes juntos e registra UMA operação; devolve o resultado."""
        nonlocal cash
        qty = sum(x.qty for x in lots)
        cost = sum(x.cost for x in lots)
        price = raw * (1 - slip)
        gross = qty * price
        fee = gross * fee_rate
        cash += gross - fee
        pnl = gross - fee - cost
        raw_entry = sum(x.raw * x.qty for x in lots) / qty if qty else raw
        trades.append(Trade(
            side="long", entry_time=min(x.time for x in lots), exit_time=when,
            entry_price=cost / qty if qty else price, exit_price=price, qty=qty, pnl=pnl,
            return_pct=pnl / cost * 100 if cost else 0.0, fees=sum(x.fee for x in lots) + fee, exit_reason=reason,
            tag=None, move_pct=(raw - raw_entry) / raw_entry * 100 if raw_entry else 0.0,
        ))
        return pnl

    # ------------------------------------------------------------------ Grid
    if grid:
        state = L.grid_new_state(params, first.open)
        lots: dict[int, _Lot] = {}
        levels: list[float] = state["levels"]
        for i in state["initial"]:
            lot = buy(size, first.open, first.open_time)
            if lot:
                lots[i] = lot
        state["lots"] = {str(i): True for i in lots}
        state["armed"] = L.grid_rearm(state, first.open)
        stop = L.grid_stop_price(params, state)
        prev = first.open
        for bar in candles:
            if stopped_at is None:
                for pt, when in _path(bar):
                    if stop is not None and pt <= stop and lots:
                        sell(list(lots.values()), _exec_price(stop, prev, pt), when, "Stop abaixo da faixa")
                        lots.clear()
                        stopped_at = when
                        break
                    state["lots"] = {str(i): True for i in lots}
                    sells, buys = L.grid_triggers(state, pt)
                    for i in sells:
                        sell([lots.pop(i)], _exec_price(levels[i + 1], prev, pt), when, f"Venda na grade {i + 1}")
                    for i in buys:
                        lot = buy(size, _exec_price(levels[i], prev, pt), when)
                        if lot:
                            lots[i] = lot
                    state["lots"] = {str(i): True for i in lots}
                    state["armed"] = L.grid_rearm(state, pt)
                    prev = pt
                    max_held = max(max_held, len(lots))
            if lots:
                bars_holding += 1
            value = cash + sum(x.qty for x in lots.values()) * bar.close
            peak = max(peak, value)
            max_dd = max(max_dd, (peak - value) / peak * 100 if peak > 0 else 0.0)
            equity.append((bar.close_time, value, cfg.initial_balance + bh_units * (bar.close - first.open)))
        open_lots = list(lots.values())
        lo, hi = L.grid_step_pct(levels)
        extra = {
            "kind": "grid", "levels": levels, "lower": levels[0], "upper": levels[-1], "step_min_pct": lo, "step_max_pct": hi,
            "capital": capital, "rounds": sum(1 for t in trades if t.exit_reason.startswith("Venda na grade")),
            "max_lots_held": max_held, "open_lots_end": len(open_lots), "stopped_at": stopped_at,
            "below_range_pct": sum(1 for b in candles if b.close < levels[0]) / len(candles) * 100,
            "above_range_pct": sum(1 for b in candles if b.close > levels[-1]) / len(candles) * 100,
        }

    # ------------------------------------------------------------------ DCA
    else:
        state = L.dca_new_state()
        cycle: list[_Lot] = []
        prev = first.open
        orders_per_cycle: list[int] = []
        longest_ms = 0
        for bar in candles:
            if not state.get("done"):
                for pt, when in _path(bar):
                    for _ in range(params.max_orders + 1):  # várias compras no mesmo ponto numa queda forte
                        act = L.dca_action(params, state, pt, when)
                        if not act:
                            break
                        kind, reason, level = act
                        raw = _exec_price(level, prev, pt)
                        if kind == "buy":
                            lot = buy(L.dca_order_quote(params, size, int(state["orders"])), raw, when)
                            if not lot:
                                break
                            cycle.append(lot)
                            state = L.dca_after_buy(state, lot.qty, lot.cost, lot.fee, raw, when)
                        else:
                            orders_per_cycle.append(len(cycle))
                            longest_ms = max(longest_ms, when - cycle[0].time)
                            pnl = sell(cycle, raw, when, reason)
                            cycle = []
                            state = L.dca_after_sell(params, state, pnl, when)
                            if reason.startswith("Stop"):
                                stopped_at = when
                            break
                    prev = pt
            max_held = max(max_held, len(cycle))
            if cycle:
                bars_holding += 1
            value = cash + sum(x.qty for x in cycle) * bar.close
            peak = max(peak, value)
            max_dd = max(max_dd, (peak - value) / peak * 100 if peak > 0 else 0.0)
            equity.append((bar.close_time, value, cfg.initial_balance + bh_units * (bar.close - first.open)))
        open_lots = cycle
        extra = {
            "kind": "dca", "capital": capital, "cycles": len(orders_per_cycle),
            "avg_orders_per_cycle": sum(orders_per_cycle) / len(orders_per_cycle) if orders_per_cycle else 0.0,
            "max_orders_used": max_held, "max_orders": params.max_orders,
            "longest_cycle_days": longest_ms / 86_400_000, "open_orders_end": len(open_lots),
            "stops": sum(1 for t in trades if t.exit_reason.startswith("Stop")),
        }

    closed_at_end = False
    last = candles[-1]
    open_value = 0.0
    if open_lots:
        open_value = sum(x.qty for x in open_lots) * last.close - sum(x.cost for x in open_lots)
        sell(open_lots, last.close, last.close_time, "Fim do período (vendido no último preço)")
        closed_at_end = True
        equity[-1] = (last.close_time, cash, equity[-1][2])
    extra["skipped_buys"] = skipped
    extra["open_result_end"] = open_value

    bh_final = cfg.initial_balance + bh_units * (last.close - first.open)
    metrics = _metrics(trades, cfg, cash, equity, max_dd, bars_holding / len(candles) * 100, bh_final / cfg.initial_balance)
    segments: list[SegmentStats] = []
    if cfg.split_time and first.open_time < cfg.split_time < last.close_time:
        segments = [_segment("Ajuste", trades, equity, first.open_time, cfg.split_time),
                    _segment("Confirmação", trades, equity, cfg.split_time, last.close_time + 1)]

    warnings = _ladder_warnings(strategy, params, extra, cfg, closed_at_end)
    warnings += [w for w in _warnings(metrics, strategy, candles, 0) if "rendeu menos" not in w]
    return BacktestResult(
        metrics=metrics, trades=trades, equity=_downsample(equity), monthly=_monthly(trades), warnings=warnings,
        candles=len(candles), start=first.open_time, end=last.close_time, open_position_closed_at_end=closed_at_end,
        params=params.model_dump(exclude_none=True), ohlc=[(c.open_time, c.open, c.high, c.low, c.close) for c in candles],
        segments=segments, analysis={}, ladder=extra,
    )


def _ladder_warnings(strategy: Strategy, params, extra: dict, cfg: BacktestConfig, closed_at_end: bool) -> list[str]:
    w: list[str] = []
    cost_pct = cfg.fee_rate * 200 + cfg.slippage_bps / 50
    if extra["capital"] > cfg.initial_balance + 1e-9:
        w.append(f"O saldo inicial ({cfg.initial_balance:,.2f}) é menor que o dinheiro necessário ({extra['capital']:,.2f}): "
                 f"{extra['skipped_buys']} compra(s) não aconteceram por falta de saldo.")
    if extra["kind"] == "grid":
        if extra["step_min_pct"] < cost_pct * 2:
            w.append(f"Cada grade rende {extra['step_min_pct']:.2f}%, perto do custo de ida e volta (~{cost_pct:.2f}%): sobra pouco "
                     "por grade. Use menos grades ou uma faixa maior.")
        if extra["below_range_pct"] > 25:
            w.append(f"O preço ficou abaixo da faixa em {extra['below_range_pct']:.0f}% do tempo: nesse trecho o robô só segura lotes "
                     "com perda e não opera.")
        if extra["above_range_pct"] > 25:
            w.append(f"O preço ficou acima da faixa em {extra['above_range_pct']:.0f}% do tempo: nesse trecho o robô fica só com "
                     "dinheiro, sem operar.")
    else:
        if params.volume_mult > 1:
            w.append(f"Com multiplicador de volume {params.volume_mult:g}, a última compra do ciclo vale "
                     f"{params.volume_mult ** (params.max_orders - 1):.1f}× a primeira: o ciclo fica caro rápido.")
        if extra["max_orders_used"] >= params.max_orders and params.trigger == "drop":
            w.append("Em algum ciclo o robô usou todas as compras e ficou esperando a volta do preço.")
    if closed_at_end:
        sign = "lucro" if extra["open_result_end"] >= 0 else "perda"
        w.append(f"No fim do período ainda havia lotes comprados ({sign} aberta de {abs(extra['open_result_end']):,.2f}); "
                 "o relatório os vende no último preço. Ao vivo, eles continuariam esperando.")
    w.append("Toda operação fechada costuma dar lucro nestes robôs: o risco está nos lotes que ficam presos numa queda. "
             "Olhe a queda máxima do patrimônio, não só o acerto.")
    return w
