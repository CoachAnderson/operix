export type Venue = "paper" | "testnet" | "live";
export type Market = "crypto" | "forex";
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
}

export interface Credential {
  id: string;
  label: string;
  exchange: "binance" | "ctrader";
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
  last_tick_at: string | null;
  created_at: string;
  user_id?: string;
}

export interface BotSummary {
  bot: Bot;
  position: { side: "long" | "short"; qty: string; avg_price: string; opened_at: string } | null;
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
  params_schema: {
    properties: Record<string, { type?: string; default?: unknown; minimum?: number; maximum?: number; title?: string; description?: string; enum?: string[]; anyOf?: unknown[] }>;
  };
}
