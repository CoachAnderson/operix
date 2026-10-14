from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


Money = Numeric(20, 2)
Qty = Numeric(28, 10)


def _enum(cls: type[enum.Enum]) -> Enum:
    return Enum(cls, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e])


class Role(str, enum.Enum):
    subscriber = "subscriber"
    admin = "admin"


class UserStatus(str, enum.Enum):
    active = "active"
    suspended = "suspended"
    deleted = "deleted"


class SubStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    paused = "paused"
    past_due = "past_due"
    cancelled = "cancelled"


class Venue(str, enum.Enum):
    paper = "paper"  # simulação interna
    testnet = "testnet"  # Binance Spot Testnet
    live = "live"  # conta real


class Market(str, enum.Enum):
    crypto = "crypto"  # Binance Spot
    forex = "forex"  # cTrader Open API


class PosSide(str, enum.Enum):
    long = "long"
    short = "short"


class ExecMode(str, enum.Enum):
    auto = "auto"  # robô executa
    signals = "signals"  # robô sugere, assinante confirma


class BotStatus(str, enum.Enum):
    stopped = "stopped"
    running = "running"
    paused_risk = "paused_risk"  # pausado pelo gerenciador de risco
    paused_billing = "paused_billing"  # assinatura inativa
    error = "error"


class Side(str, enum.Enum):
    buy = "BUY"
    sell = "SELL"


class OrderStatus(str, enum.Enum):
    new = "NEW"
    filled = "FILLED"
    partially_filled = "PARTIALLY_FILLED"
    rejected = "REJECTED"
    canceled = "CANCELED"
    unknown = "UNKNOWN"  # timeout; precisa reconciliar


class SignalStatus(str, enum.Enum):
    pending = "pending"
    executed = "executed"
    dismissed = "dismissed"
    expired = "expired"
    failed = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(_enum(Role), default=Role.subscriber)
    status: Mapped[UserStatus] = mapped_column(_enum(UserStatus), default=UserStatus.active)
    token_version: Mapped[int] = mapped_column(Integer, default=0)  # incrementar = derrubar todas as sessões
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    risk_terms_ip: Mapped[str | None] = mapped_column(String(64))
    risk_terms_version: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    subscriptions: Mapped[list[Subscription]] = relationship(back_populates="user", lazy="noload")


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    price_monthly: Mapped[Decimal] = mapped_column(Money)
    max_bots: Mapped[int] = mapped_column(Integer, default=1)
    allow_auto: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_live: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"))
    status: Mapped[SubStatus] = mapped_column(_enum(SubStatus), default=SubStatus.pending)
    mp_preapproval_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    init_point: Mapped[str | None] = mapped_column(Text)
    next_payment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="subscriptions", lazy="noload")
    plan: Mapped[Plan] = relationship(lazy="joined")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True)
    mp_authorized_payment_id: Mapped[str] = mapped_column(String(64), unique=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(40))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExchangeCredential(Base):
    __tablename__ = "exchange_credentials"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(80))
    exchange: Mapped[str] = mapped_column(String(20), default="binance")  # binance | ctrader
    venue: Mapped[Venue] = mapped_column(_enum(Venue))  # testnet (Binance testnet / cTrader demo) ou live
    # Binance: chave e segredo. cTrader: access token e refresh token (OAuth).
    api_key_enc: Mapped[str] = mapped_column(Text)
    api_secret_enc: Mapped[str] = mapped_column(Text)
    # cTrader com app próprio do cliente: Client ID e Client Secret dele (cifrados). Vazio = app da plataforma.
    client_id_enc: Mapped[str | None] = mapped_column(Text)
    client_secret_enc: Mapped[str | None] = mapped_column(Text)
    external_account_id: Mapped[str | None] = mapped_column(String(40))  # cTrader: ctidTraderAccountId
    broker_name: Mapped[str | None] = mapped_column(String(80))
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    key_last4: Mapped[str] = mapped_column(String(4))
    can_trade: Mapped[bool] = mapped_column(Boolean, default=False)
    ip_restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    credential_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("exchange_credentials.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(80))
    market: Mapped[Market] = mapped_column(_enum(Market), default=Market.crypto)
    symbol: Mapped[str] = mapped_column(String(20))  # ex.: BTCUSDT, EURUSD
    strategy: Mapped[str] = mapped_column(String(40))
    allow_short: Mapped[bool] = mapped_column(Boolean, default=False)  # opera vendido (forex)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    exec_mode: Mapped[ExecMode] = mapped_column(_enum(ExecMode), default=ExecMode.signals)
    venue: Mapped[Venue] = mapped_column(_enum(Venue), default=Venue.paper)
    status: Mapped[BotStatus] = mapped_column(_enum(BotStatus), default=BotStatus.stopped)
    status_reason: Mapped[str | None] = mapped_column(String(255))

    # Tamanho: cripto em moeda de cotação (ex.: USDT); forex em lotes.
    order_size_quote: Mapped[Decimal | None] = mapped_column(Qty)
    order_lots: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # Risco (valores em moeda da conta)
    stop_loss_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    take_profit_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    max_daily_loss_quote: Mapped[Decimal | None] = mapped_column(Qty)
    max_trades_per_day: Mapped[int] = mapped_column(Integer, default=10)

    # Simulação (venue = paper)
    paper_quote_balance: Mapped[Decimal] = mapped_column(Qty, default=Decimal("1000"))
    paper_base_balance: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))

    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("bot_id", name="uq_position_bot"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    side: Mapped[PosSide] = mapped_column(_enum(PosSide), default=PosSide.long)
    qty: Mapped[Decimal] = mapped_column(Qty)  # unidades do ativo (forex: unidades da moeda base)
    avg_price: Mapped[Decimal] = mapped_column(Qty)  # preço de entrada (referência de stop/alvo)
    cost_basis: Mapped[Decimal | None] = mapped_column(Qty)  # cripto à vista: total pago, com taxa
    entry_fee: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    external_id: Mapped[str | None] = mapped_column(String(40))  # cTrader: positionId
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    venue: Mapped[Venue] = mapped_column(_enum(Venue))
    client_order_id: Mapped[str] = mapped_column(String(36), unique=True)
    exchange_order_id: Mapped[str | None] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(20))
    side: Mapped[Side] = mapped_column(_enum(Side))
    qty: Mapped[Decimal] = mapped_column(Qty)
    price: Mapped[Decimal | None] = mapped_column(Qty)  # preço médio executado
    quote_qty: Mapped[Decimal | None] = mapped_column(Qty)
    fee_quote: Mapped[Decimal] = mapped_column(Qty, default=Decimal("0"))
    realized_pnl: Mapped[Decimal | None] = mapped_column(Qty)
    status: Mapped[OrderStatus] = mapped_column(_enum(OrderStatus), default=OrderStatus.new)
    reason: Mapped[str] = mapped_column(String(255), default="")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(20))
    side: Mapped[Side] = mapped_column(_enum(Side))
    ref_price: Mapped[Decimal] = mapped_column(Qty)
    reason: Mapped[str] = mapped_column(String(255))
    status: Mapped[SignalStatus] = mapped_column(_enum(SignalStatus), default=SignalStatus.pending)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    target: Mapped[str | None] = mapped_column(String(120))
    ip: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("provider", "topic", "resource_id", "request_id", name="uq_webhook_event"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(20))
    topic: Mapped[str] = mapped_column(String(60))
    resource_id: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str] = mapped_column(String(64))
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
