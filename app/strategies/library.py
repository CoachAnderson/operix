"""Estratégias incluídas. São exemplos educativos e simples — não há promessa de rentabilidade.
Todas funcionam só comprado (cripto à vista) ou comprado e vendido (forex), conforme `allow_short`.
Para adicionar uma nova: crie a classe, defina Params e decide(), e registre em STRATEGIES."""
from __future__ import annotations

import math

from typing import Literal

from pydantic import Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from app.services.brokers.base import Candle
from app.strategies.base import Decision, Strategy, StrategyParams, Target, Timeframe
from app.strategies.indicators import bollinger, crossed_above, crossed_below, ema, highest, lowest, rsi


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


# ---------------------------------------------------------------- Scalp: reversão à média
class ScalpMedia(Strategy):
    """Scalp de reversão à média: entra quando o preço fecha fora da Banda de Bollinger com o RSI curto esticado,
    a favor da tendência maior, e sai quando o preço volta à média. Alvo curto (alto acerto) e stop pela
    configuração do robô (percentual ou ATR): o acerto alto só vale se o ganho médio pagar as perdas."""

    code = "scalp_media"
    name = "Scalp: volta à média"
    style = "day"
    description = (
        "Compra quando o preço fecha abaixo da Banda de Bollinger com o RSI curto em sobrevenda, a favor da tendência, "
        "e sai quando ele volta à média das bandas. Alvo curto e muitas operações; use sempre stop."
    )
    default_max_hold_minutes = 120
    suggested_max_trades_per_day = 60
    notes = (
        "Estratégia de alvo curto: tende a acertar muito, mas cada perda costuma ser maior que cada ganho. Olhe no backtest o 'acerto necessário para empatar'.",
        "Use sempre stop (percentual ou pelo ATR, em Filtros). Sem stop, uma tendência forte contra a entrada pode gerar uma perda grande.",
        "Na Binance à vista só faz as compras; as vendas exigem forex ou B3 com 'operar vendido'.",
        "Em cripto, a taxa de 0,1% por lado pesa muito em alvos curtos: teste com os custos reais.",
    )

    class Params(StrategyParams):
        timeframe: Timeframe = "5m"
        bb_period: int = Field(20, ge=5, le=100, description="Períodos da Banda de Bollinger")
        bb_std: float = Field(2.0, ge=1.0, le=4.0, description="Desvios-padrão da banda")
        rsi_period: int = Field(7, ge=2, le=30)
        rsi_level: float = Field(25, ge=5, le=45, description="RSI abaixo deste nível para comprar (acima de 100 menos ele para vender)")
        trend_ema: int = Field(200, ge=0, le=400, description="0 desliga o filtro de tendência")

    def required_candles(self, params) -> int:  # type: ignore[override]
        return max(params.bb_period + 2, params.rsi_period * 5, params.trend_ema + 2, 50)

    def decide(self, candles: list[Candle], position: Target, params, allow_short: bool = False) -> Decision:  # type: ignore[override]
        closes = [c.close for c in candles]
        mid, upper, lower = bollinger(closes, params.bb_period, params.bb_std)
        r = rsi(closes, params.rsi_period)[-1]
        if math.isnan(mid) or math.isnan(r):
            return Decision.hold("Histórico insuficiente")
        close = closes[-1]
        if position == "long":
            return Decision("flat", f"Voltou à média ({mid:.6g})") if close >= mid else Decision.hold()
        if position == "short":
            return Decision("flat", f"Voltou à média ({mid:.6g})") if close <= mid else Decision.hold()
        trend = ema(closes, params.trend_ema)[-1] if params.trend_ema else math.nan
        up = not params.trend_ema or (not math.isnan(trend) and close > trend)
        down = not params.trend_ema or (not math.isnan(trend) and close < trend)
        if close < lower and r < params.rsi_level and up:
            return Decision("long", f"Fechou abaixo da banda ({lower:.6g}) com RSI {r:.0f}", "compra")
        if allow_short and close > upper and r > 100 - params.rsi_level and down:
            return Decision("short", f"Fechou acima da banda ({upper:.6g}) com RSI {r:.0f}", "venda")
        return Decision.hold()


