from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator, model_validator

from app.models import BotStatus, ExecMode, Market, OrderStatus, PosSide, Role, Side, SignalStatus, SubStatus, UserStatus, Venue
from app.services import b3
from app.strategies.filters import BotFilters


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Auth ----------
class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    accept_terms: bool

    @field_validator("password")
    @classmethod
    def strong(cls, v: str) -> str:
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            raise ValueError("A senha precisa ter letras e números")
        return v

    @field_validator("accept_terms")
    @classmethod
    def must_accept(cls, v: bool) -> bool:
        if not v:
            raise ValueError("É preciso aceitar os termos de uso")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)
    totp_code: str | None = None


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TotpCodeIn(BaseModel):
    code: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


class UserOut(ORM):
    id: uuid.UUID
    email: str
    name: str
    role: Role
    status: UserStatus
    totp_enabled: bool
    risk_terms_accepted_at: datetime | None
    created_at: datetime
    appearance: dict[str, Any] | None = None


HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
ColorKey = Literal["paper", "surface", "ink", "muted"]


class AppearanceColors(BaseModel):
    model_config = ConfigDict(extra="forbid")
    light: dict[ColorKey, HexColor] = Field(default_factory=dict)
    dark: dict[ColorKey, HexColor] = Field(default_factory=dict)


class AppearanceIn(BaseModel):
    """Aparência do painel. Só aceita valores conhecidos e cores #RRGGBB: o conteúdo vira CSS no navegador."""

    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = 1
    theme: Literal["auto", "light", "dark"] = "auto"
    palette: Literal["razao", "grafite", "oceano", "floresta", "areia", "oled"] = "razao"
    accent: HexColor | None = None
    font: Literal["schibsted", "inter", "atkinson", "plex", "serif", "system"] = "schibsted"
    scale: Literal[90, 100, 110, 120] = 100
    radius: Literal["square", "default", "round"] = "default"
    pnl: Literal["green-red", "blue-orange"] = "green-red"
    custom: AppearanceColors = Field(default_factory=AppearanceColors)


