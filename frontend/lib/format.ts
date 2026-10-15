import type { BotStatus, Market, Venue } from "./types";

const num = (v: string | number | null | undefined) => (v === null || v === undefined ? NaN : Number(v));

export function money(v: string | number | null | undefined, digits = 2): string {
  const n = num(v);
  if (Number.isNaN(n)) return "—";
  return n.toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Preço com casas proporcionais ao valor (BTC 2 casas, moedas baratas mais casas). */
export function price(v: string | number | null | undefined): string {
  const n = num(v);
  if (Number.isNaN(n)) return "—";
  const digits = n >= 100 ? 2 : n >= 1 ? 4 : 6;
  return money(n, digits);
}

export function brl(v: string | number): string {
  return num(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

export function qty(v: string | number | null | undefined): string {
  const n = num(v);
  if (Number.isNaN(n)) return "—";
  return n.toLocaleString("pt-BR", { maximumFractionDigits: 8 });
}

export function signed(v: string | number | null | undefined): string {
  const n = num(v);
  if (Number.isNaN(n)) return "—";
  return `${n > 0 ? "+" : ""}${money(n)}`;
}

export function pnlClass(v: string | number | null | undefined): string {
  const n = num(v);
  return n > 0 ? "gain" : n < 0 ? "loss" : "";
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function date(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("pt-BR");
}

export const VENUE_LABEL: Record<Venue, string> = {
  paper: "Simulação",
  testnet: "Testnet",
  live: "Conta real",
};

/** No forex o ambiente de teste é a conta demo da corretora. */
export function venueLabel(venue: Venue, market: Market = "crypto"): string {
  return market !== "crypto" && venue === "testnet" ? "Conta demo" : VENUE_LABEL[venue];
}

export const MARKET_LABEL: Record<Market, string> = { crypto: "Cripto (Binance)", forex: "Forex (cTrader)", b3: "Futuros B3 (MetaTrader 5)" };

/** Reais por ponto por contrato (o motor guarda a posição em "pontos × valor do ponto"). */
export const B3_POINT_VALUE: Record<string, number> = { WIN: 0.2, WDO: 10 };

export const VENUE_HINT: Record<Venue, string> = {
  paper: "Preços reais, saldo fictício. Nada sai da sua conta.",
  testnet: "Ambiente de testes da Binance, com saldo de teste.",
  live: "Ordens reais na sua conta Binance.",
};

export const STATUS_LABEL: Record<BotStatus, string> = {
  running: "Rodando",
  stopped: "Parado",
  paused_risk: "Pausado pelo limite de perda",
  paused_billing: "Pausado: assinatura",
  error: "Precisa de atenção",
};

export const MODE_LABEL = { auto: "Automático", signals: "Sinais" } as const;
