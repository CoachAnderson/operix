"use client";

import type { StrategyInfo } from "@/lib/types";

export const PARAM_LABELS: Record<string, string> = {
  timeframe: "Tempo gráfico",
  fast: "Média rápida (períodos)",
  slow: "Média lenta (períodos)",
  period: "Períodos do RSI",
  oversold: "Nível de sobrevenda (compra)",
  exit_level: "Nível de saída (venda)",
  trend_ema: "Média de tendência (0 desliga)",
  entry_period: "Períodos para entrada",
  exit_period: "Períodos para saída",
  max_hold_minutes: "Tempo máximo posicionado (min)",
  min_majority: "Candles na mesma direção, entre os 5 (3 a 5)",
  bb_period: "Períodos da Banda de Bollinger",
  bb_std: "Largura da banda (desvios-padrão)",
  rsi_period: "Períodos do RSI",
  rsi_level: "RSI para entrar (compra abaixo dele)",
};
export const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];

export function defaultParams(s: StrategyInfo): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, prop] of Object.entries(s.params_schema.properties)) {
    if (prop.default !== undefined && prop.default !== null) out[k] = String(prop.default);
  }
  return out;
}

/** Converte os campos do formulário para o formato da API (números e timeframe). */
export function cleanParams(params: Record<string, string>): Record<string, string | number> {
  return Object.fromEntries(
    Object.entries(params)
      .filter(([, v]) => v !== "")
      .map(([k, v]) => [k, k === "timeframe" ? v : Number(v)]),
  );
}

export function StrategyParamsFields({
  strategy,
  params,
  onChange,
}: {
  strategy: StrategyInfo;
  params: Record<string, string>;
  onChange: (p: Record<string, string>) => void;
}) {
  return (
    <div className="grid-2">
      {Object.entries(strategy.params_schema.properties).map(([k, prop]) =>
        k === "timeframe" ? (
          <label key={k}>
            {PARAM_LABELS[k]}
            <select
              value={params[k] ?? ""}
              disabled={!!prop.const}
              title={prop.const ? "Esta estratégia só funciona neste tempo gráfico" : undefined}
              onChange={(e) => onChange({ ...params, [k]: e.target.value })}
            >
              {(prop.const ? [prop.const] : prop.enum ?? TIMEFRAMES).map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </label>
        ) : (
          <label key={k}>
            {PARAM_LABELS[k] ?? k}
            <input
              type="number"
              step="any"
              min={prop.minimum}
              max={prop.maximum}
              placeholder={k === "max_hold_minutes" ? "Padrão da estratégia" : undefined}
              value={params[k] ?? ""}
              onChange={(e) => onChange({ ...params, [k]: e.target.value })}
            />
          </label>
        ),
      )}
    </div>
  );
}
