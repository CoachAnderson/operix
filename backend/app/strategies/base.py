from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.brokers.base import Candle

Timeframe = Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
Target = Literal["long", "short", "flat"]


@dataclass(frozen=True)
class Decision:
    """O que a estratégia quer ter DEPOIS deste candle.

    target = "long"  -> estar comprado
    target = "short" -> estar vendido (só se o robô permitir operar vendido)
    target = "flat"  -> estar fora do mercado
    target = None    -> manter o que está
    O motor compara com a posição atual e decide se fecha, abre ou inverte.
    """

    target: Target | None
    reason: str = ""

    @classmethod
    def hold(cls, reason: str = "") -> Decision:
        return cls(None, reason)


class StrategyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timeframe: Timeframe
    max_hold_minutes: int | None = Field(None, ge=1, le=100_000, description="Encerra a posição após esse tempo")


class Strategy:
    code: ClassVar[str]
    name: ClassVar[str]
    style: ClassVar[Literal["day", "swing"]]
    description: ClassVar[str]
    Params: ClassVar[type[StrategyParams]]
    # Day trade: tempo máximo com a posição aberta (minutos). Swing: None.
    default_max_hold_minutes: ClassVar[int | None] = None

    def parse_params(self, raw: dict[str, Any]) -> StrategyParams:
        return self.Params(**raw)

    def max_hold_minutes(self, params: StrategyParams) -> int | None:
        return params.max_hold_minutes or self.default_max_hold_minutes

    def required_candles(self, params: StrategyParams) -> int:
        return 200

    def decide(self, candles: list[Candle], position: Target, params: StrategyParams, allow_short: bool = False) -> Decision:
        """`position` é a posição atual ("long", "short" ou "flat")."""
        raise NotImplementedError

    @staticmethod
    def closed_only(candles: list[Candle], now_ms: int | None = None) -> list[Candle]:
        """Descarta o candle em formação para evitar sinais que 'piscam' (repaint)."""
        now_ms = now_ms or int(time.time() * 1000)
        if candles and candles[-1].close_time >= now_ms:
            return candles[:-1]
        return candles
