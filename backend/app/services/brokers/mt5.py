"""Futuros da B3 pelo MetaTrader 5 do cliente, através do Conector OráculoInvest (ver services/mt5_bridge.py).

Unidades: o motor trabalha em "unidades" com `lot_size` = valor do ponto por contrato (R$ 0,20 no WIN,
R$ 10 no WDO). Assim, quantidade × variação de preço = resultado em reais, igual ao forex. O conector
converte de volta para contratos.
"""
from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any

from app.models import PosSide, Side
from app.services import b3, mt5_bridge
from app.services.brokers.base import BrokerError, Candle, Fill, SymbolRules

PERIOD_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
RULES_TTL = 60
_RULES: dict[tuple[str, str], tuple[float, SymbolRules]] = {}


def D(v: Any) -> Decimal:
    return Decimal(str(v))


def rules_from_agent(root: str, data: dict) -> SymbolRules:
    tick_size = D(data["tick_size"])
    tick_value = D(data["tick_value"])
    if tick_size <= 0 or tick_value <= 0:
        raise BrokerError(f"O MetaTrader 5 não informou o valor do tick de {data.get('contract')}")
    point_value = tick_value / tick_size  # R$ por ponto por contrato
    step = D(data.get("volume_step") or 1)
    vmin = D(data.get("volume_min") or 1)
    vmax = D(data.get("volume_max") or 1000)
    exp = data.get("expiration")
    return SymbolRules(
        symbol=root,
        base_asset=root,
        quote_asset=data.get("currency") or "BRL",
        step_size=point_value * step,
        min_qty=point_value * vmin,
        max_qty=point_value * vmax,
        min_notional=Decimal("0"),
        quote_precision=2,
        trading=bool(data.get("trade_allowed", True)),
        lot_size=point_value,
        allow_short=True,
        schedule=b3.schedule(root),
        schedule_tz=b3.TZ,
        contract=data["contract"],
        expiration=datetime.fromtimestamp(exp, UTC) if exp else None,
        currency=data.get("currency") or "BRL",
    )


def split_external(external_id: str | None) -> tuple[str, int]:
    if not external_id or ":" not in external_id:
        raise BrokerError("Posição sem identificação do MetaTrader 5")
    contract, ticket = external_id.split(":", 1)
    return contract, int(ticket)