class AcceptRiskIn(BaseModel):
    version: str
    confirm: bool

    @field_validator("confirm")
    @classmethod
    def must_confirm(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Confirmação obrigatória")
        return v


# ---------- Planos e cobrança ----------
class PlanOut(ORM):
    id: uuid.UUID
    code: str
    name: str
    description: str
    price_monthly: Decimal
    max_bots: int
    allow_auto: bool
    allow_live: bool
    active: bool
    sort_order: int


class PlanIn(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9_-]{2,40}$")
    name: str = Field(min_length=2, max_length=80)
    description: str = ""
    price_monthly: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    max_bots: int = Field(ge=1, le=100)
    allow_auto: bool = False
    allow_live: bool = False
    active: bool = True
    sort_order: int = 0


class SubscriptionOut(ORM):
    id: uuid.UUID
    status: SubStatus
    plan: PlanOut
    next_payment_at: datetime | None
    created_at: datetime


class CheckoutIn(BaseModel):
    plan_id: uuid.UUID


class CheckoutOut(BaseModel):
    subscription_id: uuid.UUID
    checkout_url: str


# ---------- Credenciais ----------
class CredentialIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    venue: Venue
    api_key: str = Field(min_length=10, max_length=200)
    api_secret: str = Field(min_length=10, max_length=200)

    @field_validator("venue")
    @classmethod
    def no_paper(cls, v: Venue) -> Venue:
        if v == Venue.paper:
            raise ValueError("A simulação interna não usa credenciais")
        return v


class CTraderCredentialIn(BaseModel):
    """cTrader com o app do PRÓPRIO cliente (openapi.ctrader.com): Client ID/Secret + tokens da conta."""

    label: str = Field(min_length=1, max_length=80)
    client_id: str = Field(min_length=5, max_length=200)
    client_secret: str = Field(min_length=5, max_length=200)
    access_token: str = Field(min_length=10, max_length=500)
    refresh_token: str = Field(min_length=10, max_length=500)


class CredentialOut(ORM):
    id: uuid.UUID
    label: str
    exchange: str
    venue: Venue
    broker_name: str | None = None
    external_account_id: str | None = None
    key_last4: str
    can_trade: bool
    ip_restricted: bool
    verified_at: datetime | None
    created_at: datetime


# ---------- Robôs ----------
class BotIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    market: Market = Market.crypto
    symbol: str = Field(pattern=r"^[A-Z0-9]{3,20}$")
    strategy: str
    allow_short: bool = False
    params: dict[str, Any] = Field(default_factory=dict)
    exec_mode: ExecMode = ExecMode.signals
    venue: Venue = Venue.paper
    credential_id: uuid.UUID | None = None
    order_size_quote: Decimal | None = Field(default=None, gt=0, le=Decimal("1000000"))
    order_lots: Decimal | None = Field(default=None, gt=0, le=Decimal("100"), decimal_places=2)
    stop_loss_pct: Decimal | None = Field(default=None, gt=0, le=50)
    take_profit_pct: Decimal | None = Field(default=None, gt=0, le=500)
    max_daily_loss_quote: Decimal | None = Field(default=None, gt=0)
    max_trades_per_day: int = Field(default=10, ge=1, le=3000)
    paper_quote_balance: Decimal = Field(default=Decimal("1000"), gt=0, le=Decimal("10000000"))
    filters: BotFilters = Field(default_factory=BotFilters)
    sizing_mode: Literal["fixed", "risk"] = "fixed"
    risk_pct: Decimal | None = Field(default=None, gt=0, le=10)
    max_leverage: Decimal | None = Field(default=None, gt=0, le=500)

    @model_validator(mode="after")
    def check_market(self) -> BotIn:
        fixed = self.sizing_mode == "fixed"
        if not fixed:
            if not self.risk_pct:
                raise ValueError("Informe quanto do saldo arriscar por operação (ex.: 1%)")
            if not (self.stop_loss_pct or self.filters.stop_atr):
                raise ValueError("O tamanho pelo risco precisa de um stop (em % ou pelo ATR)")
        if self.market == Market.crypto:
            if fixed and not self.order_size_quote:
                raise ValueError("Informe o valor por ordem")
            if self.allow_short:
                raise ValueError("Cripto à vista não opera vendido")
            self.order_lots = None
        else:
            if fixed and not self.order_lots:
                raise ValueError("Informe o número de contratos" if self.market == Market.b3 else "Informe o tamanho em lotes (ex.: 0.01)")
            if self.market == Market.b3:
                b3.info(self.symbol)  # ValueError se o ativo não for liberado
                if self.order_lots is not None and self.order_lots != self.order_lots.to_integral_value():
                    raise ValueError("Na B3 o tamanho é em contratos inteiros (1, 2, 3…)")
            self.order_size_quote = None
        return self


class BotUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    allow_short: bool | None = None
    order_lots: Decimal | None = Field(default=None, gt=0, le=Decimal("100"), decimal_places=2)
    params: dict[str, Any] | None = None
    exec_mode: ExecMode | None = None
    venue: Venue | None = None
    credential_id: uuid.UUID | None = None
    order_size_quote: Decimal | None = Field(default=None, gt=0)
    stop_loss_pct: Decimal | None = Field(default=None, gt=0, le=50)
    take_profit_pct: Decimal | None = Field(default=None, gt=0, le=500)
    max_daily_loss_quote: Decimal | None = Field(default=None, gt=0)
    max_trades_per_day: int | None = Field(default=None, ge=1, le=3000)
    filters: BotFilters | None = None
    sizing_mode: Literal["fixed", "risk"] | None = None
    risk_pct: Decimal | None = Field(default=None, gt=0, le=10)
    max_leverage: Decimal | None = Field(default=None, gt=0, le=500)


class BotOut(ORM):
    id: uuid.UUID
    name: str
    market: Market
    symbol: str
    strategy: str
    allow_short: bool
    order_lots: Decimal | None
    params: dict[str, Any]
    exec_mode: ExecMode
    venue: Venue
    credential_id: uuid.UUID | None
    status: BotStatus
    status_reason: str | None
    order_size_quote: Decimal | None
    stop_loss_pct: Decimal | None
    take_profit_pct: Decimal | None
    max_daily_loss_quote: Decimal | None
    max_trades_per_day: int
    paper_quote_balance: Decimal
    paper_base_balance: Decimal
    filters: dict[str, Any] = Field(default_factory=dict)
    sizing_mode: str = "fixed"
    risk_pct: Decimal | None = None
    max_leverage: Decimal | None = None
    last_tick_at: datetime | None
    created_at: datetime


class PositionOut(ORM):
    side: PosSide
    qty: Decimal
    avg_price: Decimal
    stop_price: Decimal | None = None
    take_price: Decimal | None = None
    opened_at: datetime


class OrderOut(ORM):
    id: uuid.UUID
    bot_id: uuid.UUID
    venue: Venue
    symbol: str
    side: Side
    qty: Decimal
    price: Decimal | None
    quote_qty: Decimal | None
    fee_quote: Decimal
    realized_pnl: Decimal | None
    status: OrderStatus
    reason: str
    error: str | None
    created_at: datetime


class SignalOut(ORM):
    id: uuid.UUID
    bot_id: uuid.UUID
    symbol: str
    side: Side
    ref_price: Decimal
    reason: str
    status: SignalStatus
    expires_at: datetime
    created_at: datetime


class StrategyInfo(BaseModel):
    code: str
    name: str
    style: str  # day | swing
    description: str
    timeframe: str
    family: str  # trend | reversion (define o que o filtro de ADX exige)
    params_schema: dict[str, Any]
    trade_bars: int | None = None  # operação de duração fixa (em candles)
    suggested_max_trades_per_day: int | None = None
    notes: list[str] = []


class BotSummary(BaseModel):
    bot: BotOut
    position: PositionOut | None
    realized_pnl_today: Decimal
    realized_pnl_total: Decimal
    trades_today: int


# ---------- Admin ----------
class AdminUserOut(UserOut):
    last_login_at: datetime | None


class AdminUserUpdate(BaseModel):
    status: UserStatus | None = None
    role: Role | None = None


class AdminStats(BaseModel):
    users_total: int
    subscriptions_active: int
    mrr: Decimal
    bots_running: int
    bots_live: int
    orders_24h: int
    kill_switch: bool


class KillSwitchIn(BaseModel):
    enabled: bool
    reason: str = Field(default="", max_length=255)


class AuditOut(ORM):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    action: str
    target: str | None
    ip: str | None
    details: dict[str, Any]
    created_at: datetime
