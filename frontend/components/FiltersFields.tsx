"use client";

import type { BotFilters } from "@/lib/types";

const TF_MS: Record<string, number> = { "1m": 60e3, "5m": 300e3, "15m": 900e3, "30m": 1800e3, "1h": 3600e3, "4h": 14400e3, "1d": 86400e3 };
const TF_LABEL: Record<string, string> = { "1m": "1 minuto", "5m": "5 minutos", "15m": "15 minutos", "30m": "30 minutos", "1h": "1 hora", "4h": "4 horas", "1d": "Diário" };

/** Tempos gráficos maiores e múltiplos do da estratégia (ex.: 5m → 15m, 30m, 1h, 4h, 1d). */
export function higherTimeframes(tf: string): string[] {
  return Object.keys(TF_MS).filter((k) => TF_MS[k] > TF_MS[tf] && TF_MS[k] % TF_MS[tf] === 0);
}

/** Quantos filtros estão ligados (para o resumo). */
export function activeFilters(f: BotFilters): string[] {
  const on: string[] = [];
  if (f.regime) on.push("tipo de mercado (ADX)");
  if (f.htf) on.push(`confirmação no ${TF_LABEL[f.htf]?.toLowerCase() ?? f.htf}`);
  if (f.hours_start && f.hours_end) on.push(`horário ${f.hours_start}–${f.hours_end}`);
  if (f.atr_min_pct || f.atr_max_pct) on.push("volatilidade");
  if (f.stop_atr || f.take_atr) on.push("stop/alvo pelo ATR");
  return on;
}

/** Remove campos vazios antes de enviar ao servidor. */
export function cleanFilters(f: BotFilters): BotFilters {
  const out: BotFilters = {};
  if (f.regime) Object.assign(out, { regime: true, adx_level: f.adx_level ?? 20 });  // o componente já põe 30 para reversão
  if (f.htf) Object.assign(out, { htf: f.htf, htf_ema: f.htf_ema ?? 50 });
  if (f.hours_start && f.hours_end) Object.assign(out, { hours_start: f.hours_start, hours_end: f.hours_end });
  if (f.atr_min_pct) out.atr_min_pct = f.atr_min_pct;
  if (f.atr_max_pct) out.atr_max_pct = f.atr_max_pct;
  if (f.stop_atr) out.stop_atr = f.stop_atr;
  if (f.take_atr) out.take_atr = f.take_atr;
  return out;
}

function num(v: string): number | null {
  const n = Number(v.replace(",", "."));
  return v.trim() === "" || Number.isNaN(n) ? null : n;
}

function Toggle({ on, onChange, title, hint, children }: { on: boolean; onChange: (v: boolean) => void; title: string; hint: string; children?: React.ReactNode }) {
  return (
    <div className={`flt ${on ? "on" : ""}`}>
      <label className="check flt-head">
        <input type="checkbox" checked={on} onChange={(e) => onChange(e.target.checked)} />
        <span>
          <strong>{title}</strong>
          <span className="hint">{hint}</span>
        </span>
      </label>
      {on && children && <div className="flt-body">{children}</div>}
    </div>
  );
}

/**
 * Filtros que melhoram a qualidade das entradas. Só barram ENTRADAS; saídas nunca são bloqueadas.
 * `family` vem da estratégia: tendência precisa de mercado direcional; reversão, de mercado lateral.
 */
