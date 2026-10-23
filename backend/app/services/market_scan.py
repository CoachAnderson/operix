"""Pares da Binance à vista disponíveis agora: status de negociação, preço, variação, volume e movimento da última hora.

Só dados públicos de mercado (sem chave de API). Tudo fica em cache por pouco tempo e é compartilhado entre os
clientes, para não pesar no limite de requisições da Binance:
- exchangeInfo (lista de pares e status): 10 minutos;
- ticker de 24 h de todos os pares (peso 80): 30 segundos;
- janela de 1 hora dos 100 pares com mais volume de cada moeda de cotação (peso 200): 60 segundos.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.brokers.base import BrokerError

STATUS_LABEL = {"TRADING": "Negociando", "HALT": "Suspenso", "BREAK": "Pausado", "END_OF_DAY": "Encerrado"}
HOUR_TOP = 100  # máximo de pares por requisição da janela móvel


@dataclass
class _Entry:
    at: float
    value: Any


_cache: dict[str, _Entry] = {}
_locks: dict[str, asyncio.Lock] = {}


async def _cached(key: str, ttl: float, fetch) -> Any:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit.at < ttl:
        return hit.value
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit.at < ttl:
            return hit.value
        try:
            value = await fetch()
        except BrokerError:
            if hit:  # Binance fora do ar: devolve o último dado conhecido em vez de erro
                return hit.value
            raise
        _cache[key] = _Entry(time.monotonic(), value)
        return value


def _client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=get_settings().binance_market_data_base, timeout=15, transport=transport)


async def _get(path: str, params: dict[str, Any], transport=None) -> Any:
    async with _client(transport) as http:
        try:
            resp = await http.get(path, params=params)
        except httpx.HTTPError as exc:
            raise BrokerError(f"Binance indisponível: {exc}", retryable=True) from exc
    if resp.status_code >= 400:
        raise BrokerError(f"Binance respondeu {resp.status_code}", retryable=resp.status_code >= 500 or resp.status_code == 429)
    return resp.json()


def _f(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pct(a: float | None, b: float | None) -> float | None:
    return (a - b) / b * 100 if a is not None and b else None


async def _symbols(transport=None) -> dict[str, dict]:
    async def fetch():
        data = await _get("/api/v3/exchangeInfo", {"permissions": "SPOT", "showPermissionSets": "false"}, transport)
        out = {}
        for s in data.get("symbols", []):
            if not s.get("isSpotTradingAllowed", True):
                continue
            out[s["symbol"]] = {
                "base": s.get("baseAsset", ""),
                "quote": s.get("quoteAsset", ""),
                "status": s.get("status", ""),
                "market_order": "MARKET" in (s.get("orderTypes") or []),
            }
        return out

    return await _cached("symbols", 600, fetch)


async def _tickers_24h(transport=None) -> dict[str, dict]:
    async def fetch():
        data = await _get("/api/v3/ticker/24hr", {"type": "MINI"}, transport)
        return {t["symbol"]: t for t in data if "symbol" in t}

    return await _cached("t24", 30, fetch)


async def _tickers_1h(symbols: list[str], transport=None) -> dict[str, dict]:
    if not symbols:
        return {}
    key = "t1h:" + ",".join(symbols)

    async def fetch():
        data = await _get("/api/v3/ticker", {"windowSize": "1h", "type": "MINI", "symbols": json.dumps(symbols, separators=(",", ":"))}, transport)
        return {t["symbol"]: t for t in data if "symbol" in t}

    return await _cached(key, 60, fetch)


async def scan(quote: str, transport=None) -> dict:
    """Pares com a moeda de cotação `quote` (ex.: USDT, BRL), já ordenados por volume em 24 h."""
    symbols, t24 = await asyncio.gather(_symbols(transport), _tickers_24h(transport))
    quotes: dict[str, int] = {}
    for info in symbols.values():
        if info["status"] == "TRADING":
            quotes[info["quote"]] = quotes.get(info["quote"], 0) + 1

    rows = []
    for sym, info in symbols.items():
        if info["quote"] != quote:
            continue
        t = t24.get(sym, {})
        last, open_, high, low = _f(t.get("lastPrice")), _f(t.get("openPrice")), _f(t.get("highPrice")), _f(t.get("lowPrice"))
        change = _f(t.get("priceChangePercent"))
        rows.append({
            "symbol": sym,
            "base": info["base"],
            "status": info["status"],
            "status_label": STATUS_LABEL.get(info["status"], info["status"].title()),
            "tradable": info["status"] == "TRADING" and info["market_order"],
            "price": last,
            "change_24h_pct": change if change is not None else _pct(last, open_),
            "range_24h_pct": _pct(high, low) if low else None,
            "quote_volume_24h": _f(t.get("quoteVolume")) or 0.0,
            "trades_24h": int(t.get("count") or 0),
            "change_1h_pct": None,
            "range_1h_pct": None,
        })
    rows.sort(key=lambda r: r["quote_volume_24h"], reverse=True)

    # Última hora: só os pares com mais volume (a janela móvel aceita até 100 por requisição).
    top = [r["symbol"] for r in rows if r["status"] == "TRADING"][:HOUR_TOP]
    hour_ok = True
    try:
        t1h = await _tickers_1h(top, transport)
    except BrokerError:
        t1h, hour_ok = {}, False
    for r in rows:
        h = t1h.get(r["symbol"])
        if h:
            last, open_ = _f(h.get("lastPrice")), _f(h.get("openPrice"))
            high, low = _f(h.get("highPrice")), _f(h.get("lowPrice"))
            change = _f(h.get("priceChangePercent"))
            r["change_1h_pct"] = change if change is not None else _pct(last, open_)
            r["range_1h_pct"] = _pct(high, low) if low else None

    return {
        "quote": quote,
        "quotes": [{"quote": q, "count": n} for q, n in sorted(quotes.items(), key=lambda kv: -kv[1])],
        "rows": rows,
        "hour_top": len(top) if hour_ok else 0,
        "updated_at": int(time.time() * 1000),
    }


def clear_cache() -> None:
    _cache.clear()
