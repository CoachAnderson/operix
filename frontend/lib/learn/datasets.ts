import { generate, type Candle } from "./market";

/** Conjuntos de dados fictícios usados nas aulas. Sementes escolhidas para ilustrar cada ideia com clareza. */
const cache = new Map<string, Candle[]>();
function memo(key: string, make: () => Candle[]): Candle[] {
  if (!cache.has(key)) cache.set(key, make());
  return cache.get(key)!;
}

export type RegimeName = "alta" | "lateral" | "queda";

export const REGIME_LABEL: Record<RegimeName, string> = {
  alta: "Tendência de alta",
  lateral: "Mercado lateral",
  queda: "Tendência de queda",
};

export function regime(name: RegimeName): Candle[] {
  return memo(`regime-${name}`, () => {
    const seed = 133;
    if (name === "alta") return generate(seed, [{ n: 160, drift: 0.0025, vol: 0.015 }]);
    if (name === "queda") return generate(seed, [{ n: 160, drift: -0.0025, vol: 0.015 }]);
    return generate(seed, [{ n: 160, drift: 0, vol: 0.012, pull: 0.25, wave: 0.07, period: 32 }]);
  });
}

/** Alta, depois lateral, depois queda: mostra onde cada estratégia acerta e erra. */
export function mixed(): Candle[] {
  return memo("mixed", () =>
    generate(21, [
      { n: 80, drift: 0.004, vol: 0.013 },
      { n: 70, drift: 0, vol: 0.012, pull: 0.25, wave: 0.05, period: 24 },
      { n: 70, drift: -0.004, vol: 0.013 },
    ]),
  );
}

/** Candles de 1 hora (para a aula de tempo gráfico). */
export function hourly(): Candle[] {
  return memo("hourly", () =>
    generate(7, [
      { n: 96, drift: 0.0012, vol: 0.006 },
      { n: 72, drift: 0, vol: 0.005, pull: 0.2, wave: 0.02, period: 20 },
      { n: 72, drift: 0.0015, vol: 0.006 },
    ]),
  );
}

/** Série curta para a aula de candle e de médias. */
export function short(): Candle[] {
  return memo("short", () =>
    generate(42, [
      { n: 40, drift: 0.003, vol: 0.012 },
      { n: 30, drift: -0.003, vol: 0.014 },
      { n: 40, drift: 0.002, vol: 0.012 },
    ]),
  );
}

/** Mercado que lateraliza e depois dispara: o caso clássico do rompimento. */
export function breakoutSeries(): Candle[] {
  return memo("breakout", () =>
    generate(11, [
      { n: 70, drift: 0, vol: 0.01, pull: 0.3, wave: 0.03, period: 22 },
      { n: 60, drift: 0.0045, vol: 0.012 },
      { n: 50, drift: 0, vol: 0.012, pull: 0.25, wave: 0.04, period: 20 },
      { n: 40, drift: -0.004, vol: 0.013 },
    ]),
  );
}
