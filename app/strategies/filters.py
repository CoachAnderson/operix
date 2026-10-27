"""Filtros de entrada e stop/alvo pelo ATR, comuns a todas as estratégias.

Os filtros só barram ENTRADAS. Saídas (sinal contrário, stop, alvo, fim do pregão) nunca são bloqueadas.
O mesmo código roda no robô ao vivo e no backtest, sempre só com candles já fechados.
"""
from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.brokers.base import Candle
from app.strategies.base import Timeframe
from app.strategies.indicators import adx, atr, ema

TZ = ZoneInfo("America/Sao_Paulo")
TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
TF_LABEL = {"1m": "1 minuto", "5m": "5 minutos", "15m": "15 minutos", "30m": "30 minutos", "1h": "1 hora", "4h": "4 horas", "1d": "diário"}
Family = Literal["trend", "reversion"]

# Que tipo de mercado cada estratégia precisa.
STRATEGY_FAMILY: dict[str, Family] = {
    "ema_cross_day": "trend",
    "ema_cross_swing": "trend",
    "donchian_breakout": "trend",
    "rsi_reversion": "reversion",
    "reversao_ams": "reversion",
    "scalp_media": "reversion",
    "grade_spot": "reversion",
    "dca_spot": "reversion",
}


def _hhmm(v: str | None) -> str | None:
    if v in (None, ""):
        return None
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
        raise ValueError("Use o formato HH:MM, ex.: 09:30")
    return v


class BotFilters(BaseModel):
    """Configuração guardada em Bot.filters (JSON). Tudo desligado por padrão."""

    model_config = ConfigDict(extra="forbid")

    # 1) Tipo de mercado (ADX): tendência para estratégias de tendência; lateral para reversão
    regime: bool = False
    adx_period: int = Field(14, ge=5, le=50)
    adx_level: float = Field(20, ge=10, le=50)
    # 2) Confirmação no tempo gráfico maior: só compra acima da média, só vende abaixo
    htf: Timeframe | None = None
    htf_ema: int = Field(50, ge=5, le=200)
    # 3) Horário de entrada (horário de Brasília). Início > fim = janela que cruza a meia-noite.
    hours_start: str | None = None
    hours_end: str | None = None
    # 4) Volatilidade: ATR em % do preço
    atr_period: int = Field(14, ge=5, le=50)
    atr_min_pct: float | None = Field(None, gt=0, le=50)
    atr_max_pct: float | None = Field(None, gt=0, le=50)
    # 5) Stop e alvo em múltiplos do ATR (substituem os percentuais fixos)
    stop_atr: float | None = Field(None, ge=0.3, le=10)
    take_atr: float | None = Field(None, ge=0.3, le=30)

    @field_validator("hours_start", "hours_end")
    @classmethod
    def check_hours(cls, v: str | None) -> str | None:
        return _hhmm(v)

    @model_validator(mode="after")
    def check(self) -> BotFilters:
        if bool(self.hours_start) != bool(self.hours_end):
            raise ValueError("Informe o horário de início e o de fim")
        if self.hours_start and self.hours_start == self.hours_end:
            raise ValueError("O horário de início e o de fim não podem ser iguais")
        if self.atr_min_pct and self.atr_max_pct and self.atr_min_pct >= self.atr_max_pct:
            raise ValueError("A volatilidade mínima precisa ser menor que a máxima")
        return self

    # ------------------------------------------------------------ resumo
    @property
    def any_entry_filter(self) -> bool:
        return bool(self.regime or self.htf or self.hours_start or self.atr_min_pct or self.atr_max_pct)

    @property
    def atr_exits(self) -> bool:
        return bool(self.stop_atr or self.take_atr)

    @property
    def active(self) -> bool:
        return self.any_entry_filter or self.atr_exits

    def validate_for(self, timeframe: str) -> None:
        if self.htf and TF_MS[self.htf] <= TF_MS[timeframe]:
            raise ValueError(f"O tempo gráfico de confirmação precisa ser maior que o da estratégia ({timeframe})")
        if self.htf and TF_MS[self.htf] % TF_MS[timeframe]:
            raise ValueError(f"O tempo gráfico de confirmação precisa ser múltiplo de {timeframe}")

    def lookback(self) -> int:
        """Candles do tempo gráfico da estratégia que os filtros precisam."""
        n = 0
        if self.regime:
            n = max(n, self.adx_period * 6 + 2)
        if self.atr_min_pct or self.atr_max_pct or self.atr_exits:
            n = max(n, self.atr_period * 5 + 2)
        return n

    def htf_lookback(self) -> int:
        """Candles do tempo maior: a média fica correta a partir de `htf_ema` candles (semente = média simples)."""
        return self.htf_ema * 2 + 2 if self.htf else 0


def parse(raw: dict | None) -> BotFilters:
    return BotFilters(**(raw or {}))


