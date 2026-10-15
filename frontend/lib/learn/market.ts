/**
 * Dados fictícios e indicadores para as aulas da área Aprender.
 * Tudo é determinístico (semente fixa), para que a aula mostre sempre o mesmo gráfico.
 */

export interface Candle {
  o: number;
  h: number;
  l: number;
  c: number;
}

export interface Regime {
  n: number; // quantidade de candles
  drift: number; // tendência média por candle (0,002 = +0,2%)
  vol: number; // oscilação típica por candle
  pull?: number; // força de volta ao centro (mercado lateral)
  wave?: number; // amplitude das ondas do lateral (0,06 = ±6%)
  period?: number; // candles por onda
}

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gaussian(rand: () => number): number {
  const u = Math.max(rand(), 1e-9);
  const v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/** Gera candles a partir de uma sequência de regimes (alta, lateral, queda...). */
export function generate(seed: number, regimes: Regime[], start = 100): Candle[] {
  const rand = mulberry32(seed);
  const out: Candle[] = [];
  let price = start;
  for (const r of regimes) {
    const anchor = price;
    for (let i = 0; i < r.n; i++) {
      const o = price;
      const center = r.wave ? anchor * (1 + r.wave * Math.sin((2 * Math.PI * i) / (r.period ?? 30))) : anchor;
      const pull = r.pull ? (r.pull * (center - o)) / anchor : 0;
      const c = Math.max(0.01, o * (1 + r.drift + pull + r.vol * gaussian(rand)));
      const h = Math.max(o, c) * (1 + Math.abs(gaussian(rand)) * r.vol * 0.55);
      const l = Math.min(o, c) * (1 - Math.abs(gaussian(rand)) * r.vol * 0.55);
      const r4 = (v: number) => Math.round(v * 1e4) / 1e4;
      out.push({ o: r4(o), h: r4(h), l: r4(l), c: r4(c) });
      price = c;
    }
  }
  return out;
}

/** Junta candles de k em k (ex.: quatro de 1 hora viram um de 4 horas). */
export function aggregate(candles: Candle[], k: number): Candle[] {
  const out: Candle[] = [];
  for (let i = 0; i + k <= candles.length; i += k) {
    const g = candles.slice(i, i + k);
    out.push({ o: g[0].o, c: g[g.length - 1].c, h: Math.max(...g.map((x) => x.h)), l: Math.min(...g.map((x) => x.l)) });
  }
  return out;
}

export type Series = (number | null)[];

/** Média móvel exponencial. Começa na média simples dos primeiros n valores. */
export function ema(values: number[], n: number): Series {
  const out: Series = values.map(() => null);
  if (values.length < n) return out;
  const k = 2 / (n + 1);
  let prev = values.slice(0, n).reduce((a, b) => a + b, 0) / n;
  out[n - 1] = prev;
  for (let i = n; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

/** Média móvel simples. */
export function sma(values: number[], n: number): Series {
  return values.map((_, i) => (i < n - 1 ? null : values.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0) / n));
}

/** RSI de Wilder (0 a 100). */
export function rsi(values: number[], n = 14): Series {
  const out: Series = values.map(() => null);
  if (values.length <= n) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= n; i++) {
    const d = values[i] - values[i - 1];
    if (d >= 0) gain += d;
    else loss -= d;
  }
  gain /= n;
  loss /= n;
  out[n] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  for (let i = n + 1; i < values.length; i++) {
    const d = values[i] - values[i - 1];
    gain = (gain * (n - 1) + Math.max(d, 0)) / n;
    loss = (loss * (n - 1) + Math.max(-d, 0)) / n;
    out[i] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  }
  return out;
}

/** Canal de Donchian: máxima e mínima dos n candles ANTERIORES (o candle atual pode romper). */
export function donchian(candles: Candle[], n: number): { upper: Series; lower: Series } {
  const upper: Series = [];
  const lower: Series = [];
  candles.forEach((_, i) => {
    if (i < n) {
      upper.push(null);
      lower.push(null);
      return;
    }
    const g = candles.slice(i - n, i);
    upper.push(Math.max(...g.map((x) => x.h)));
    lower.push(Math.min(...g.map((x) => x.l)));
  });
  return { upper, lower };
}

// ---------------- mini-backtests didáticos ----------------
export interface Trade {
  entry: number; // índice do candle
  exit: number;
  entryPrice: number;
  exitPrice: number;
  pct: number; // resultado em %, já com custo
}

export interface Result {
  trades: Trade[];
  totalPct: number; // soma composta
  wins: number;
}

/** Custo por operação completa (entrada + saída), em %. */
export const DEFAULT_COST = 0.2;

function run(candles: Candle[], wantLong: (i: number, inPos: boolean) => boolean | null, cost = DEFAULT_COST): Result {
  const trades: Trade[] = [];
  let entry = -1;
  for (let i = 0; i < candles.length; i++) {
    const want = wantLong(i, entry >= 0);
    if (want === null) continue;
    if (want && entry < 0) entry = i;
    else if (!want && entry >= 0) {
      const ep = candles[entry].c;
      const xp = candles[i].c;
      trades.push({ entry, exit: i, entryPrice: ep, exitPrice: xp, pct: (xp / ep - 1) * 100 - cost });
      entry = -1;
    }
  }
  if (entry >= 0) {
    const last = candles.length - 1;
    const ep = candles[entry].c;
    const xp = candles[last].c;
    trades.push({ entry, exit: last, entryPrice: ep, exitPrice: xp, pct: (xp / ep - 1) * 100 - cost });
  }
  const totalPct = (trades.reduce((acc, t) => acc * (1 + t.pct / 100), 1) - 1) * 100;
  return { trades, totalPct, wins: trades.filter((t) => t.pct > 0).length };
}

/** Comprado enquanto a média rápida estiver acima da lenta. */
export function emaCross(candles: Candle[], fast: number, slow: number, cost = DEFAULT_COST): Result & { fast: Series; slow: Series } {
  const closes = candles.map((c) => c.c);
  const f = ema(closes, fast);
  const s = ema(closes, slow);
  const r = run(candles, (i) => (f[i] === null || s[i] === null ? null : (f[i] as number) > (s[i] as number)), cost);
  return { ...r, fast: f, slow: s };
}

/** Compra quando o RSI cai abaixo de "oversold"; vende quando passa de "exitLevel". */
export function rsiReversion(candles: Candle[], period: number, oversold: number, exitLevel: number, cost = DEFAULT_COST): Result & { rsi: Series } {
  const r = rsi(
    candles.map((c) => c.c),
    period,
  );
  const res = run(
    candles,
    (i, inPos) => {
      const v = r[i];
      if (v === null) return null;
      if (!inPos) return v < oversold ? true : null;
      return v > exitLevel ? false : null;
    },
    cost,
  );
  return { ...res, rsi: r };
}

/** Compra no fechamento acima da máxima de "entryN"; sai abaixo da mínima de "exitN". */
export function breakout(candles: Candle[], entryN: number, exitN: number, cost = DEFAULT_COST): Result & { upper: Series; lower: Series; exitLower: Series } {
  const ch = donchian(candles, entryN);
  const ex = donchian(candles, exitN);
  const res = run(
    candles,
    (i, inPos) => {
      const up = ch.upper[i];
      const lo = ex.lower[i];
      if (up === null || lo === null) return null;
      if (!inPos) return candles[i].c > up ? true : null;
      return candles[i].c < lo ? false : null;
    },
    cost,
  );
  return { ...res, upper: ch.upper, lower: ch.lower, exitLower: ex.lower };
}

/** Comprar no primeiro candle e segurar até o último. */
export function buyAndHold(candles: Candle[]): number {
  return (candles[candles.length - 1].c / candles[0].c - 1) * 100;
}

// ---------------- formatação ----------------
export function pct(v: number, digits = 1): string {
  const s = Math.abs(v).toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${s}%`;
}

export function num(v: number, digits = 2): string {
  return v.toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export { mulberry32 };