# ---------------------------------------------------------------- Reversão AMS (1 minuto)
AMS_WINDOW = 5


class ReversaoAMS(Strategy):
    """Conta altas e baixas nos 5 últimos candles FECHADOS de 1 minuto e entra contra a maioria na abertura do
    6º candle; a operação dura exatamente esse candle (sai no fechamento). Doji (fechamento = abertura) não conta."""

    code = "reversao_ams"
    name = "Reversão AMS (1 minuto)"
    style = "day"
    description = (
        "Olha os 5 últimos candles fechados de 1 minuto. Com 3, 4 ou 5 de alta, vende; com 3, 4 ou 5 de baixa, compra. "
        "Entra na abertura do candle seguinte e sai no fechamento dele: cada operação dura 1 minuto."
    )
    default_max_hold_minutes = 3  # rede de segurança: a saída normal acontece no fechamento do candle
    trade_bars = 1
    suggested_max_trades_per_day = 120
    notes = (
        "Cada operação dura exatamente 1 candle de 1 minuto; o robô decide cerca de 1 segundo após cada fechamento.",
        "Na Binance à vista não há venda a descoberto: o robô só faz as compras (CALL). Os sinais de venda (PUT) só viram operação em forex e B3, com 'operar vendido' ligado.",
        "Em 1 minuto o preço anda pouco. Taxa e escorregamento de ida e volta podem ser maiores que o movimento médio do candle: confira no backtest o custo médio contra o movimento médio antes de ligar.",
        "Cada operação conta 2 no limite diário (entrada e saída). O limite sugerido de 120 equivale a 60 operações por dia.",
    )

    class Params(StrategyParams):
        timeframe: Literal["1m"] = "1m"
        min_majority: int = Field(3, ge=3, le=5, description="Candles na mesma direção, entre os 5, para entrar")
        max_hold_minutes: SkipJsonSchema[int | None] = None  # duração fixa: não se aplica

    def required_candles(self, params) -> int:  # type: ignore[override]
        return AMS_WINDOW

    def decide(self, candles: list[Candle], position: Target, params, allow_short: bool = False) -> Decision:  # type: ignore[override]
        if len(candles) < AMS_WINDOW:
            return Decision("flat", "Histórico insuficiente")
        last = candles[-AMS_WINDOW:]
        step = 60_000
        if last[-1].open_time - last[0].open_time != (AMS_WINDOW - 1) * step:
            return Decision("flat", "Falta candle de 1 minuto na sequência dos 5 analisados")
        up = sum(1 for c in last if c.close > c.open)
        down = sum(1 for c in last if c.close < c.open)
        seq = " ".join("A" if c.close > c.open else "B" if c.close < c.open else "D" for c in last)
        if up >= params.min_majority:
            tag = f"{up}x{AMS_WINDOW - up}"
            if not allow_short:
                return Decision("flat", f"Reversão AMS: {up} de 5 em alta ({seq}) pede venda, mas o robô não opera vendido", tag)
            return Decision("short", f"Reversão AMS {tag}: {up} de 5 candles em alta ({seq}) → venda por 1 candle", tag)
        if down >= params.min_majority:
            tag = f"{down}x{AMS_WINDOW - down}"
            return Decision("long", f"Reversão AMS {tag}: {down} de 5 candles em baixa ({seq}) → compra por 1 candle", tag)
        return Decision("flat", f"Reversão AMS: sem maioria de {params.min_majority} em 5 ({seq})")


from app.strategies.ladder import DcaSpot, GridSpot  # noqa: E402

STRATEGIES: dict[str, Strategy] = {
    s.code: s() for s in (EmaCrossDay, EmaCrossSwing, RsiReversion, DonchianBreakout, ScalpMedia, ReversaoAMS, GridSpot, DcaSpot)
}


def get_strategy(code: str) -> Strategy:
    try:
        return STRATEGIES[code]
    except KeyError:
        raise ValueError(f"Estratégia desconhecida: {code}") from None
