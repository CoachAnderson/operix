"""cTrader Open API (Spotware) — conexão JSON por WebSocket na porta 5036, sem SDK de terceiros.

Documentação: https://help.ctrader.com/open-api/
Mensagens: https://github.com/spotware/openapi-proto-messages

Cada cliente usa as PRÓPRIAS credenciais: Client ID/Secret do app (do cliente ou da plataforma) e o
Access Token da conta dele. Uma conexão é aberta por (ambiente, Client ID) e reaproveitada; várias contas
podem ser autorizadas na mesma conexão.

Preços em barras e cotações vêm em 1/100000 da unidade; volumes em centésimos de unidade
(volume 100000 = 1.000 unidades = 0,01 lote padrão).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any

import websockets

from app.core.config import get_settings
from app.models import PosSide, Side
from app.services.brokers.base import BrokerError, Candle, Fill, OrderUnknownError, SymbolRules

log = logging.getLogger(__name__)

PRICE_SCALE = 100_000
HEARTBEAT_SECONDS = 10
REQUEST_TIMEOUT = 15


class PT:
    """Payload types (OpenApiMessages.proto / OpenApiCommonModelMessages.proto)."""

    ERROR_RES = 50
    HEARTBEAT = 51
    APP_AUTH_REQ, APP_AUTH_RES = 2100, 2101
    ACCOUNT_AUTH_REQ, ACCOUNT_AUTH_RES = 2102, 2103
    NEW_ORDER_REQ = 2106
    CLOSE_POSITION_REQ = 2111
    SYMBOLS_LIST_REQ, SYMBOLS_LIST_RES = 2114, 2115
    SYMBOL_BY_ID_REQ, SYMBOL_BY_ID_RES = 2116, 2117
    TRADER_REQ, TRADER_RES = 2121, 2122
    RECONCILE_REQ, RECONCILE_RES = 2124, 2125
    EXECUTION_EVENT = 2126
    SPOT_EVENT = 2131
    ORDER_ERROR_EVENT = 2132
    GET_TRENDBARS_REQ, GET_TRENDBARS_RES = 2137, 2138
    OA_ERROR_RES = 2142
    TOKEN_INVALIDATED_EVENT = 2147
    CLIENT_DISCONNECT_EVENT = 2148
    ACCOUNTS_BY_TOKEN_REQ, ACCOUNTS_BY_TOKEN_RES = 2149, 2150
    DEALS_BY_POSITION_REQ, DEALS_BY_POSITION_RES = 2179, 2180


ORDER_MARKET = 1
SIDE = {Side.buy: 1, Side.sell: 2}
EXEC_FILLED, EXEC_PARTIAL = 3, 11
EXEC_FAIL = {5: "CANCELED", 6: "EXPIRED", 7: "REJECTED"}
PERIOD = {"1m": 1, "5m": 5, "15m": 7, "30m": 8, "1h": 9, "4h": 10, "1d": 12}
PERIOD_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


class CTraderError(BrokerError):
    pass


def _i(v: Any, default: int = 0) -> int:
    """int64 pode chegar como string no JSON."""
    return int(v) if v is not None and v != "" else default


def _enum(v: Any) -> int | str:
    return int(v) if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()) else v


# ------------------------------------------------------------------ conversões (puras, testáveis)
def trendbar_to_candle(tb: dict, interval: str) -> Candle:
    low = _i(tb.get("low"))
    open_ms = _i(tb["utcTimestampInMinutes"]) * 60_000
    return Candle(
        open_time=open_ms,
        open=(low + _i(tb.get("deltaOpen"))) / PRICE_SCALE,
        high=(low + _i(tb.get("deltaHigh"))) / PRICE_SCALE,
        low=low / PRICE_SCALE,
        close=(low + _i(tb.get("deltaClose"))) / PRICE_SCALE,
        volume=float(_i(tb.get("volume"))),
        close_time=open_ms + PERIOD_MS[interval] - 1,
    )


def symbol_to_rules(name: str, sym: dict) -> SymbolRules:
    step = Decimal(_i(sym.get("stepVolume"), 100_000)) / 100
    return SymbolRules(
        symbol=name,
        base_asset=name[:3],
        quote_asset=name[3:],
        step_size=step,
        min_qty=Decimal(_i(sym.get("minVolume"), 100_000)) / 100,
        max_qty=Decimal(_i(sym.get("maxVolume"), 10**14)) / 100,
        min_notional=Decimal("0"),
        quote_precision=_i(sym.get("digits"), 5),
        trading=_enum(sym.get("tradingMode", 0)) in (0, "ENABLED"),
        lot_size=Decimal(_i(sym.get("lotSize"), 10_000_000)) / 100,
        allow_short=bool(sym.get("enableShortSelling", True)),
        schedule=tuple((_i(x["startSecond"]), _i(x["endSecond"])) for x in sym.get("schedule", [])) or None,
        schedule_tz=sym.get("scheduleTimeZone") or "UTC",
    )


def money_value(v: Any, digits: Any) -> Decimal:
    return Decimal(_i(v)) / (Decimal(10) ** _i(digits, 2))


def close_detail_pnl(deal: dict) -> Decimal:
    """Resultado líquido do fechamento, sem a comissão de abertura (o motor desconta a da entrada).
    Comissão, swap negativo e taxa de conversão chegam com sinal negativo."""
    d = deal.get("closePositionDetail") or {}
    digits = d.get("moneyDigits", deal.get("moneyDigits", 2))
    return money_value(d.get("grossProfit"), digits) + money_value(d.get("swap"), digits) - abs(
        money_value(d.get("commission"), digits)
    ) - abs(money_value(d.get("pnlConversionFee"), digits))


# ------------------------------------------------------------------ conexão
class CTraderConnection:
    def __init__(self, host: str, client_id: str, client_secret: str, port: int | None = None, url: str | None = None):
        self.url = url or f"wss://{host}:{port or get_settings().ctrader_json_port}"
        self.client_id, self.client_secret = client_id, client_secret
        self._ws = None
        self._pending: dict[str, asyncio.Future] = {}
        self._waiters: list[tuple[Callable[[int, dict], bool], asyncio.Future]] = []
        self._authorized: set[int] = set()
        self._tasks: list[asyncio.Task] = []
        self._lock = asyncio.Lock()
        self.closed = True

    async def ensure(self) -> None:
        async with self._lock:
            if not self.closed:
                return
            try:
                self._ws = await websockets.connect(self.url, open_timeout=10, ping_interval=None, max_size=2**24)
            except Exception as exc:  # noqa: BLE001
                raise CTraderError(f"Não foi possível conectar ao cTrader: {exc}", retryable=True) from exc
            self.closed = False
            self._authorized.clear()
            self._tasks = [asyncio.create_task(self._reader()), asyncio.create_task(self._heartbeat())]
            await self.request(PT.APP_AUTH_REQ, {"clientId": self.client_id, "clientSecret": self.client_secret}, skip_ensure=True)

    async def close(self) -> None:
        self.closed = True
        for t in self._tasks:
            t.cancel()
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()

    async def _heartbeat(self) -> None:
        while not self.closed:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            with contextlib.suppress(Exception):
                await self._ws.send(json.dumps({"payloadType": PT.HEARTBEAT, "payload": {}}))

    async def _reader(self) -> None:
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                pt, payload, mid = _i(msg.get("payloadType")), msg.get("payload") or {}, msg.get("clientMsgId")
                if pt in (PT.HEARTBEAT, PT.SPOT_EVENT):
                    continue
                if pt == PT.TOKEN_INVALIDATED_EVENT:
                    for acc in payload.get("ctidTraderAccountIds", []):
                        self._authorized.discard(_i(acc))
                if mid and mid in self._pending and not self._pending[mid].done():
                    self._pending.pop(mid).set_result((pt, payload))
                for pred, fut in list(self._waiters):
                    if not fut.done() and pred(pt, payload):
                        fut.set_result((pt, payload))
        except Exception as exc:  # noqa: BLE001
            log.warning("Conexão cTrader encerrada: %s", exc)
        finally:
            self.closed = True
            err = CTraderError("Conexão com o cTrader caiu", retryable=True)
            for fut in list(self._pending.values()) + [f for _, f in self._waiters]:
                if not fut.done():
                    fut.set_exception(err)
            self._pending.clear()

    async def request(self, payload_type: int, payload: dict, *, timeout: float = REQUEST_TIMEOUT, skip_ensure: bool = False) -> tuple[int, dict]:
        if not skip_ensure:
            await self.ensure()
        mid = uuid.uuid4().hex[:16]
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self._ws.send(json.dumps({"clientMsgId": mid, "payloadType": payload_type, "payload": payload}))
        try:
            pt, res = await asyncio.wait_for(fut, timeout)
        except TimeoutError as exc:
            self._pending.pop(mid, None)
            raise CTraderError("Tempo esgotado aguardando o cTrader", retryable=True) from exc
        if pt in (PT.OA_ERROR_RES, PT.ERROR_RES, PT.ORDER_ERROR_EVENT):
            code = res.get("errorCode", "ERRO")
            raise CTraderError(f"cTrader {code}: {res.get('description', '')}".strip(), retryable=code in ("BLOCKED_PAYLOAD_TYPE", "CANT_ROUTE_REQUEST", "TIMEOUT_ERROR"))
        return pt, res

    def waiter(self, predicate: Callable[[int, dict], bool]) -> asyncio.Future:
        """Registra ANTES de enviar a ordem, para não perder eventos que cheguem rápido."""
        fut = asyncio.get_running_loop().create_future()
        self._waiters.append((predicate, fut))
        fut.add_done_callback(lambda f: self._waiters.remove((predicate, fut)) if (predicate, fut) in self._waiters else None)
        return fut

    async def authorize_account(self, account_id: int, access_token: str) -> None:
        await self.ensure()
        if account_id in self._authorized:
            return
        await self.request(PT.ACCOUNT_AUTH_REQ, {"ctidTraderAccountId": account_id, "accessToken": access_token})
        self._authorized.add(account_id)


_POOL: dict[tuple[str, str], CTraderConnection] = {}
_POOL_LOCK = asyncio.Lock()


async def get_connection(live: bool, client_id: str, client_secret: str) -> CTraderConnection:
    s = get_settings()
    host = s.ctrader_live_host if live else s.ctrader_demo_host
    async with _POOL_LOCK:
        conn = _POOL.get((host, client_id))
        if conn is None or (conn.closed and conn.client_secret != client_secret):
            conn = CTraderConnection(host, client_id, client_secret)
            _POOL[(host, client_id)] = conn
    await conn.ensure()
    return conn


async def list_accounts(client_id: str, client_secret: str, access_token: str) -> tuple[list[dict], bool]:
    """Contas que o token libera e se o token permite negociar (SCOPE_TRADE)."""
    conn = await get_connection(True, client_id, client_secret)
    _, res = await conn.request(PT.ACCOUNTS_BY_TOKEN_REQ, {"accessToken": access_token})
    scope = _enum(res.get("permissionScope", 0))
    return res.get("ctidTraderAccount", []), scope in (1, "SCOPE_TRADE")


# ------------------------------------------------------------------ corretora
@dataclass
class _SymbolCache:
    by_name: dict[str, int]
    rules: dict[str, SymbolRules]
    at: float


_SYMBOLS: dict[tuple[str, int], _SymbolCache] = {}


class CTraderBroker:
    supports_short = True

    def __init__(self, conn: CTraderConnection, account_id: int, access_token: str, venue: str):
        self.conn = conn
        self.account_id = account_id
        self.access_token = access_token
        self.venue = venue

    async def close(self) -> None:
        return None  # a conexão é compartilhada no pool

    async def _req(self, pt: int, payload: dict, **kw) -> dict:
        await self.conn.authorize_account(self.account_id, self.access_token)
        _, res = await self.conn.request(pt, {"ctidTraderAccountId": self.account_id, **payload}, **kw)
        return res

    # ---------------- símbolos e dados ----------------
    async def _symbol(self, name: str) -> tuple[int, SymbolRules]:
        key = (self.conn.url, self.account_id)
        cache = _SYMBOLS.get(key)
        if cache is None or time.monotonic() - cache.at > 3600:
            res = await self._req(PT.SYMBOLS_LIST_REQ, {"includeArchivedSymbols": False})
            cache = _SymbolCache(
                by_name={str(s.get("symbolName", "")).upper().replace("/", ""): _i(s["symbolId"]) for s in res.get("symbol", [])},
                rules={},
                at=time.monotonic(),
            )
            _SYMBOLS[key] = cache
        sid = cache.by_name.get(name.upper())
        if sid is None:
            raise CTraderError(f"Símbolo {name} não existe nesta conta cTrader")
        if name not in cache.rules:
            res = await self._req(PT.SYMBOL_BY_ID_REQ, {"symbolId": [sid]})
            if not res.get("symbol"):
                raise CTraderError(f"Detalhes do símbolo {name} indisponíveis")
            cache.rules[name] = symbol_to_rules(name, res["symbol"][0])
        return sid, cache.rules[name]

    async def get_rules(self, symbol: str) -> SymbolRules:
        return (await self._symbol(symbol))[1]

    async def get_klines(self, symbol: str, interval: str, limit: int = 200) -> list[Candle]:
        sid, _ = await self._symbol(symbol)
        now = int(time.time() * 1000)
        # Janela folgada por causa de fins de semana e feriados; `count` limita a partir do fim.
        start = now - PERIOD_MS[interval] * limit * 3 - 4 * 86_400_000
        res = await self._req(
            PT.GET_TRENDBARS_REQ,
            {"symbolId": sid, "period": PERIOD[interval], "fromTimestamp": start, "toTimestamp": now, "count": limit},
        )
        candles = sorted((trendbar_to_candle(tb, interval) for tb in res.get("trendbar", [])), key=lambda c: c.open_time)
        return candles[-limit:]

    async def get_klines_range(self, symbol: str, interval: str, start_ms: int, end_ms: int, max_candles: int) -> list[Candle]:
        sid, _ = await self._symbol(symbol)
        step = PERIOD_MS[interval]
        out: dict[int, Candle] = {}
        cursor = start_ms
        chunk = step * 2000
        while cursor < end_ms and len(out) < max_candles:
            to = min(end_ms, cursor + chunk)
            res = await self._req(PT.GET_TRENDBARS_REQ, {"symbolId": sid, "period": PERIOD[interval], "fromTimestamp": cursor, "toTimestamp": to})
            for tb in res.get("trendbar", []):
                c = trendbar_to_candle(tb, interval)
                out[c.open_time] = c
            cursor = to
        now = int(time.time() * 1000)
        return [c for c in sorted(out.values(), key=lambda c: c.open_time) if c.close_time < now][:max_candles]

    async def get_price(self, symbol: str) -> Decimal:
        bars = await self.get_klines(symbol, "1m", 2)
        if not bars:
            raise CTraderError(f"Sem cotação recente para {symbol} (mercado fechado?)", retryable=True)
        return Decimal(str(bars[-1].close))

    async def trader(self) -> dict:
        res = await self._req(PT.TRADER_REQ, {})
        return res.get("trader", {})

    # ---------------- ordens ----------------
    @staticmethod
    def _volume(rules: SymbolRules, units: Decimal) -> int:
        units = rules.floor_qty(units)
        if units < rules.min_qty:
            raise CTraderError(f"Tamanho abaixo do mínimo do símbolo ({rules.min_qty} unidades)")
        return int((units * 100).to_integral_value(rounding=ROUND_DOWN))

    def _fill_from_event(self, ev: dict, side: Side, client_order_id: str) -> Fill:
        deal = ev.get("deal") or {}
        pos = ev.get("position") or {}
        qty = Decimal(_i(deal.get("filledVolume") or deal.get("volume"))) / 100
        price = Decimal(str(deal.get("executionPrice") or pos.get("price") or 0))
        digits = deal.get("moneyDigits", pos.get("moneyDigits", 2))
        fee = abs(money_value(deal.get("commission"), digits))
        closing = bool(deal.get("closePositionDetail"))
        return Fill(
            client_order_id=client_order_id,
            exchange_order_id=str(deal.get("orderId") or (ev.get("order") or {}).get("orderId") or ""),
            status="FILLED" if _i(ev.get("executionType")) == EXEC_FILLED else "PARTIALLY_FILLED",
            side=side,
            executed_qty=qty,
            net_base_qty=qty,
            avg_price=price,
            quote_qty=qty * price,
            fee_quote=fee,
            raw=ev,
            external_position_id=str(_i(pos.get("positionId") or deal.get("positionId"))) or None,
            realized_pnl=close_detail_pnl(deal) if closing else None,
        )

    def _filled(self, match: Callable[[dict], bool]) -> Callable[[int, dict], bool]:
        def pred(pt: int, p: dict) -> bool:
            if _i(p.get("ctidTraderAccountId")) != self.account_id:
                return False
            return pt == PT.EXECUTION_EVENT and _i(p.get("executionType")) in (EXEC_FILLED, EXEC_PARTIAL, *EXEC_FAIL) and match(p)

        return pred

    async def _await_fill(self, fut: asyncio.Future, side: Side, client_order_id: str) -> Fill:
        try:
            pt, ev = await asyncio.wait_for(fut, REQUEST_TIMEOUT)
        except TimeoutError as exc:
            raise OrderUnknownError("Ordem enviada sem confirmação do cTrader", retryable=True) from exc
        if pt == PT.ORDER_ERROR_EVENT:
            raise CTraderError(f"cTrader recusou: {ev.get('errorCode')} {ev.get('description', '')}".strip())
        et = _i(ev.get("executionType"))
        if et in EXEC_FAIL:
            raise CTraderError(f"Ordem {EXEC_FAIL[et]} pelo cTrader {ev.get('errorCode') or ''}".strip())
        return self._fill_from_event(ev, side, client_order_id)

    async def open_position(self, symbol, side, client_order_id, *, quote_amount=None, units=None, sl_price=None, tp_price=None) -> Fill:
        if units is None:
            raise CTraderError("Informe o tamanho em lotes")
        sid, rules = await self._symbol(symbol)
        if side == PosSide.short and not rules.allow_short:
            raise CTraderError(f"A corretora não permite operar vendido em {symbol}")
        volume = self._volume(rules, Decimal(units))
        trade_side = Side.buy if side == PosSide.long else Side.sell
        payload: dict[str, Any] = {
            "symbolId": sid,
            "orderType": ORDER_MARKET,
            "tradeSide": SIDE[trade_side],
            "volume": volume,
            "label": "operix",
            "comment": client_order_id,
            "clientOrderId": client_order_id,
        }
        # Ordem a mercado aceita só stop/alvo RELATIVOS (em 1/100000 do preço).
        if sl_price is not None or tp_price is not None:
            ref = await self.get_price(symbol)
            if sl_price is not None:
                payload["relativeStopLoss"] = max(1, int(abs(ref - Decimal(sl_price)) * PRICE_SCALE))
            if tp_price is not None:
                payload["relativeTakeProfit"] = max(1, int(abs(Decimal(tp_price) - ref) * PRICE_SCALE))

        fut = self.conn.waiter(self._filled(lambda p: (p.get("order") or {}).get("clientOrderId") == client_order_id))
        try:
            # A resposta direta costuma ser ORDER_ACCEPTED; a execução chega em seguida como evento.
            first = await self._req(PT.NEW_ORDER_REQ, payload)
        except CTraderError:
            fut.cancel()
            raise
        if _i(first.get("executionType")) in (EXEC_FILLED, EXEC_PARTIAL) and first.get("deal"):
            fut.cancel()
            return self._fill_from_event(first, trade_side, client_order_id)
        return await self._await_fill(fut, trade_side, client_order_id)

    async def close_position(self, symbol, side, qty, client_order_id, external_id=None) -> Fill:
        if not external_id:
            raise CTraderError("Posição sem identificador do cTrader")
        _, rules = await self._symbol(symbol)
        pid = int(external_id)
        trade_side = Side.sell if side == PosSide.long else Side.buy
        fut = self.conn.waiter(
            self._filled(lambda p: _i((p.get("position") or {}).get("positionId")) == pid
                         and (bool((p.get("deal") or {}).get("closePositionDetail")) or _i(p.get("executionType")) in EXEC_FAIL))
        )
        try:
            first = await self._req(PT.CLOSE_POSITION_REQ, {"positionId": pid, "volume": int(Decimal(qty) * 100)})
        except CTraderError:
            fut.cancel()
            raise
        if (first.get("deal") or {}).get("closePositionDetail"):
            fut.cancel()
            return self._fill_from_event(first, trade_side, client_order_id)
        return await self._await_fill(fut, trade_side, client_order_id)

    async def _open_positions(self) -> list[dict]:
        res = await self._req(PT.RECONCILE_REQ, {})
        return res.get("position", [])

    async def closed_by_broker(self, symbol: str, external_id: str | None) -> Fill | None:
        if not external_id:
            return None
        pid = int(external_id)
        if any(_i(p.get("positionId")) == pid for p in await self._open_positions()):
            return None
        now = int(time.time() * 1000)
        res = await self._req(PT.DEALS_BY_POSITION_REQ, {"positionId": pid, "fromTimestamp": now - 30 * 86_400_000, "toTimestamp": now})
        closing = [d for d in res.get("deal", []) if d.get("closePositionDetail")]
        if not closing:
            return None
        deal = max(closing, key=lambda d: _i(d.get("executionTimestamp")))
        side = Side.buy if _enum(deal.get("tradeSide")) in (1, "BUY") else Side.sell
        fill = self._fill_from_event({"executionType": EXEC_FILLED, "deal": deal, "position": {"positionId": pid}}, side, f"broker-{deal.get('dealId')}")
        fill.client_order_id = f"tbx{uuid.uuid4().hex[:29]}"
        return fill

    async def query_order(self, symbol: str, client_order_id: str) -> Fill | None:
        """Reconciliação de ordem de ABERTURA sem resposta: procura a posição pelo comentário."""
        for p in await self._open_positions():
            td = p.get("tradeData") or {}
            if td.get("comment") == client_order_id:
                side = Side.buy if _enum(td.get("tradeSide")) in (1, "BUY") else Side.sell
                qty = Decimal(_i(td.get("volume"))) / 100
                price = Decimal(str(p.get("price") or 0))
                return Fill(client_order_id, None, "FILLED", side, qty, qty, price, qty * price, Decimal("0"),
                            raw=p, external_position_id=str(_i(p.get("positionId"))))
        return None
