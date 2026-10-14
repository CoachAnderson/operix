"""Corretora simulada: preços e regras reais da corretora de origem, execução e saldo virtuais.

Dois modos de conta:
- à vista (cripto): compra gasta o saldo em moeda de cotação e recebe o ativo; não opera vendido;
- margem (forex): o saldo só muda pelo resultado realizado; permite comprado e vendido.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from app.core.config import get_settings
from app.models import PosSide, Side
from app.services.brokers.base import BrokerError, Candle, Fill, SymbolRules


@dataclass
class PaperAccount:
    quote: Decimal  # saldo (moeda de cotação/conta)
    base: Decimal  # só no modo à vista: ativo em carteira


class PaperBroker:
    venue = "paper"

    def __init__(self, market_data, account: PaperAccount, fee_rate: float | None = None, slippage_bps: float | None = None, margin: bool = False):
        s = get_settings()
        self._md = market_data  # objeto com get_price/get_klines/get_rules (Binance pública, cTrader...)
        self.account = account
        self.margin = margin
        self.supports_short = margin
        self.fee_rate = Decimal(str(fee_rate if fee_rate is not None else s.paper_fee_rate))
        self.slippage = Decimal(str(slippage_bps if slippage_bps is not None else s.paper_slippage_bps)) / Decimal(10000)
        self._open_side: dict[str, tuple[PosSide, Decimal, Decimal]] = {}  # margem: lado, qtd, preço de entrada

    async def close(self) -> None:
        if hasattr(self._md, "close"):
            await self._md.close()

    async def get_price(self, symbol: str) -> Decimal:
        return await self._md.get_price(symbol)

    async def get_klines(self, symbol: str, interval: str, limit: int = 200) -> list[Candle]:
        return await self._md.get_klines(symbol, interval, limit)

    async def get_rules(self, symbol: str) -> SymbolRules:
        return await self._md.get_rules(symbol)

    def _fill(self, coid: str, side: Side, qty: Decimal, price: Decimal, fee: Decimal, net: Decimal | None = None, pnl: Decimal | None = None) -> Fill:
        return Fill(
            client_order_id=coid,
            exchange_order_id=f"paper-{uuid.uuid4().hex[:12]}",
            status="FILLED",
            side=side,
            executed_qty=qty,
            net_base_qty=net if net is not None else qty,
            avg_price=price,
            quote_qty=qty * price,
            fee_quote=fee,
            realized_pnl=pnl,
        )

    # ---------------- interface genérica ----------------
    async def open_position(self, symbol, side, client_order_id, *, quote_amount=None, units=None, sl_price=None, tp_price=None) -> Fill:
        if side == PosSide.short and not self.margin:
            raise BrokerError("A simulação à vista não opera vendido")
        if not self.margin:
            if quote_amount is None:
                raise BrokerError("Informe o valor da ordem")
            return await self.market_buy_quote(symbol, Decimal(quote_amount), client_order_id)
        if units is None:
            raise BrokerError("Informe o tamanho em unidades")
        rules = await self.get_rules(symbol)
        qty = rules.floor_qty(Decimal(units))
        if qty < rules.min_qty or qty <= 0:
            raise BrokerError(f"Tamanho abaixo do mínimo ({rules.min_qty} unidades)")
        ref = await self.get_price(symbol)
        price = ref * (1 + self.slippage) if side == PosSide.long else ref * (1 - self.slippage)
        fee = qty * price * self.fee_rate
        self.account.quote -= fee
        return self._fill(client_order_id, Side.buy if side == PosSide.long else Side.sell, qty, price, fee)

    async def close_position(self, symbol, side, qty, client_order_id, external_id=None) -> Fill:
        if not self.margin:
            return await self.market_sell_qty(symbol, Decimal(qty), client_order_id)
        ref = await self.get_price(symbol)
        price = ref * (1 - self.slippage) if side == PosSide.long else ref * (1 + self.slippage)
        qty = Decimal(qty)
        fee = qty * price * self.fee_rate
        # O resultado bruto é calculado pelo motor (precisa do preço de entrada); aqui só a taxa de saída.
        self.account.quote -= fee
        return self._fill(client_order_id, Side.sell if side == PosSide.long else Side.buy, qty, price, fee)

    def settle(self, gross_pnl: Decimal) -> None:
        """Margem: credita/debita o resultado bruto da posição encerrada."""
        if self.margin:
            self.account.quote += gross_pnl

    async def closed_by_broker(self, symbol, external_id) -> Fill | None:
        return None

    # ---------------- à vista ----------------
    async def market_buy_quote(self, symbol: str, quote_amount: Decimal, client_order_id: str) -> Fill:
        rules = await self.get_rules(symbol)
        amount = rules.floor_quote(min(quote_amount, self.account.quote))
        if amount < rules.min_notional or amount <= 0:
            raise BrokerError(f"Saldo simulado insuficiente ou abaixo do mínimo ({rules.min_notional} {rules.quote_asset})")
        price = (await self.get_price(symbol)) * (1 + self.slippage)
        gross_qty = rules.floor_qty(amount / price)
        if gross_qty < rules.min_qty or gross_qty <= 0:
            raise BrokerError("Quantidade abaixo do mínimo do par")
        cost = gross_qty * price
        fee_base = gross_qty * self.fee_rate  # Binance cobra a taxa da compra no ativo recebido
        net = gross_qty - fee_base
        self.account.quote -= cost
        self.account.base += net
        return self._fill(client_order_id, Side.buy, gross_qty, price, fee_base * price, net=net)

    async def market_sell_qty(self, symbol: str, qty: Decimal, client_order_id: str) -> Fill:
        rules = await self.get_rules(symbol)
        qty = rules.floor_qty(min(qty, self.account.base))
        if qty <= 0 or qty < rules.min_qty:
            raise BrokerError("Quantidade simulada insuficiente para vender")
        price = (await self.get_price(symbol)) * (1 - self.slippage)
        gross = qty * price
        if gross < rules.min_notional:
            raise BrokerError(f"Venda abaixo do mínimo ({rules.min_notional} {rules.quote_asset})")
        fee = gross * self.fee_rate
        self.account.base -= qty
        self.account.quote += gross - fee
        return self._fill(client_order_id, Side.sell, qty, price, fee)

    async def query_order(self, symbol: str, client_order_id: str) -> Fill | None:
        return None  # a simulação é síncrona; nunca há ordem em estado desconhecido