# ------------------------------------------------------------ cálculo
def _num(v: float, digits: int = 1) -> str:
    return f"{v:.{digits}f}".replace(".", ",")


def resample(candles: list[Candle], htf: str, now_ms: int) -> list[Candle]:
    """Junta candles menores em candles do tempo maior, só com os blocos já FECHADOS em `now_ms`."""
    step = TF_MS[htf]
    out: list[Candle] = []
    bucket: list[Candle] = []
    key = None
    for c in candles:
        k = c.open_time // step
        if key is not None and k != key:
            out.append(_merge(bucket, key * step, step))
            bucket = []
        key = k
        bucket.append(c)
    if bucket and (key + 1) * step <= now_ms:
        out.append(_merge(bucket, key * step, step))
    return out


def _merge(group: list[Candle], open_time: int, step: int) -> Candle:
    return Candle(
        open_time=open_time,
        open=group[0].open,
        high=max(c.high for c in group),
        low=min(c.low for c in group),
        close=group[-1].close,
        volume=sum(c.volume for c in group),
        close_time=open_time + step - 1,
    )


def atr_value(candles: list[Candle], period: int) -> float:
    a = atr([c.high for c in candles], [c.low for c in candles], [c.close for c in candles], period)
    return a[-1] if a else math.nan


def entry_block(
    f: BotFilters,
    family: Family,
    direction: Literal["long", "short"],
    candles: list[Candle],
    htf_candles: list[Candle] | None,
    now_ms: int,
) -> str | None:
    """Motivo para NÃO entrar, ou None se todos os filtros liberarem. `candles` são só os já fechados."""
    if f.hours_start and f.hours_end:
        local = datetime.fromtimestamp(now_ms / 1000, UTC).astimezone(TZ).strftime("%H:%M")
        inside = f.hours_start <= local < f.hours_end if f.hours_start < f.hours_end else (local >= f.hours_start or local < f.hours_end)
        if not inside:
            return f"fora do horário de entrada ({f.hours_start} às {f.hours_end})"

    if f.regime:
        v = adx([c.high for c in candles], [c.low for c in candles], [c.close for c in candles], f.adx_period)[-1]
        if math.isnan(v):
            return "histórico insuficiente para o ADX"
        if family == "trend" and v < f.adx_level:
            return f"ADX {_num(v)} abaixo de {_num(f.adx_level, 0)}: mercado sem tendência"
        if family == "reversion" and v >= f.adx_level:
            return f"ADX {_num(v)} acima de {_num(f.adx_level, 0)}: tendência forte, reversão arriscada"

    if f.atr_min_pct or f.atr_max_pct:
        a = atr_value(candles, f.atr_period)
        if math.isnan(a):
            return "histórico insuficiente para o ATR"
        pct = a / candles[-1].close * 100
        if f.atr_min_pct and pct < f.atr_min_pct:
            return f"volatilidade baixa demais (ATR {_num(pct, 2)}% do preço)"
        if f.atr_max_pct and pct > f.atr_max_pct:
            return f"volatilidade alta demais (ATR {_num(pct, 2)}% do preço)"

    if f.htf:
        if not htf_candles or len(htf_candles) < f.htf_ema + 1:
            return f"histórico insuficiente no gráfico de {TF_LABEL[f.htf]}"
        closes = [c.close for c in htf_candles]
        m = ema(closes, f.htf_ema)[-1]
        if math.isnan(m):
            return f"histórico insuficiente no gráfico de {TF_LABEL[f.htf]}"
        if direction == "long" and closes[-1] <= m:
            return f"no gráfico de {TF_LABEL[f.htf]} o preço está abaixo da média de {f.htf_ema}: não compra contra a maré"
        if direction == "short" and closes[-1] >= m:
            return f"no gráfico de {TF_LABEL[f.htf]} o preço está acima da média de {f.htf_ema}: não vende contra a maré"
    return None


def atr_levels(f: BotFilters, direction: Literal["long", "short"], entry: float, atr_now: float) -> tuple[float | None, float | None]:
    """Preços de stop e alvo a partir do ATR no momento da entrada."""
    if math.isnan(atr_now) or atr_now <= 0:
        return None, None
    sign = 1 if direction == "long" else -1
    stop = entry - sign * f.stop_atr * atr_now if f.stop_atr else None
    take = entry + sign * f.take_atr * atr_now if f.take_atr else None
    return stop, take


def reason_kind(msg: str) -> str:
    """Agrupa os motivos para o resumo do backtest."""
    if msg.startswith("fora do horário"):
        return "Fora do horário"
    if "sem tendência" in msg:
        return "Mercado sem tendência (ADX)"
    if "reversão arriscada" in msg:
        return "Tendência forte demais para reversão (ADX)"
    if "volatilidade baixa" in msg:
        return "Volatilidade baixa"
    if "volatilidade alta" in msg:
        return "Volatilidade alta"
    if "contra a maré" in msg:
        return "Contra o tempo gráfico maior"
    return "Histórico insuficiente"
