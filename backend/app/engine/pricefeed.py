"""Preço em tempo real da Binance (stream `bookTicker` por WebSocket), para stop e alvo sem esperar ciclo.

Uma conexão por ambiente (produção/testnet). As assinaturas mudam sem reconectar (SUBSCRIBE/UNSUBSCRIBE).
A Binance encerra conexões a cada 24 h e pede pong aos pings; a biblioteca `websockets` responde os pings e
o laço reconecta com espera crescente. Sem conexão, o motor cai para a consulta periódica de preço.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import websockets

log = logging.getLogger(__name__)

PriceCallback = Callable[[str, str, float, float], None]  # (feed, símbolo, bid, ask)


@dataclass
class Quote:
    bid: float
    ask: float
    at: float  # time.time() do recebimento

    def fresh(self, max_age: float = 3.0) -> bool:
        return time.time() - self.at <= max_age


class BinanceFeed:
    def __init__(self, name: str, url: str, on_price: PriceCallback | None = None):
        self.name = name  # "live" | "testnet"
        self.url = url
        self.on_price = on_price
        self.quotes: dict[str, Quote] = {}
        self._wanted: set[str] = set()
        self._subscribed: set[str] = set()
        self._ws = None
        self._ids = 0
        self.connected = asyncio.Event()

    # ------------------------------------------------------------ assinaturas
    def set_symbols(self, symbols: set[str]) -> None:
        self._wanted = {s.upper() for s in symbols}
        if self._ws is not None:
            asyncio.get_running_loop().create_task(self._sync())

    async def _send(self, method: str, symbols: set[str]) -> None:
        if not symbols or self._ws is None:
            return
        self._ids += 1
        await self._ws.send(json.dumps({"method": method, "params": [f"{s.lower()}@bookTicker" for s in sorted(symbols)], "id": self._ids}))

    async def _sync(self) -> None:
        add, drop = self._wanted - self._subscribed, self._subscribed - self._wanted
        try:
            await self._send("SUBSCRIBE", add)
            await self._send("UNSUBSCRIBE", drop)
        except Exception:  # noqa: BLE001 - a reconexão refaz tudo
            return
        self._subscribed = (self._subscribed | add) - drop
        for s in drop:
            self.quotes.pop(s, None)

    def quote(self, symbol: str, max_age: float = 3.0) -> Quote | None:
        q = self.quotes.get(symbol.upper())
        return q if q and q.fresh(max_age) else None

    # ------------------------------------------------------------ laço
    def _handle(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if "s" not in msg or "b" not in msg:  # respostas de SUBSCRIBE etc.
            return
        symbol, bid, ask = msg["s"], float(msg["b"]), float(msg["a"])
        self.quotes[symbol] = Quote(bid, ask, time.time())
        if self.on_price:
            try:
                self.on_price(self.name, symbol, bid, ask)
            except Exception:  # noqa: BLE001
                log.exception("Falha ao processar preço de %s", symbol)

    async def run(self, stop: asyncio.Event) -> None:
        backoff = 1.0
        while not stop.is_set():
            try:
                async with websockets.connect(self.url, ping_interval=None, open_timeout=10, max_queue=4096) as ws:
                    self._ws, self._subscribed = ws, set()
                    self.connected.set()
                    await self._sync()
                    backoff = 1.0
                    log.info("Preço em tempo real conectado (%s)", self.name)
                    while not stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except TimeoutError:
                            await ws.ping()
                            continue
                        self._handle(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - rede caiu, Binance fechou etc.
                log.warning("Preço em tempo real (%s) desconectado: %s. Nova tentativa em %.0fs", self.name, exc, backoff)
            finally:
                self._ws = None
                self.connected.clear()
            if stop.is_set():
                break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            backoff = min(backoff * 2, 30)
