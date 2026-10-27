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


def true_range(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    out = [math.nan] * len(closes)
    for i in range(1, len(closes)):
        pc = closes[i - 1]
        out[i] = max(highs[i] - lows[i], abs(highs[i] - pc), abs(lows[i] - pc))
    return out


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    """ATR de Wilder: tamanho médio do movimento de cada candle, incluindo saltos de abertura."""
    tr = true_range(highs, lows, closes)
    out = [math.nan] * len(closes)
    if len(closes) <= period:
        return out
    prev = sum(tr[1 : period + 1]) / period
    out[period] = prev
    for i in range(period + 1, len(closes)):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    """ADX de Wilder (0 a 100): força da tendência, sem dizer a direção. Acima de ~20-25, há tendência."""
    n = len(closes)
    out = [math.nan] * n
    if n < period * 2 + 1:
        return out
    tr = true_range(highs, lows, closes)
    pdm = [0.0] * n
    mdm = [0.0] * n
    for i in range(1, n):
        up, down = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        pdm[i] = up if up > down and up > 0 else 0.0
        mdm[i] = down if down > up and down > 0 else 0.0
    s_tr = sum(tr[1 : period + 1])
    s_p = sum(pdm[1 : period + 1])
    s_m = sum(mdm[1 : period + 1])
    dx: list[float] = []
    for i in range(period, n):
        if i > period:
            s_tr = s_tr - s_tr / period + tr[i]
            s_p = s_p - s_p / period + pdm[i]
            s_m = s_m - s_m / period + mdm[i]
        if s_tr <= 0:
            dx.append(0.0)
            continue
        pdi, mdi = 100 * s_p / s_tr, 100 * s_m / s_tr
        dx.append(0.0 if pdi + mdi == 0 else 100 * abs(pdi - mdi) / (pdi + mdi))
        if len(dx) == period:
            out[i] = sum(dx) / period
        elif len(dx) > period:
            out[i] = (out[i - 1] * (period - 1) + dx[-1]) / period
    return out


def bollinger(values: list[float], period: int = 20, num_std: float = 2.0) -> tuple[float, float, float]:
    """Bandas de Bollinger do ÚLTIMO valor: (média, banda superior, banda inferior). NaN se faltar histórico."""
    if period <= 1 or len(values) < period:
        return math.nan, math.nan, math.nan
    window = values[-period:]
    mid = sum(window) / period
    sd = math.sqrt(sum((v - mid) ** 2 for v in window) / period)
    return mid, mid + num_std * sd, mid - num_std * sd