class MT5Broker:
    supports_short = True

    def __init__(self, cred_id: uuid.UUID, venue: str):
        self.cred_id = cred_id
        self.venue = venue

    async def close(self) -> None:
        return None

    async def _call(self, kind: str, args: dict | None = None, timeout: float = 15) -> Any:
        return await mt5_bridge.call(self.cred_id, kind, args, timeout)

    # ---------------- dados ----------------
    async def get_rules(self, symbol: str) -> SymbolRules:
        root = b3.info(symbol).root
        key = (str(self.cred_id), root)
        hit = _RULES.get(key)
        if hit and time.monotonic() - hit[0] < RULES_TTL:
            return hit[1]
        rules = rules_from_agent(root, await self._call("rules", {"root": root}))
        _RULES[key] = (time.monotonic(), rules)
        return rules

    @staticmethod
    def _candles(rows: list[dict], interval: str) -> list[Candle]:
        step = PERIOD_MS[interval]
        out = [
            Candle(
                open_time=int(r["t"]) * 1000,
                open=float(r["o"]),
                high=float(r["h"]),
                low=float(r["l"]),
                close=float(r["c"]),
                volume=float(r.get("v", 0)),
                close_time=int(r["t"]) * 1000 + step - 1,
            )
            for r in rows
        ]
        return sorted(out, key=lambda c: c.open_time)

    async def get_klines(self, symbol: str, interval: str, limit: int = 200) -> list[Candle]:
        rows = await self._call("candles", {"root": b3.info(symbol).root, "timeframe": interval, "count": limit}, timeout=20)
        return self._candles(rows, interval)[-limit:]

    async def get_klines_range(self, symbol: str, interval: str, start_ms: int, end_ms: int, max_candles: int) -> list[Candle]:
        rows = await self._call(
            "candles_range",
            {"root": b3.info(symbol).root, "timeframe": interval, "from": start_ms // 1000, "to": end_ms // 1000, "max": max_candles},
            timeout=40,
        )
        now = int(time.time() * 1000)
        return [c for c in self._candles(rows, interval) if c.close_time < now][:max_candles]

    async def get_price(self, symbol: str) -> Decimal:
        t = await self._call("tick", {"root": b3.info(symbol).root})
        last = D(t.get("last") or 0)
        if last > 0:
            return last
        bid, ask = D(t.get("bid") or 0), D(t.get("ask") or 0)
        if bid > 0 and ask > 0:
            return (bid + ask) / 2
        raise BrokerError(f"Sem cotação de {symbol} agora (mercado fechado?)", retryable=True)

    # ---------------- ordens ----------------
    @staticmethod
    def _contracts(rules: SymbolRules, units: Decimal) -> Decimal:
        contracts = (Decimal(units) / rules.lot_size).to_integral_value(rounding=ROUND_DOWN)
        if contracts * rules.lot_size < rules.min_qty or contracts <= 0:
            raise BrokerError("Tamanho abaixo de 1 contrato")
        return contracts

    def _fill(self, data: dict, side: Side, coid: str, rules: SymbolRules, *, closing: bool) -> Fill:
        qty = D(data["volume"]) * rules.lot_size
        price = D(data["price"])
        realized = None
        if closing:
            # Resultado informado pela corretora, já com a corretagem/emolumentos da saída.
            realized = D(data.get("profit", 0)) + D(data.get("commission", 0)) + D(data.get("swap", 0)) + D(data.get("fee", 0))
        fee = abs(D(data.get("commission", 0))) + abs(D(data.get("fee", 0)))
        return Fill(
            client_order_id=coid,
            exchange_order_id=str(data.get("order") or data.get("deal") or ""),
            status="FILLED",
            side=side,
            executed_qty=qty,
            net_base_qty=qty,
            avg_price=price,
            quote_qty=qty * price,
            fee_quote=fee,  # no fechamento é só informativo: o resultado já vem líquido da corretora
            raw=data,
            external_position_id=f"{data['contract']}:{data['position']}" if data.get("position") else None,
            realized_pnl=realized,
        )

    async def open_position(self, symbol, side, client_order_id, *, quote_amount=None, units=None, sl_price=None, tp_price=None) -> Fill:
        if units is None:
            raise BrokerError("Informe o número de contratos")
        rules = await self.get_rules(symbol)
        contracts = self._contracts(rules, Decimal(units))
        trade = Side.buy if side == PosSide.long else Side.sell
        data = await self._call(
            "open",
            {
                "root": rules.symbol,
                "side": "buy" if trade == Side.buy else "sell",
                "volume": float(contracts),
                "sl": float(sl_price) if sl_price is not None else None,
                "tp": float(tp_price) if tp_price is not None else None,
                "coid": client_order_id,
            },
            timeout=25,
        )
        return self._fill(data, trade, client_order_id, rules, closing=False)

    async def close_position(self, symbol, side, qty, client_order_id, external_id=None) -> Fill:
        rules = await self.get_rules(symbol)
        contract, ticket = split_external(external_id)
        trade = Side.sell if side == PosSide.long else Side.buy
        data = await self._call(
            "close",
            {"contract": contract, "position": ticket, "side": "sell" if trade == Side.sell else "buy",
             "volume": float(self._contracts(rules, Decimal(qty))), "coid": client_order_id},
            timeout=25,
        )
        return self._fill(data, trade, client_order_id, rules, closing=True)

    async def closed_by_broker(self, symbol: str, external_id: str | None) -> Fill | None:
        if not external_id:
            return None
        contract, ticket = split_external(external_id)
        data = await self._call("position_status", {"contract": contract, "position": ticket})
        if data.get("open") or not data.get("closing"):
            return None
        rules = await self.get_rules(symbol)
        closing = {**data["closing"], "contract": contract, "position": ticket}
        side = Side.buy if closing.get("side") == "buy" else Side.sell
        fill = self._fill(closing, side, f"tbx{uuid.uuid4().hex[:29]}", rules, closing=True)
        return fill

    async def query_order(self, symbol: str, client_order_id: str) -> Fill | None:
        data = await self._call("find", {"coid": client_order_id})
        if not data:
            return None
        rules = await self.get_rules(symbol)
        side = Side.buy if data.get("side") == "buy" else Side.sell
        return self._fill(data, side, client_order_id, rules, closing=bool(data.get("closing")))
