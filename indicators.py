"""Indicadores técnicos em Python puro (sem pandas) para manter o worker leve e testável."""
from __future__ import annotations

import math


def sma(values: list[float], period: int) -> list[float]:
    out = [math.nan] * len(values)
    if period <= 0 or len(values) < period:
        return out
    acc = sum(values[:period])
    out[period - 1] = acc / period
    for i in range(period, len(values)):
        acc += values[i] - values[i - period]
        out[i] = acc / period
    return out


def ema(values: list[float], period: int) -> list[float]:
    out = [math.nan] * len(values)
    if period <= 0 or len(values) < period:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(values: list[float], period: int = 14) -> list[float]:
    """RSI de Wilder."""
    out = [math.nan] * len(values)
    if len(values) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    avg_g, avg_l = gains / period, losses / period
    out[period] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(period + 1, len(values)):
        d = values[i] - values[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0)) / period
        out[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out


def highest(values: list[float], period: int, end: int) -> float:
    """Máxima dos `period` valores anteriores a `end` (exclusivo)."""
    window = values[max(0, end - period) : end]
    return max(window) if window else math.nan


def lowest(values: list[float], period: int, end: int) -> float:
    window = values[max(0, end - period) : end]
    return min(window) if window else math.nan


def crossed_above(a: list[float], b: list[float]) -> bool:
    return len(a) >= 2 and a[-2] <= b[-2] and a[-1] > b[-1]


def crossed_below(a: list[float], b: list[float]) -> bool:
    return len(a) >= 2 and a[-2] >= b[-2] and a[-1] < b[-1]
