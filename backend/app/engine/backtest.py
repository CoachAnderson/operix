"""Backtest: roda uma estratégia sobre candles históricos com as mesmas regras do robô ao vivo.

Regras para não "olhar o futuro":
- a estratégia decide no FECHAMENTO do candle i (só com candles até i);
- a ordem é executada na ABERTURA do candle i+1 (como o robô ao vivo, que envia a mercado logo após o fechamento);
- stop loss e alvo são checados dentro do candle pelas máximas/mínimas. Se os dois forem tocados no mesmo
  candle, assume-se que o STOP veio primeiro (hipótese conservadora). Se o candle abrir além do nível
  (gap), a execução é no preço de abertura;
- taxas e slippage são cobrados em todas as entradas e saídas.

Contabilidade única para à vista e margem: saldo = saldo inicial + resultados realizados; patrimônio = saldo +
resultado aberto. Em cripto à vista o tamanho é em moeda de cotação; em forex, em unidades (lotes × tamanho do lote).
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.services.brokers.base import Candle
from app.strategies import filters as flt
from app.strategies.base import Strategy, StrategyParams, Target

MAX_EQUITY_POINTS = 400
BRT = ZoneInfo("America/Sao_Paulo")


@dataclass
class BacktestConfig:
    initial_balance: float = 1000.0
    order_size_quote: float = 100.0  # cripto: valor por ordem
    order_units: float | None = None  # forex: unidades por ordem (substitui order_size_quote)
    allow_short: bool = False
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    max_daily_loss_quote: float | None = None
    max_trades_per_day: int = 50
    fee_rate: float = 0.001  # por lado, sobre o valor negociado (0,1% = taxa spot padrão da Binance)
    slippage_bps: float = 5  # contra você em cada execução
    filters: flt.BotFilters | None = None  # filtros de entrada e stop/alvo pelo ATR
    family: flt.Family = "trend"
    timeframe: str | None = None  # tempo gráfico da estratégia (para o filtro de tempo maior)
    split_time: int | None = None  # início do período de confirmação (fora da amostra), em ms
    risk_pct: float | None = None  # tamanho pelo risco: % do saldo perdido se o stop for atingido
    max_leverage: float | None = None  # valor da posição ÷ saldo
    unit_step: float | None = None  # forex/B3: múltiplo de unidades negociável (lote mínimo, 1 contrato)


@dataclass
class Trade:
    side: str  # long | short
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    qty: float
    pnl: float  # já com taxas
    return_pct: float  # sobre o valor da posição na entrada
    fees: float
    exit_reason: str
    tag: str | None = None  # padrão que gerou a entrada (ex.: "4x1" na Reversão AMS)
    move_pct: float = 0.0  # variação do preço a favor da posição, sem taxa nem escorregamento


@dataclass
class Metrics:
    trades: int
    wins: int
    losses: int
    win_rate_pct: float
    avg_win: float
    avg_loss: float
    payoff: float | None  # ganho médio / perda média
    expectancy: float  # resultado médio por operação
    expectancy_pct: float  # resultado médio por operação (% do valor da posição)
    profit_factor: float | None  # soma dos ganhos / soma das perdas
    net_pnl: float
    return_pct: float
    buy_hold_pct: float
    max_drawdown_pct: float
    fees_total: float
    exposure_pct: float  # % do tempo posicionado
    avg_hold_minutes: float
    best_trade: float
    worst_trade: float
    max_consecutive_losses: int
    final_balance: float
    long_trades: int = 0
    short_trades: int = 0


@dataclass
class SegmentStats:
    """Números de um trecho do período (ajuste ou confirmação)."""

    label: str
    start: int
    end: int
    trades: int
    win_rate_pct: float
    payoff: float | None
    profit_factor: float | None
    expectancy_pct: float
    return_pct: float
    buy_hold_pct: float
    max_drawdown_pct: float
    net_pnl: float


@dataclass
class BacktestResult:
    metrics: Metrics
    trades: list[Trade]
    equity: list[tuple[int, float, float]]  # (tempo, patrimônio do robô, comprar e segurar)
    monthly: list[dict]
    warnings: list[str]
    candles: int
    start: int
    end: int
    open_position_closed_at_end: bool = False
    params: dict = field(default_factory=dict)
    ohlc: list[tuple[int, float, float, float, float]] = field(default_factory=list)  # candles do período testado
    segments: list[SegmentStats] = field(default_factory=list)  # ajuste × confirmação
    filtered_entries: int = 0  # entradas que os filtros barraram
    filter_reasons: list[dict] = field(default_factory=list)  # motivos mais comuns
    analysis: dict = field(default_factory=dict)  # acerto de direção, teste estatístico, por padrão e por hora

    def to_dict(self) -> dict:
        d = asdict(self)
        d["metrics"] = {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in d["metrics"].items()}
        return d


@dataclass
class _Position:
    side: str
    qty: float
    entry_price: float
    entry_time: int
    entry_fee: float
    stop: float | None = None  # preço (modo ATR)
    take: float | None = None
    raw_entry: float = 0.0  # preço de mercado na entrada, sem escorregamento
    tag: str | None = None

    @property
    def sign(self) -> int:
        return 1 if self.side == "long" else -1

    def unrealized(self, price: float) -> float:
        return self.sign * (price - self.entry_price) * self.qty


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d")


def _month(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m")


def filter_warmup(f: flt.BotFilters | None, timeframe: str | None) -> int:
    """Candles extras que os filtros precisam antes do início do teste."""
    if not f:
        return 0
    n = f.lookback()
    if f.htf and timeframe:
        ratio = flt.TF_MS[f.htf] // flt.TF_MS[timeframe]
        n = max(n, (f.htf_lookback() + 1) * ratio)
    return n


def run_backtest(strategy: Strategy, params: StrategyParams, candles: list[Candle], cfg: BacktestConfig) -> BacktestResult:
    f = cfg.filters if cfg.filters and cfg.filters.active else None
    strat_window = strategy.required_candles(params)
    warmup = max(strat_window, filter_warmup(f, cfg.timeframe))
    filtered = 0
    reasons: dict[str, int] = defaultdict(int)
    pending_atr: float | None = None
    pending_tag: str | None = None
    trade_bars = strategy.trade_bars
    tf_ms = flt.TF_MS.get(params.timeframe, 60_000)
    if len(candles) <= warmup + 2:
        raise ValueError(
            f"São necessários mais de {warmup + 2} candles para esta estratégia; o período tem {len(candles)}. "
            "Aumente o período ou use um tempo gráfico menor."
        )

    fee = cfg.fee_rate
    slip = cfg.slippage_bps / 10_000
    max_hold = strategy.max_hold_minutes(params)
    max_hold_ms = max_hold * 60_000 if max_hold else None
    spot = cfg.order_units is None  # à vista: não pode gastar mais do que tem

    balance = cfg.initial_balance
    pos: _Position | None = None
    pending: Target | None = None
    trades: list[Trade] = []
    equity: list[tuple[int, float, float]] = []
    peak = cfg.initial_balance
    max_dd = 0.0
    bars_in_position = 0
    day_trades: dict[str, int] = defaultdict(int)
    day_pnl: dict[str, float] = defaultdict(float)
    bh_start = candles[warmup].open
    # Referência justa: comprar e segurar O MESMO TAMANHO de posição do robô.
    bh_units = cfg.order_units if cfg.order_units is not None else min(cfg.order_size_quote, cfg.initial_balance) / bh_start

    def buy_hold_value(close: float) -> float:
        return cfg.initial_balance + bh_units * (close - bh_start)

    def open_position(side: str, raw_price: float, when: int, atr_now: float | None = None, tag: str | None = None) -> None:
        nonlocal pos, balance
        price = raw_price * (1 + slip) if side == "long" else raw_price * (1 - slip)
        if cfg.order_units is not None:
            qty = cfg.order_units
        else:
            spend = min(cfg.order_size_quote, balance)
            if spend <= 0:
                return
            qty = spend / price
        if cfg.risk_pct or cfg.max_leverage:
            sign = 1 if side == "long" else -1
            stop = None
            if f and f.stop_atr and atr_now:
                stop = price - sign * f.stop_atr * atr_now
            elif cfg.stop_loss_pct:
                stop = price * (1 - sign * cfg.stop_loss_pct / 100)
            if cfg.risk_pct:
                if not stop or balance <= 0:
                    return  # sem stop não dá para dimensionar pelo risco
                qty = balance * cfg.risk_pct / 100 / abs(price - stop)
            if cfg.max_leverage:
                qty = min(qty, max(balance, 0) * cfg.max_leverage / price)
            if spot:
                qty = min(qty, max(balance, 0) / price)
            if cfg.unit_step:
                qty = math.floor(qty / cfg.unit_step + 1e-9) * cfg.unit_step
            if qty <= 0:
                return
        entry_fee = qty * price * fee
        balance -= entry_fee
        pos = _Position(side=side, qty=qty, entry_price=price, entry_time=when, entry_fee=entry_fee, raw_entry=raw_price, tag=tag)
        if f and f.atr_exits and atr_now:
            pos.stop, pos.take = flt.atr_levels(f, side, price, atr_now)  # type: ignore[arg-type]
        day_trades[_day(when)] += 1

    def close_position(raw_price: float, when: int, reason: str) -> None:
        nonlocal pos, balance
        assert pos is not None
        price = raw_price * (1 - slip) if pos.side == "long" else raw_price * (1 + slip)
        exit_fee = pos.qty * price * fee
        gross = pos.unrealized(price)
        pnl = gross - pos.entry_fee - exit_fee
        balance += gross - exit_fee
        trades.append(
            Trade(
                side=pos.side,
                entry_time=pos.entry_time,
                exit_time=when,
                entry_price=pos.entry_price,
                exit_price=price,
                qty=pos.qty,
                pnl=pnl,
                return_pct=pnl / (pos.qty * pos.entry_price) * 100,
                fees=pos.entry_fee + exit_fee,
                exit_reason=reason,
                tag=pos.tag,
                move_pct=pos.sign * (raw_price - pos.raw_entry) / pos.raw_entry * 100 if pos.raw_entry else 0.0,
            )
        )
        day_trades[_day(when)] += 1
        day_pnl[_day(when)] += pnl
        pos = None

    for i in range(warmup, len(candles)):
        bar = candles[i]
        today = _day(bar.open_time)

        # 1) O que foi decidido no fechamento anterior executa na abertura deste candle.
        if pending is not None:
            if pos is not None and pos.side != pending:
                close_position(bar.open, bar.open_time, "Sinal de saída da estratégia")
            if pos is None and pending in ("long", "short"):
                open_position(pending, bar.open, bar.open_time, pending_atr, pending_tag)
            pending = None
            pending_atr = None
            pending_tag = None

        # 2) Saídas de risco dentro do candle (stop primeiro quando os dois são tocados).
        if pos is not None:
            e = pos.entry_price
            atr_mode = f is not None and f.atr_exits
            if pos.side == "long":
                sl = pos.stop if atr_mode and f.stop_atr else (e * (1 - cfg.stop_loss_pct / 100) if cfg.stop_loss_pct else None)
                tp = pos.take if atr_mode and f.take_atr else (e * (1 + cfg.take_profit_pct / 100) if cfg.take_profit_pct else None)
                if sl is not None and bar.low <= sl:
                    close_position(min(sl, bar.open), bar.open_time, "Stop loss")
                elif tp is not None and bar.high >= tp:
                    close_position(max(tp, bar.open), bar.open_time, "Alvo de lucro")
            else:
                sl = pos.stop if atr_mode and f.stop_atr else (e * (1 + cfg.stop_loss_pct / 100) if cfg.stop_loss_pct else None)
                tp = pos.take if atr_mode and f.take_atr else (e * (1 - cfg.take_profit_pct / 100) if cfg.take_profit_pct else None)
                if sl is not None and bar.high >= sl:
                    close_position(max(sl, bar.open), bar.open_time, "Stop loss")
                elif tp is not None and bar.low <= tp:
                    close_position(min(tp, bar.open), bar.open_time, "Alvo de lucro")
            if pos is not None and max_hold_ms and bar.close_time - pos.entry_time >= max_hold_ms:
                close_position(bar.close, bar.close_time, f"Tempo máximo de {max_hold} min")

        if pos is not None:
            bars_in_position += 1

        # 2b) Operação de duração fixa (ex.: Reversão AMS): sai no fechamento do último candle da operação.
        if pos is not None and trade_bars and bar.open_time >= pos.entry_time + (trade_bars - 1) * tf_ms:
            close_position(bar.close, bar.close_time, f"Fim da operação de {trade_bars} candle(s)")

        # 3) Decisão da estratégia no fechamento, só com o passado.
        window = candles[max(0, i + 1 - strat_window - 2) : i + 1]
        current: Target = pos.side if pos else "flat"  # type: ignore[assignment]
        decision = strategy.decide(window, current, params, cfg.allow_short)
        target = decision.target
        if target == "short" and not cfg.allow_short:
            target = "flat"
        if trade_bars and target in ("long", "short") and i + 1 < len(candles) and candles[i + 1].open_time != bar.close_time + 1:
            target = "flat"  # duração fixa: o candle da entrada precisa vir logo depois (sem lacuna)
        if target is not None and target != current and i + 1 < len(candles):
            if target in ("long", "short"):
                blocked = day_trades[today] >= cfg.max_trades_per_day or (
                    cfg.max_daily_loss_quote is not None and day_pnl[today] <= -cfg.max_daily_loss_quote
                ) or (spot and balance <= 0)
                if not blocked and f is not None and f.any_entry_filter:
                    reason = _filter_check(f, cfg, target, candles, i, bar)
                    if reason:
                        blocked = True
                        filtered += 1
                        reasons[flt.reason_kind(reason)] += 1
                if blocked:
                    target = "flat" if pos is not None else None  # sem nova entrada; ainda pode sair
                elif f is not None and f.atr_exits:
                    pending_atr = flt.atr_value(candles[max(0, i + 1 - f.lookback()) : i + 1], f.atr_period)
            pending = target
            pending_tag = decision.tag if target in ("long", "short") else None

        # 4) Patrimônio marcado no fechamento.
        value = balance + (pos.unrealized(bar.close) if pos else 0.0)
        peak = max(peak, value)
        max_dd = max(max_dd, (peak - value) / peak * 100 if peak > 0 else 0.0)
        equity.append((bar.close_time, value, buy_hold_value(bar.close)))

    closed_at_end = False
    if pos is not None:
        last = candles[-1]
        close_position(last.close, last.close_time, "Fim do período")
        closed_at_end = True
        equity[-1] = (last.close_time, balance, equity[-1][2])

    total_bars = len(candles) - warmup
    bh_final = buy_hold_value(candles[-1].close)
    metrics = _metrics(trades, cfg, balance, equity, max_dd, bars_in_position / total_bars * 100, bh_final / cfg.initial_balance)
    segments: list[SegmentStats] = []
    if cfg.split_time and candles[warmup].open_time < cfg.split_time < candles[-1].close_time:
        segments = [
            _segment("Ajuste", trades, equity, candles[warmup].open_time, cfg.split_time),
            _segment("Confirmação", trades, equity, cfg.split_time, candles[-1].close_time + 1),
        ]
    return BacktestResult(
        metrics=metrics,
        trades=trades,
        equity=_downsample(equity),
        monthly=_monthly(trades),
        warnings=_warnings(metrics, strategy, candles, warmup),
        candles=len(candles),
        start=candles[warmup].open_time,
        end=candles[-1].close_time,
        open_position_closed_at_end=closed_at_end,
        params=params.model_dump(exclude_none=True),
        ohlc=[(c.open_time, c.open, c.high, c.low, c.close) for c in candles[warmup:]],
        segments=segments,
        filtered_entries=filtered,
        filter_reasons=[{"reason": k, "count": v} for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])[:5]],
        analysis=analyze(trades, cfg),
    )


def _filter_check(f: flt.BotFilters, cfg: BacktestConfig, target: str, candles: list[Candle], i: int, bar: Candle) -> str | None:
    """Mesma checagem do robô ao vivo, só com candles fechados até o candle i."""
    now_ms = bar.close_time + 1
    window = candles[max(0, i + 1 - max(f.lookback(), 3)) : i + 1]
    htf = None
    if f.htf and cfg.timeframe:
        ratio = flt.TF_MS[f.htf] // flt.TF_MS[cfg.timeframe]
        span = (f.htf_lookback() + 2) * ratio
        htf = flt.resample(candles[max(0, i + 1 - span) : i + 1], f.htf, now_ms)
    return flt.entry_block(f, cfg.family, target, window, htf, now_ms)  # type: ignore[arg-type]


def _segment(label: str, trades: list[Trade], equity: list[tuple[int, float, float]], start: int, end: int) -> SegmentStats:
    """Números de um trecho: operações que ENTRARAM no trecho e a curva de patrimônio dele."""
    ts = [t for t in trades if start <= t.entry_time < end]
    pts = [p for p in equity if start <= p[0] < end]
    if not pts:
        pts = [equity[-1]]
    first_val, first_bh = pts[0][1], pts[0][2]
    before = [p for p in equity if p[0] < start]
    if before:  # começa do patrimônio no fim do trecho anterior
        first_val, first_bh = before[-1][1], before[-1][2]
    peak, dd = first_val, 0.0
    for _, v, _ in pts:
        peak = max(peak, v)
        dd = max(dd, (peak - v) / peak * 100 if peak > 0 else 0.0)
    pnls = [t.pnl for t in ts]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    avg_w = sum(wins) / len(wins) if wins else 0.0
    avg_l = sum(losses) / len(losses) if losses else 0.0
    last_val, last_bh = pts[-1][1], pts[-1][2]
    return SegmentStats(
        label=label,
        start=start,
        end=end,
        trades=len(ts),
        win_rate_pct=len(wins) / len(ts) * 100 if ts else 0.0,
        payoff=(avg_w / -avg_l) if wins and avg_l < 0 else None,
        profit_factor=(sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else None,
        expectancy_pct=sum(t.return_pct for t in ts) / len(ts) if ts else 0.0,
        return_pct=(last_val - first_val) / first_val * 100 if first_val else 0.0,
        buy_hold_pct=(last_bh - first_bh) / first_bh * 100 if first_bh else 0.0,
        max_drawdown_pct=dd,
        net_pnl=last_val - first_val,
    )


def _metrics(trades: list[Trade], cfg: BacktestConfig, final: float, equity, max_dd: float, exposure: float, bh_ratio: float) -> Metrics:
    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win, gross_loss = sum(wins), -sum(losses)
    streak = worst_streak = 0
    for p in pnls:
        streak = streak + 1 if p <= 0 else 0
        worst_streak = max(worst_streak, streak)
    n = len(trades)
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    return Metrics(
        trades=n,
        wins=len(wins),
        losses=len(losses),
        win_rate_pct=len(wins) / n * 100 if n else 0.0,
        avg_win=avg_win,
        avg_loss=avg_loss,
        payoff=(avg_win / -avg_loss) if wins and avg_loss < 0 else None,
        expectancy=sum(pnls) / n if n else 0.0,
        expectancy_pct=sum(t.return_pct for t in trades) / n if n else 0.0,
        profit_factor=(gross_win / gross_loss) if gross_loss > 0 else None,
        net_pnl=final - cfg.initial_balance,
        return_pct=(final - cfg.initial_balance) / cfg.initial_balance * 100,
        buy_hold_pct=(bh_ratio - 1) * 100,
        max_drawdown_pct=max_dd,
        fees_total=sum(t.fees for t in trades),
        exposure_pct=exposure,
        avg_hold_minutes=sum((t.exit_time - t.entry_time) / 60_000 for t in trades) / n if n else 0.0,
        best_trade=max(pnls) if pnls else 0.0,
        worst_trade=min(pnls) if pnls else 0.0,
        max_consecutive_losses=worst_streak,
        final_balance=final,
        long_trades=sum(1 for t in trades if t.side == "long"),
        short_trades=sum(1 for t in trades if t.side == "short"),
    )


# ---------------------------------------------------------------- Estatística
def binom_p_two_sided(k: int, n: int) -> float:
    """p-valor exato do teste binomial bilateral com p = 0,5 (soma das caudas igualmente ou menos prováveis)."""
    if n == 0:
        return float("nan")
    k = max(k, n - k)
    # P(X >= k) para Binomial(n, 0,5), em escala logarítmica para não estourar com n grande.
    log_half_n = -n * math.log(2)
    terms = [math.lgamma(n + 1) - math.lgamma(j + 1) - math.lgamma(n - j + 1) + log_half_n for j in range(k, n + 1)]
    m = max(terms)
    tail = math.exp(m) * sum(math.exp(t - m) for t in terms)
    return min(1.0, 2 * tail) if 2 * k != n else 1.0


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    meia = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centro - meia, centro + meia


def _group(trades: list[Trade]) -> dict:
    w = sum(1 for t in trades if t.move_pct > 0)
    l = sum(1 for t in trades if t.move_pct < 0)
    lo, hi = wilson(w, w + l)
    return {
        "trades": len(trades), "wins": w, "losses": l, "ties": len(trades) - w - l,
        "hit_pct": w / (w + l) * 100 if w + l else None,
        "ci_low_pct": lo * 100 if w + l else None, "ci_high_pct": hi * 100 if w + l else None,
        "p_value": binom_p_two_sided(w, w + l) if w + l else None,
        "net_wins": sum(1 for t in trades if t.pnl > 0),
        "pnl": sum(t.pnl for t in trades),
        "avg_move_pct": sum(t.move_pct for t in trades) / len(trades) if trades else 0.0,
    }


def analyze(trades: list[Trade], cfg: BacktestConfig) -> dict:
    """Acerto de DIREÇÃO (o preço andou a favor?), separado do resultado depois dos custos.

    Empate = saída no mesmo preço da entrada. O teste binomial verifica se o acerto de direção é diferente de 50%
    (o que se esperaria por acaso). Também mostra o custo médio de ida e volta contra o movimento médio.
    """
    if not trades:
        return {}
    out = _group(trades)
    out["significant"] = out["p_value"] is not None and out["p_value"] < 0.05
    out["avg_abs_move_pct"] = sum(abs(t.move_pct) for t in trades) / len(trades)
    out["avg_cost_pct"] = sum(t.fees / (t.qty * t.entry_price) * 100 for t in trades) / len(trades) + 2 * cfg.slippage_bps / 100
    tags = sorted({t.tag for t in trades if t.tag})
    out["by_tag"] = [{"tag": tag, **_group([t for t in trades if t.tag == tag])} for tag in tags]
    hours: dict[int, list[Trade]] = defaultdict(list)
    for t in trades:
        hours[datetime.fromtimestamp(t.entry_time / 1000, BRT).hour].append(t)
    out["by_hour"] = [{"hour": h, **_group(hours[h])} for h in sorted(hours)]
    for side in ("long", "short"):
        sub = [t for t in trades if t.side == side]
        out[f"{side}_hit_pct"] = _group(sub)["hit_pct"] if sub else None
    return out


def _downsample(points: list[tuple[int, float, float]]) -> list[tuple[int, float, float]]:
    if len(points) <= MAX_EQUITY_POINTS:
        return points
    step = len(points) / MAX_EQUITY_POINTS
    out = [points[int(i * step)] for i in range(MAX_EQUITY_POINTS - 1)]
    out.append(points[-1])
    return out


def _monthly(trades: list[Trade]) -> list[dict]:
    months: dict[str, dict] = {}
    for t in trades:
        m = months.setdefault(_month(t.exit_time), {"month": _month(t.exit_time), "trades": 0, "wins": 0, "pnl": 0.0})
        m["trades"] += 1
        m["wins"] += t.pnl > 0
        m["pnl"] += t.pnl
    return [months[k] for k in sorted(months)]


def _warnings(m: Metrics, strategy: Strategy, candles: list[Candle], warmup: int) -> list[str]:
    w: list[str] = []
    if m.trades == 0:
        w.append("Nenhuma operação no período. Experimente um período maior ou outros parâmetros.")
    elif m.trades < 30:
        w.append(f"Só {m.trades} operações: amostra pequena, o resultado pode ser obra do acaso. O ideal é passar de 100.")
    if m.trades and m.return_pct < m.buy_hold_pct:
        w.append("O robô rendeu menos do que comprar o mesmo tamanho de posição no início e segurar até o fim do período.")
    if m.profit_factor is not None and m.profit_factor < 1:
        w.append("Fator de lucro abaixo de 1: as perdas somaram mais que os ganhos.")
    days = (candles[-1].close_time - candles[warmup].open_time) / 86_400_000
    if strategy.style == "swing" and days < 180:
        w.append("Para swing trade, teste pelo menos 6 meses, passando por alta, queda e lateralização.")
    if strategy.style == "day" and days < 30 and not strategy.trade_bars:
        w.append("Para day trade, teste pelo menos 1 mês de dados.")
    if strategy.trade_bars and m.trades:
        w.append("Operações de 1 candle são muito sensíveis a custos: compare o custo médio de ida e volta com o "
                 "movimento médio do candle na análise estatística.")
    w.append(
        "Resultado passado não garante resultado futuro. A simulação não reproduz falhas de conexão, "
        "livro de ofertas raso nem mudanças de taxa. Ajustar parâmetros até o histórico ficar bonito "
        "costuma piorar o resultado real (sobreajuste)."
    )
    return w