export function FiltersFields({
  value,
  onChange,
  timeframe,
  family,
  open = false,
}: {
  value: BotFilters;
  onChange: (f: BotFilters) => void;
  timeframe: string;
  family: "trend" | "reversion";
  open?: boolean;
}) {
  const set = (patch: BotFilters) => onChange({ ...value, ...patch });
  const htfs = higherTimeframes(timeframe);
  const on = activeFilters(value);

  return (
    <details className="flt-box" open={open || on.length > 0}>
      <summary>
        <strong>Filtros de entrada</strong>
        <span className="muted small">{on.length ? `Ligados: ${on.join(", ")}` : "Nenhum ligado. Filtros barram entradas ruins; as saídas nunca são bloqueadas."}</span>
      </summary>

      <Toggle
        on={!!value.regime}
        onChange={(v) => set({ regime: v, adx_level: value.adx_level ?? (family === "reversion" ? 30 : 20) })}
        title="Só operar no tipo de mercado certo (ADX)"
        hint={
          family === "trend"
            ? "Esta estratégia segue tendência: só entra quando o ADX mostra tendência (fica parada no mercado lateral)."
            : "Esta estratégia é de reversão: só entra sem tendência forte. Atenção: nos testes com dados reais, para reversão a confirmação no tempo gráfico maior funcionou melhor que o ADX."
        }
      >
        <label>
          Nível do ADX
          <span className="hint">{family === "trend" ? "Entra com ADX acima disso. 20 a 25 é o usual." : "Entra com ADX abaixo disso. Para reversão use 30 ou mais: o RSI só fica baixo depois de uma queda forte, que já sobe o ADX."}</span>
          <input type="number" min="10" max="50" step="1" value={value.adx_level ?? (family === "reversion" ? 30 : 20)} onChange={(e) => set({ adx_level: num(e.target.value) ?? 20 })} />
        </label>
      </Toggle>

      <Toggle
        on={!!value.htf}
        onChange={(v) => set({ htf: v ? htfs[Math.min(2, htfs.length - 1)] ?? null : null, htf_ema: value.htf_ema ?? 50 })}
        title="Confirmar no tempo gráfico maior"
        hint="Só compra se, no gráfico maior, o preço estiver acima da média; só vende se estiver abaixo. Foi o filtro mais consistente nos testes com dados reais."
      >
        {htfs.length ? (
          <div className="grid-2">
            <label>
              Tempo gráfico de confirmação
              <select value={value.htf ?? ""} onChange={(e) => set({ htf: e.target.value })}>
                {htfs.map((t) => (
                  <option key={t} value={t}>
                    {TF_LABEL[t]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Média de
              <input type="number" min="5" max="200" step="1" value={value.htf_ema ?? 50} onChange={(e) => set({ htf_ema: num(e.target.value) ?? 50 })} />
            </label>
          </div>
        ) : (
          <p className="muted small">Não há tempo gráfico maior que o diário.</p>
        )}
      </Toggle>

      <Toggle
        on={!!(value.hours_start || value.hours_end)}
        onChange={(v) => set(v ? { hours_start: "09:30", hours_end: "17:00" } : { hours_start: null, hours_end: null })}
        title="Horário de entrada"
        hint="Evita a abertura agitada e horários de notícia. Horário de Brasília."
      >
        <div className="grid-2">
          <label>
            Das
            <input type="time" required value={value.hours_start ?? ""} onChange={(e) => set({ hours_start: e.target.value })} />
          </label>
          <label>
            Às
            <input type="time" required value={value.hours_end ?? ""} onChange={(e) => set({ hours_end: e.target.value })} />
          </label>
        </div>
      </Toggle>

      <Toggle
        on={!!(value.atr_min_pct || value.atr_max_pct)}
        onChange={(v) => set(v ? { atr_min_pct: 0.2, atr_max_pct: null } : { atr_min_pct: null, atr_max_pct: null })}
        title="Filtro de volatilidade (ATR)"
        hint="Não entra com o mercado parado demais (o custo come o ganho) nem agitado demais."
      >
        <div className="grid-2">
          <label>
            Mínimo (% do preço)
            <span className="hint">Tamanho médio dos candles.</span>
            <input type="number" min="0" step="0.01" value={value.atr_min_pct ?? ""} onChange={(e) => set({ atr_min_pct: num(e.target.value) })} />
          </label>
          <label>
            Máximo (% do preço)
            <span className="hint">Vazio = sem máximo.</span>
            <input type="number" min="0" step="0.01" value={value.atr_max_pct ?? ""} onChange={(e) => set({ atr_max_pct: num(e.target.value) })} />
          </label>
        </div>
      </Toggle>

      <Toggle
        on={!!(value.stop_atr || value.take_atr)}
        onChange={(v) => set(v ? { stop_atr: 1.5, take_atr: 3 } : { stop_atr: null, take_atr: null })}
        title="Stop e alvo pelo ATR"
        hint="A distância acompanha a agitação do mercado: maior em dias nervosos, menor em dias calmos. Substitui os percentuais."
      >
        <div className="grid-2">
          <label>
            Stop a quantos ATR
            <span className="hint">1,5 a 2 é o usual. Vazio usa o stop em %.</span>
            <input type="number" min="0.3" max="10" step="0.1" value={value.stop_atr ?? ""} onChange={(e) => set({ stop_atr: num(e.target.value) })} />
          </label>
          <label>
            Alvo a quantos ATR
            <span className="hint">O dobro do stop é um bom começo. Vazio usa o alvo em %.</span>
            <input type="number" min="0.3" max="30" step="0.1" value={value.take_atr ?? ""} onChange={(e) => set({ take_atr: num(e.target.value) })} />
          </label>
        </div>
      </Toggle>
    </details>
  );
}
