"""Estratégias incluídas. São exemplos educativos e simples — não há promessa de rentabilidade.
Todas funcionam só comprado (cripto à vista) ou comprado e vendido (forex), conforme `allow_short`.
Para adicionar uma nova: crie a classe, defina Params e decide(), e registre em STRATEGIES."""
from __future__ import annotations

import math

from pydantic import Field, model_validator

from app.services.brokers.base import Candle
from app.strategies.base import Decision, Strategy, StrategyParams, Target, Timeframe
from app.strategies.indicators import crossed_above, crossed_below, ema, highest, lowest, rsi


# ---------------------------------------------------------------- Cruzamento de médias
class EmaCrossParams(StrategyParams):
    fast: int = Field(9, ge=2, le=100)
    slow: int = Field(21, ge=3, le=400)

    @model_validator(mode="after")
    def check(self) -> EmaCrossParams:
        if self.fast >= self.slow:
            raise ValueError("A média rápida deve ser menor que a lenta")
        return self


class _EmaCross(Strategy):
    Params = EmaCrossParams

    def required_candles(self, params: EmaCrossParams) -> int:  # type: ignore[override]
        return params.slow * 3 + 2

    def decide(self, candles: list[Candle], position: Target, params: EmaCrossParams, allow_short: bool = False) -> Decision:  # type: ignore[override]
        closes = [c.close for c in candles]
        f, s = ema(closes, params.fast), ema(closes, params.slow)
        if math.isnan(s[-1]) or math.isnan(s[-2]):
            return Decision.hold("Histórico insuficiente")
        if crossed_above(f, s) and position != "long":
            return Decision("long", f"EMA{params.fast} cruzou acima da EMA{params.slow}")
        if crossed_below(f, s) and position != "short":
            target: Target = "short" if allow_short else "flat"
            if target == "flat" and position == "flat":
                return Decision.hold()
            return Decision(target, f"EMA{params.fast} cruzou abaixo da EMA{params.slow}")
        return Decision.hold()


class EmaCrossDay(_EmaCross):
    code = "ema_cross_day"
    name = "Cruzamento de médias (intradiário)"
    style = "day"
    description = "Entra a favor do cruzamento da média rápida sobre a lenta em tempo gráfico curto; sai no cruzamento contrário ou no fim do prazo."
    default_max_hold_minutes = 480

    class Params(EmaCrossParams):
        timeframe: Timeframe = "5m"


class EmaCrossSwing(_EmaCross):
    code = "ema_cross_swing"
    name = "Cruzamento de médias (swing)"
    style = "swing"
    description = "Segue tendência em gráfico de 4 horas com médias 20/50."

    class Params(EmaCrossParams):
        timeframe: Timeframe = "4h"
        fast: int = Field(20, ge=2, le=100)
        slow: int = Field(50, ge=3, le=400)


# ---------------------------------------------------------------- Reversão por RSI
class RsiReversion(Strategy):
    code = "rsi_reversion"
    name = "Reversão por RSI"
    style = "day"
    description = "Compra em sobrevenda a favor da tendência maior e vende em sobrecompra contra ela (se operar vendido). Sai quando o RSI normaliza."
    default_max_hold_minutes = 720

    class Params(StrategyParams):
        timeframe: Timeframe = "15m"
        period: int = Field(14, ge=2, le=50)
        oversold: float = Field(30, ge=5, le=50)
        exit_level: float = Field(55, ge=40, le=95)
        trend_ema: int = Field(200, ge=0, le=400, description="0 desliga o filtro de tendência")

    def required_candles(self, params) -> int:  # type: ignore[override]
        return max(params.period * 5, params.trend_ema + 2, 50)

    def decide(self, candles: list[Candle], position: Target, params, allow_short: bool = False) -> Decision:  # type: ignore[override]
        closes = [c.close for c in candles]
        r = rsi(closes, params.period)[-1]
        if math.isnan(r):
            return Decision.hold("Histórico insuficiente")
        overbought, short_exit = 100 - params.oversold, 100 - params.exit_level

        if position == "long":
            return Decision("flat", f"RSI {r:.1f} acima de {params.exit_level:g}") if r > params.exit_level else Decision.hold()
        if position == "short":
            return Decision("flat", f"RSI {r:.1f} abaixo de {short_exit:g}") if r < short_exit else Decision.hold()

        trend = ema(closes, params.trend_ema)[-1] if params.trend_ema else math.nan
        up = not params.trend_ema or (not math.isnan(trend) and closes[-1] > trend)
        down = not params.trend_ema or (not math.isnan(trend) and closes[-1] < trend)
        if r < params.oversold and up:
            return Decision("long", f"RSI {r:.1f} abaixo de {params.oversold:g}")
        if allow_short and r > overbought and down:
            return Decision("short", f"RSI {r:.1f} acima de {overbought:g}")
        return Decision.hold()


# ---------------------------------------------------------------- Rompimento (Donchian)
class DonchianBreakout(Strategy):
    code = "donchian_breakout"
    name = "Rompimento de canal"
    style = "swing"
    description = "Compra no fechamento acima da máxima dos últimos N períodos e vende abaixo da mínima (se operar vendido). Sai no rompimento contrário de M períodos."

    class Params(StrategyParams):
        timeframe: Timeframe = "1d"
        entry_period: int = Field(20, ge=5, le=200)
        exit_period: int = Field(10, ge=3, le=200)

    def required_candles(self, params) -> int:  # type: ignore[override]
        return max(params.entry_period, params.exit_period) + 5

    def decide(self, candles: list[Candle], position: Target, params, allow_short: bool = False) -> Decision:  # type: ignore[override]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        close = candles[-1].close
        n = len(candles) - 1
        if n < max(params.entry_period, params.exit_period):
            return Decision.hold("Histórico insuficiente")
        if position != "long" and close > highest(highs, params.entry_period, n):
            return Decision("long", f"Fechou acima da máxima de {params.entry_period} períodos")
        if allow_short and position != "short" and close < lowest(lows, params.entry_period, n):
            return Decision("short", f"Fechou abaixo da mínima de {params.entry_period} períodos")
        if position == "long" and close < lowest(lows, params.exit_period, n):
            return Decision("flat", f"Fechou abaixo da mínima de {params.exit_period} períodos")
        if position == "short" and close > highest(highs, params.exit_period, n):
            return Decision("flat", f"Fechou acima da máxima de {params.exit_period} períodos")
        return Decision.hold()


STRATEGIES: dict[str, Strategy] = {s.code: s() for s in (EmaCrossDay, EmaCrossSwing, RsiReversion, DonchianBreakout)}


def get_strategy(code: str) -> Strategy:
    try:
        return STRATEGIES[code]
    except KeyError:
        raise ValueError(f"Estratégia desconhecida: {code}") from None
