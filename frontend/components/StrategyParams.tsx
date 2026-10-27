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
  // Grid à vista
  range_mode: "Faixa de preço",
  lower_pct: "Piso: % abaixo do preço de partida",
  upper_pct: "Teto: % acima do preço de partida",
  lower_price: "Preço do piso",
  upper_price: "Preço do teto",
  grids: "Número de grades (lotes)",
  spacing: "Espaçamento dos níveis",
  initial_buy: "Na partida, comprar os lotes das grades acima do preço",
  stop_below_pct: "Stop: % abaixo do piso",
  // Compra programada (DCA)
  trigger: "Novas compras",
  deviation_pct: "Queda para a 2ª compra (%)",
  step_mult: "Multiplicador da queda",
  interval_hours: "Horas entre as compras",
  max_orders: "Máximo de compras por ciclo",
  volume_mult: "Multiplicador do valor",
  take_profit_pct: "Alvo sobre o custo médio (%)",
  stop_loss_pct: "Stop abaixo do custo médio (%)",
  restart: "Começar outro ciclo depois do alvo",
  cooldown_minutes: "Espera entre ciclos (min)",
};

const ENUM_LABELS: Record<string, string> = {
  auto: "Em % do preço na partida",
  manual: "Preços fixos",
  geometric: "Degraus em % iguais",
  arithmetic: "Degraus de preço iguais",
  drop: "A cada queda do preço",
  time: "A cada intervalo de tempo",
};

const HINTS: Record<string, string> = {
  grids: "Cada grade é um lote do valor por ordem. Mais grades = degraus menores.",
  stop_below_pct: "Vende todos os lotes e para o robô. Vazio desliga.",
  deviation_pct: "Quanto o preço precisa cair, desde a 1ª compra, para a 2ª compra.",
  step_mult: "1,2 = cada queda exigida é 20% maior que a anterior (2%, 2,4%, 2,88%…).",
  volume_mult: "1 = todas as compras do mesmo valor. Acima de 1, cada compra aumenta (o ciclo fica caro rápido).",
  take_profit_pct: "Vende tudo quando o preço passa o custo médio do ciclo mais isso. A taxa da venda sai do lucro.",
  stop_loss_pct: "Vende tudo e para o robô. Vazio desliga.",
};

/** Campos que só valem em um modo (ex.: preços fixos só na faixa manual). */
function hidden(k: string, p: Record<string, string>): boolean {
  if (k === "lower_pct" || k === "upper_pct") return p.range_mode === "manual";
  if (k === "lower_price" || k === "upper_price") return p.range_mode !== "manual";
  if (k === "deviation_pct" || k === "step_mult") return p.trigger === "time";
  if (k === "interval_hours") return p.trigger !== "time";
  if (k === "cooldown_minutes") return p.restart === "false";
  return false;
}

export const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];

type Prop = StrategyInfo["params_schema"]["properties"][string];

/** Campo opcional (anyOf com null) vira o tipo não nulo, mantendo o padrão. */
function resolve(prop: Prop): Prop & { nullable?: boolean } {
  if (!prop.anyOf) return prop;
  const inner = (prop.anyOf as Prop[]).find((x) => x.type !== "null") ?? {};
  return { ...inner, default: prop.default, description: prop.description, nullable: true };
}

export function defaultParams(s: StrategyInfo): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, prop] of Object.entries(s.params_schema.properties)) {
    if (prop.default !== undefined && prop.default !== null) out[k] = String(prop.default);
  }
  return out;
}

/** Converte os campos do formulário para o formato da API (números, sim/não e textos). */
export function cleanParams(params: Record<string, string>): Record<string, string | number | boolean> {
  return Object.fromEntries(
    Object.entries(params)
      .filter(([k, v]) => v !== "" && !hidden(k, params))
      .map(([k, v]) => [k, v === "true" ? true : v === "false" ? false : k === "timeframe" || !/^-?\d+(\.\d+)?(e-?\d+)?$/i.test(v) ? v : Number(v)]),
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
  const entries = Object.entries(strategy.params_schema.properties).filter(([k]) => !hidden(k, params));
  const checks = entries.filter(([, p]) => resolve(p).type === "boolean");
  const fields = entries.filter(([, p]) => resolve(p).type !== "boolean");
  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div className="grid-2">
        {fields.map(([k, raw]) => {
          const prop = resolve(raw);
          if (k === "timeframe")
            return (
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
            );
          if (prop.enum)
            return (
              <label key={k}>
                {PARAM_LABELS[k] ?? k}
                <select value={params[k] ?? ""} onChange={(e) => onChange({ ...params, [k]: e.target.value })}>
                  {prop.enum.map((t) => (
                    <option key={t} value={t}>
                      {ENUM_LABELS[t] ?? t}
                    </option>
                  ))}
                </select>
              </label>
            );
          return (
            <label key={k}>
              {PARAM_LABELS[k] ?? k}
              {HINTS[k] && <span className="hint">{HINTS[k]}</span>}
              <input
                type="number"
                step="any"
                min={prop.minimum}
                max={prop.maximum}
                required={(k === "lower_price" || k === "upper_price") && params.range_mode === "manual"}
                placeholder={k === "max_hold_minutes" ? "Padrão da estratégia" : prop.nullable ? "Desligado" : undefined}
                value={params[k] ?? ""}
                onChange={(e) => onChange({ ...params, [k]: e.target.value })}
              />
            </label>
          );
        })}
      </div>
      {checks.map(([k]) => (
        <label key={k} className="check">
          <input type="checkbox" checked={params[k] === "true"} onChange={(e) => onChange({ ...params, [k]: String(e.target.checked) })} /> {PARAM_LABELS[k] ?? k}
        </label>
      ))}
    </div>
  );
}
