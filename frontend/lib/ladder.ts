/** Contas dos robôs de grade (Grid) e compra programada (DCA), iguais às do servidor (app/strategies/ladder.py). */

export type LadderParams = Record<string, string>;

const n = (v: string | undefined, d: number) => {
  const x = Number(v);
  return v === undefined || v === "" || !Number.isFinite(x) ? d : x;
};

export function gridLevels(lower: number, upper: number, grids: number, spacing: string): number[] {
  if (spacing === "arithmetic") return Array.from({ length: grids + 1 }, (_, i) => lower + ((upper - lower) / grids) * i);
  const ratio = (upper / lower) ** (1 / grids);
  return Array.from({ length: grids + 1 }, (_, i) => lower * ratio ** i);
}

/** Faixa, degrau e dinheiro necessário. `price` é o preço atual (para a faixa automática e a manual). */
export function gridPreview(p: LadderParams, size: number, price: number | null) {
  const grids = Math.max(2, Math.round(n(p.grids, 20)));
  const manual = p.range_mode === "manual";
  const anchor = price ?? 100;
  const lower = manual ? n(p.lower_price, 0) : anchor * (1 - n(p.lower_pct, 10) / 100);
  const upper = manual ? n(p.upper_price, 0) : anchor * (1 + n(p.upper_pct, 10) / 100);
  const valid = lower > 0 && upper > lower;
  const levels = valid ? gridLevels(lower, upper, grids, p.spacing ?? "geometric") : [];
  const steps = levels.slice(1).map((v, i) => (v / levels[i] - 1) * 100);
  const initial = valid && price !== null && p.initial_buy !== "false" && price >= lower ? levels.slice(0, -1).filter((l) => l >= price).length : null;
  return {
    grids,
    lower: valid && (manual || price !== null) ? lower : null,
    upper: valid && (manual || price !== null) ? upper : null,
    stepMin: steps.length ? Math.min(...steps) : null,
    stepMax: steps.length ? Math.max(...steps) : null,
    capital: grids * size,
    initial,
    initialCost: initial !== null ? initial * size : null,
    outside: valid && price !== null && (price < lower || price > upper),
  };
}

export function dcaPlan(p: LadderParams, size: number) {
  const max = Math.max(1, Math.round(n(p.max_orders, 6)));
  const vm = n(p.volume_mult, 1);
  const dev = n(p.deviation_pct, 1.5);
  const sm = n(p.step_mult, 1.2);
  const drop = (k: number) => dev * Array.from({ length: k }, (_, j) => sm ** j).reduce((a, b) => a + b, 0);
  const orders = Array.from({ length: max }, (_, k) => ({ k, quote: size * vm ** k, drop: k ? drop(k) : 0 }));
  return { orders, capital: orders.reduce((a, o) => a + o.quote, 0), lastDrop: orders[orders.length - 1].drop, byTime: p.trigger === "time" };
}

export function ladderCapital(code: string, p: LadderParams, size: number): number | null {
  if (code === "grade_spot") return gridPreview(p, size, null).capital;
  if (code === "dca_spot") return dcaPlan(p, size).capital;
  return null;
}
