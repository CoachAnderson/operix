from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from app.models import PosSide, Side


class BrokerError(Exception):
    """Erro da corretora. `retryable` indica se pode tentar de novo no próximo ciclo."""

    def __init__(self, message: str, *, retryable: bool = False, code: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.code = code


class OrderUnknownError(BrokerError):
    """Timeout/erro de rede após enviar a ordem: o estado precisa ser reconciliado pelo client_order_id."""


@dataclass(frozen=True)
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    base_asset: str
    quote_asset: str
    step_size: Decimal
    min_qty: Decimal
    max_qty: Decimal
    min_notional: Decimal
    quote_precision: int
    trading: bool = True
    lot_size: Decimal = Decimal("1")  # unidades por lote (forex: geralmente 100.000)
    allow_short: bool = False
    # Horário de negociação: intervalos em segundos desde domingo 00:00 no fuso schedule_tz. None = 24x7.
    schedule: tuple[tuple[int, int], ...] | None = None
    schedule_tz: str = "UTC"
    # Futuros (B3): contrato em negociação (ex.: WINZ26) e o vencimento dele.
    contract: str | None = None
    expiration: datetime | None = None
    currency: str | None = None

    def _week_second(self, now: datetime | None) -> int:
        now = (now or datetime.now(UTC)).astimezone(ZoneInfo(self.schedule_tz))
        return ((now.weekday() + 1) % 7) * 86400 + now.hour * 3600 + now.minute * 60 + now.second  # domingo = 0

    def is_open(self, now: datetime | None = None) -> bool:
        if not self.schedule:
            return self.trading
        sec = self._week_second(now)
        return self.trading and any(start <= sec < end for start, end in self.schedule)

    def minutes_to_close(self, now: datetime | None = None) -> float | None:
        """Minutos até o fim da sessão atual. None quando o mercado é 24x7 ou está fechado."""
        if not self.schedule:
            return None
        sec = self._week_second(now)
        for start, end in self.schedule:
            if start <= sec < end:
                return (end - sec) / 60
        return None

    def floor_qty(self, qty: Decimal) -> Decimal:
        if self.step_size <= 0:
            return qty
        steps = (qty / self.step_size).to_integral_value(rounding=ROUND_DOWN)
        return (steps * self.step_size).normalize()

    def floor_quote(self, amount: Decimal) -> Decimal:
        return amount.quantize(Decimal(1).scaleb(-self.quote_precision), rounding=ROUND_DOWN)


@dataclass
class Fill:
    client_order_id: str
    exchange_order_id: str | None
    status: str  # FILLED, PARTIALLY_FILLED, REJECTED, EXPIRED, CANCELED, NEW
    side: Side
    executed_qty: Decimal  # quantidade bruta executada
    net_base_qty: Decimal  # quantidade líquida após taxa cobrada no ativo base (compra)
    avg_price: Decimal
    quote_qty: Decimal  # valor total em moeda de cotação
    fee_quote: Decimal  # taxa estimada em moeda de cotação
    raw: dict = field(default_factory=dict)
    external_position_id: str | None = None  # cTrader: positionId
    realized_pnl: Decimal | None = None  # quando a corretora informa o resultado do fechamento (moeda da conta)


class Broker(Protocol):
    venue: str
    supports_short: bool

    async def get_price(self, symbol: str) -> Decimal: ...

    async def get_klines(self, symbol: str, interval: str, limit: int = 200) -> list[Candle]: ...

    async def get_rules(self, symbol: str) -> SymbolRules: ...

    async def open_position(
        self,
        symbol: str,
        side: PosSide,
        client_order_id: str,
        *,
        quote_amount: Decimal | None = None,
        units: Decimal | None = None,
        sl_price: Decimal | None = None,
        tp_price: Decimal | None = None,
    ) -> Fill:
        """Abre posição a mercado. Cripto à vista usa quote_amount; forex usa units. SL/TP vão para a
        corretora quando ela suporta (cTrader); nas demais, o motor vigia a cada ciclo."""
        ...

    async def close_position(self, symbol: str, side: PosSide, qty: Decimal, client_order_id: str, external_id: str | None = None) -> Fill: ...

    async def closed_by_broker(self, symbol: str, external_id: str | None) -> Fill | None:
        """Se a corretora encerrou a posição sozinha (stop/alvo no servidor, stop-out), devolve o fechamento."""
        ...

    async def query_order(self, symbol: str, client_order_id: str) -> Fill | None: ...

    async def close(self) -> None: ...
