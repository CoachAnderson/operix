"""Cliente da API oficial REST da Binance Spot (live e testnet), sem SDK de terceiros.

Documentação: https://developers.binance.com/docs/binance-spot-api-docs
Autenticação: cabeçalho X-MBX-APIKEY + assinatura HMAC-SHA256 da query string (incluindo timestamp).
"""
from __future__ import annotations

import hashlib
import hmac
import time
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings
from app.models import PosSide, Side
from app.services.brokers.base import BrokerError, Candle, Fill, OrderUnknownError, SymbolRules

_RULES_CACHE: dict[tuple[str, str], tuple[float, SymbolRules]] = {}
_RULES_TTL = 3600
_KLINES_CACHE: dict[tuple[str, str, str, int], tuple[float, list[Candle]]] = {}
_KLINES_TTL = 10


class BinanceClient:
    supports_short = False  # Spot: só compra e venda do que se tem

    def __init__(
        self,
        venue: str,
        api_key: str | None = None,
        api_secret: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        s = get_settings()
        if venue not in ("live", "testnet"):
            raise ValueError("venue deve ser live ou testnet")
        self.venue = venue
        self._key = api_key
        self._secret = api_secret
        base = s.binance_live_base if venue == "live" else s.binance_testnet_base
        market = s.binance_market_data_base if venue == "live" else s.binance_testnet_base
        self._http = httpx.AsyncClient(base_url=base, timeout=10, transport=transport)
        self._market = httpx.AsyncClient(base_url=market, timeout=10, transport=transport)
        self._time_offset_ms = 0

    async def close(self) -> None:
        await self._http.aclose()
        await self._market.aclose()

    # ---------------- infraestrutura ----------------
    @staticmethod
    def _raise_for(resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        try:
            data = resp.json()
            code, msg = data.get("code"), data.get("msg", resp.text)
        except ValueError:
            code, msg = None, resp.text
        # 429/418: limite de requisições; 5xx: instabilidade -> tentar no próximo ciclo
        retryable = resp.status_code in (418, 429) or resp.status_code >= 500
        raise BrokerError(f"Binance {resp.status_code} [{code}]: {msg}", retryable=retryable, code=code)

    def _sign(self, params: dict[str, Any]) -> str:
        if not (self._key and self._secret):
            raise BrokerError("Credenciais da Binance ausentes")
        params = {**params, "timestamp": int(time.time() * 1000) + self._time_offset_ms, "recvWindow": 5000}
        query = urlencode(params)
        signature = hmac.new(self._secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        return f"{query}&signature={signature}"

    async def _signed(self, method: str, path: str, params: dict[str, Any]) -> Any:
        query = self._sign(params)
        try:
            resp = await self._http.request(method, f"{path}?{query}", headers={"X-MBX-APIKEY": self._key or ""})
        except httpx.TimeoutException as exc:
            if method == "POST":
                raise OrderUnknownError("Timeout ao enviar ordem", retryable=True) from exc
            raise BrokerError("Timeout na Binance", retryable=True) from exc
        except httpx.TransportError as exc:
            raise BrokerError(f"Erro de rede: {exc}", retryable=True) from exc
        if resp.status_code >= 500 and method == "POST":
            # Binance documenta que 5xx não significa falha: a ordem pode ter sido aceita.
            raise OrderUnknownError(f"Binance {resp.status_code} ao enviar ordem", retryable=True)
        self._raise_for(resp)
        return resp.json()

    async def _public(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            resp = await self._market.get(path, params=params)
        except httpx.HTTPError as exc:
            raise BrokerError(f"Erro ao consultar dados de mercado: {exc}", retryable=True) from exc
        self._raise_for(resp)
        return resp.json()

    async def sync_time(self) -> None:
        data = await self._public("/api/v3/time")
        self._time_offset_ms = int(data["serverTime"]) - int(time.time() * 1000)

    # ---------------- dados de mercado ----------------
    async def get_price(self, symbol: str) -> Decimal:
        data = await self._public("/api/v3/ticker/price", {"symbol": symbol})
        return Decimal(data["price"])

    async def get_klines(self, symbol: str, interval: str, limit: int = 200) -> list[Candle]:
        # Cache curto: vários robôs no mesmo par/tempo gráfico compartilham a consulta (economiza peso da API).
        key = (str(self._market.base_url), symbol, interval, limit)
        cached = _KLINES_CACHE.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        rows = await self._public("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": min(limit, 1000)})
        candles = [
            Candle(
                open_time=int(r[0]),
                open=float(r[1]),
                high=float(r[2]),
                low=float(r[3]),
                close=float(r[4]),
                volume=float(r[5]),
                close_time=int(r[6]),
            )
            for r in rows
        ]
        _KLINES_CACHE[key] = (time.monotonic() + _KLINES_TTL, candles)
        return candles

    async def get_klines_range(self, symbol: str, interval: str, start_ms: int, end_ms: int, max_candles: int) -> list[Candle]:
        """Histórico paginado (1.000 candles por chamada) entre start_ms e end_ms."""
        out: list[Candle] = []
        cursor = start_ms
        while cursor < end_ms and len(out) < max_candles:
            rows = await self._public(
                "/api/v3/klines",
                {"symbol": symbol, "interval": interval, "startTime": cursor, "endTime": end_ms, "limit": 1000},
            )
            if not rows:
                break
            out.extend(
                Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]), int(r[6])) for r in rows
            )
            cursor = int(rows[-1][0]) + 1
            if len(rows) < 1000:
                break
        now_ms = int(time.time() * 1000)
        return [c for c in out if c.close_time < now_ms][:max_candles]  # só candles já fechados

    async def get_rules(self, symbol: str) -> SymbolRules:
        key = (self.venue, symbol)
        cached = _RULES_CACHE.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        data = await self._public("/api/v3/exchangeInfo", {"symbol": symbol})
        if not data.get("symbols"):
            raise BrokerError(f"Par {symbol} não encontrado")
        info = data["symbols"][0]
        filters = {f["filterType"]: f for f in info["filters"]}
        lot = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE") or {}
        if Decimal(lot.get("stepSize", "0")) == 0:  # MARKET_LOT_SIZE pode vir zerado
            lot = filters.get("LOT_SIZE", {})
        notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
        rules = SymbolRules(
            symbol=symbol,
            base_asset=info["baseAsset"],
            quote_asset=info["quoteAsset"],
            step_size=Decimal(lot.get("stepSize", "0.00000001")),
            min_qty=Decimal(lot.get("minQty", "0")),
            max_qty=Decimal(lot.get("maxQty", "9999999999")),
            min_notional=Decimal(notional.get("minNotional", "0")),
            quote_precision=int(info.get("quoteAssetPrecision", info.get("quotePrecision", 8))),
            trading=info.get("status") == "TRADING",
        )
        _RULES_CACHE[key] = (time.monotonic() + _RULES_TTL, rules)
        return rules

    # ---------------- conta ----------------
    async def account(self) -> dict[str, Any]:
        return await self._signed("GET", "/api/v3/account", {"omitZeroBalances": "true"})

    async def account_balance(self, symbol: str) -> Decimal:
        """Saldo livre na moeda de cotação do par (ex.: USDT em BTCUSDT)."""
        rules = await self.get_rules(symbol)
        for b in (await self.account()).get("balances", []):
            if b.get("asset") == rules.quote_asset:
                return Decimal(b.get("free", "0"))
        return Decimal("0")

    async def api_restrictions(self) -> dict[str, Any] | None:
        """Permissões da chave (só existe na produção). Usado para recusar chaves com saque habilitado."""
        if self.venue != "live":
            return None
        return await self._signed("GET", "/sapi/v1/account/apiRestrictions", {})

    # ---------------- ordens ----------------
    def _to_fill(self, data: dict[str, Any], side: Side, rules: SymbolRules | None) -> Fill:
        executed = Decimal(data.get("executedQty", "0"))
        quote = Decimal(data.get("cummulativeQuoteQty", "0"))
        avg = (quote / executed) if executed > 0 else Decimal("0")
        fee_quote = Decimal("0")
        fee_base = Decimal("0")
        for f in data.get("fills", []):
            commission = Decimal(f.get("commission", "0"))
            asset = f.get("commissionAsset")
            if rules and asset == rules.quote_asset:
                fee_quote += commission
            elif rules and asset == rules.base_asset:
                fee_base += commission
                fee_quote += commission * Decimal(f.get("price", avg))
            # Taxa em BNB: não altera saldo do par; fica registrada no bruto (raw) para conciliação.
        net = executed - fee_base if side == Side.buy else executed
        return Fill(
            client_order_id=data.get("clientOrderId", ""),
            exchange_order_id=str(data.get("orderId")) if data.get("orderId") is not None else None,
            status=data.get("status", "UNKNOWN"),
            side=side,
            executed_qty=executed,
            net_base_qty=net,
            avg_price=avg,
            quote_qty=quote,
            fee_quote=fee_quote,
            raw=data,
        )

    async def market_buy_quote(self, symbol: str, quote_amount: Decimal, client_order_id: str) -> Fill:
        rules = await self.get_rules(symbol)
        amount = rules.floor_quote(quote_amount)
        data = await self._signed(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": "BUY",
                "type": "MARKET",
                "quoteOrderQty": format(amount, "f"),
                "newClientOrderId": client_order_id,
                "newOrderRespType": "FULL",
            },
        )
        return self._to_fill(data, Side.buy, rules)

    async def market_sell_qty(self, symbol: str, qty: Decimal, client_order_id: str) -> Fill:
        rules = await self.get_rules(symbol)
        data = await self._signed(
            "POST",
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": "SELL",
                "type": "MARKET",
                "quantity": format(rules.floor_qty(qty), "f"),
                "newClientOrderId": client_order_id,
                "newOrderRespType": "FULL",
            },
        )
        return self._to_fill(data, Side.sell, rules)

    # ---------------- interface genérica de posição ----------------
    async def open_position(self, symbol, side, client_order_id, *, quote_amount=None, units=None, sl_price=None, tp_price=None) -> Fill:
        if side != PosSide.long:
            raise BrokerError("Binance Spot não permite operar vendido")
        if quote_amount is None:
            raise BrokerError("Informe o valor da ordem em moeda de cotação")
        return await self.market_buy_quote(symbol, quote_amount, client_order_id)

    async def close_position(self, symbol, side, qty, client_order_id, external_id=None) -> Fill:
        return await self.market_sell_qty(symbol, qty, client_order_id)

    async def closed_by_broker(self, symbol, external_id) -> Fill | None:
        return None  # stop/alvo são vigiados pelo motor

    async def query_order(self, symbol: str, client_order_id: str) -> Fill | None:
        try:
            data = await self._signed("GET", "/api/v3/order", {"symbol": symbol, "origClientOrderId": client_order_id})
        except BrokerError as exc:
            if exc.code == -2013:  # ordem não existe
                return None
            raise
        side = Side.buy if data.get("side") == "BUY" else Side.sell
        rules = await self.get_rules(symbol)
        # A consulta não traz "fills"; taxa fica zerada e deve ser conciliada via /api/v3/myTrades se necessário.
        return self._to_fill(data, side, rules)
