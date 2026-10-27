export type Venue = "paper" | "testnet" | "live";
export type Market = "crypto" | "forex" | "b3";
export type ExecMode = "auto" | "signals";
export type BotStatus = "stopped" | "running" | "paused_risk" | "paused_billing" | "error";

export interface User {
  id: string;
  email: string;
  name: string;
  role: "subscriber" | "admin";
  status: "active" | "suspended" | "deleted";
  totp_enabled: boolean;
  risk_terms_accepted_at: string | null;
  created_at: string;
  last_login_at?: string | null;
  appearance?: Record<string, unknown> | null;
  access?: Access | null;
}

export interface Access {
  source: "admin" | "mercadopago" | "manual" | "none";
  plan_name: string | null;
  expires_at: string | null;
  subscription_id: string | null;
}

export interface Plan {
  id: string;
  code: string;
  name: string;
  description: string;
  price_monthly: string;
  max_bots: number;
  allow_auto: boolean;
  allow_live: boolean;
  active: boolean;
}

export interface Subscription {
  id: string;
  status: "pending" | "active" | "paused" | "past_due" | "cancelled";
  plan: Plan;
  next_payment_at: string | null;
  created_at: string;
  expires_at?: string | null;
  source?: "mercadopago" | "manual" | "admin";
}

export interface Credential {
  id: string;
  label: string;
  exchange: "binance" | "ctrader" | "mt5";
  venue: Venue;
  broker_name: string | null;
  external_account_id: string | null;
  key_last4: string;
  can_trade: boolean;
  ip_restricted: boolean;
  verified_at: string | null;
}

export interface Bot {
  id: string;
  name: string;
  market: Market;
  symbol: string;
  strategy: string;
  allow_short: boolean;
  order_lots: string | null;
  params: Record<string, unknown>;
  exec_mode: ExecMode;
  venue: Venue;
  credential_id: string | null;
  status: BotStatus;
  status_reason: string | null;
  order_size_quote: string | null;
  stop_loss_pct: string | null;
  take_profit_pct: string | null;
  max_daily_loss_quote: string | null;
  max_trades_per_day: number;
  paper_quote_balance: string;
  paper_base_balance: string;
  filters: BotFilters;
  sizing_mode: "fixed" | "risk";
  risk_pct: string | null;
  max_leverage: string | null;
  last_tick_at: string | null;
  created_at: string;
  user_id?: string;
}

export interface BotSummary {
  bot: Bot;
  position: { side: "long" | "short"; qty: string; avg_price: string; stop_price: string | null; take_price: string | null; opened_at: string } | null;
  realized_pnl_today: string;
  realized_pnl_total: string;
  trades_today: number;
}

export interface Order {
  id: string;
  bot_id: string;
  venue: Venue;
  symbol: string;
  side: "BUY" | "SELL";
  qty: string;
  price: string | null;
  quote_qty: string | null;
  fee_quote: string;
  realized_pnl: string | null;
  status: string;
  reason: string;
  error: string | null;
  created_at: string;
}

export interface Signal {
  id: string;
  bot_id: string;
  symbol: string;
  side: "BUY" | "SELL";
  ref_price: string;
  reason: string;
  status: "pending" | "executed" | "dismissed" | "expired" | "failed";
  expires_at: string;
  created_at: string;
}

export interface StrategyInfo {
  code: string;
  name: string;
  style: "day" | "swing";
  description: string;
  timeframe: string;
  family: "trend" | "reversion";
  params_schema: {
    properties: Record<string, { type?: string; default?: unknown; minimum?: number; maximum?: number; title?: string; description?: string; enum?: string[]; const?: string; anyOf?: unknown[] }>;
  };
  trade_bars?: number | null;
  suggested_max_trades_per_day?: number | null;
  notes?: string[];
  kind?: "signal" | "ladder";
}

export interface ReportSymbol {
  symbol: string;
  market: Market;
  open: boolean;
  open_sides: ("long" | "short")[];
  bots: number;
}

export interface Mt5Status {
  credential_id: string;
  online: boolean;
  last_seen: string | null;
  account: { login: number; server: string; company: string; name: string; currency: string; trade_mode: number; trade_allowed: boolean } | null;
  terminal: { trade_allowed: boolean; connected: boolean; build: number | null } | null;
  limits: { roots: string[]; max_contracts: number } | null;
  agent_version: string | null;
}

/** Filtros de entrada e stop/alvo pelo ATR (campos ausentes = padrão do servidor). */
export interface BotFilters {
  regime?: boolean;
  adx_period?: number;
  adx_level?: number;
  htf?: string | null;
  htf_ema?: number;
  hours_start?: string | null;
  hours_end?: string | null;
  atr_period?: number;
  atr_min_pct?: number | null;
  atr_max_pct?: number | null;
  stop_atr?: number | null;
  take_atr?: number | null;
}

/** Prévia do tamanho da próxima entrada (POST /bots/sizing-preview ou GET /bots/{id}/sizing-preview). */
export interface SizingPreview {
  ok: boolean;
  message?: string;
  currency?: string;
  unit?: string | null; // "lotes" | "contratos" | null (cripto)
  units?: string | null;
  quote_amount?: string | null;
  price?: string;
  notional?: string;
  balance?: string | null;
  leverage?: string | null;
  stop?: string | null;
  risk_money?: string | null;
  risk_pct?: string | null;
  lots?: string | null;
  capped?: boolean;
  note?: string;
}
