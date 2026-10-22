"use client";

import { money, pnlClass } from "@/lib/format";

export interface Segment {
  label: string;
  start: number;
  end: number;
  trades: number;
  win_rate_pct: number;
  payoff: number | null;
  profit_factor: number | null;
  expectancy_pct: number;
  return_pct: number;
  buy_hold_pct: number;
  max_drawdown_pct: number;
  net_pnl: number;
}

export interface CompareMetrics {
  trades: number;
  win_rate_pct: number;
  payoff: number | null;
  profit_factor: number | null;
  return_pct: number;
  max_drawdown_pct: number;
  expectancy_pct: number;
}

const pct = (v: number) => `${v > 0 ? "+" : ""}${money(v)}%`;
const opt = (v: number | null) => (v === null ? "—" : money(v));
const day = (ms: number) => new Date(ms).toLocaleDateString("pt-BR");
const pf = (v: number | null) => (v === null ? 0 : v);

/** Ajuste × confirmação: a estratégia continua boa no trecho que não foi usado para ajustar? */
function splitVerdict(a: Segment, c: Segment): { tone: "" | "gain" | "loss"; text: string } {
  if (c.trades < 10)
    return { tone: "", text: `Só ${c.trades} operações no período de confirmação: pouco para concluir. Aumente o período ou a parte de confirmação.` };
  const okA = pf(a.profit_factor) >= 1;
  const okC = pf(c.profit_factor) >= 1;
  if (okA && okC) {
    const drop = a.win_rate_pct - c.win_rate_pct;
    return drop > 15
      ? { tone: "", text: `Ganhou nos dois trechos, mas o acerto caiu ${money(drop, 0)} pontos na confirmação. Vale testar outros períodos antes de confiar.` }
      : { tone: "gain", text: "Os números se mantiveram no período de confirmação, que não foi usado para ajustar. Bom sinal (não é garantia)." };
  }
  if (okA && !okC)
    return { tone: "loss", text: "Funcionou no período de ajuste e falhou na confirmação: sinal de excesso de ajuste. Não leve para a conta real assim." };
  if (!okA && okC)
    return { tone: "", text: "Perdeu no ajuste e ganhou na confirmação: provavelmente sorte daquele trecho. Teste um período maior." };
  return { tone: "loss", text: "Perdeu nos dois trechos. Mude a estratégia, o tempo gráfico ou os filtros." };
}

function Row({ label, values, tones }: { label: string; values: string[]; tones?: string[] }) {
  return (
    <tr>
      <th scope="row">{label}</th>
      {values.map((v, i) => (
        <td key={i} className={`num ${tones?.[i] ?? ""}`}>
          {v}
        </td>
      ))}
    </tr>
  );
}

export function SplitTable({ segments }: { segments: Segment[] }) {
  if (segments.length !== 2) return null;
  const [a, c] = segments;
  const v = splitVerdict(a, c);
  return (
    <section className="rb">
      <h3>Ajuste × confirmação</h3>
      <p className="muted small">
        O período foi dividido em dois. Use o primeiro para escolher parâmetros e filtros; o segundo mostra como a mesma configuração se saiu em dados que
        você não usou para ajustar.
      </p>
      <div className="table-wrap">
        <table className="rb-table">
          <thead>
            <tr>
              <th />
              <th className="num">
                Ajuste
                <span className="rb-dates">{day(a.start)} a {day(a.end - 1)}</span>
              </th>
              <th className="num">
                Confirmação
                <span className="rb-dates">{day(c.start)} a {day(c.end - 1)}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <Row label="Operações" values={[String(a.trades), String(c.trades)]} />
            <Row label="Taxa de acerto" values={[`${money(a.win_rate_pct, 1)}%`, `${money(c.win_rate_pct, 1)}%`]} />
            <Row label="Ganho médio ÷ perda média" values={[opt(a.payoff), opt(c.payoff)]} />
            <Row
              label="Fator de lucro"
              values={[opt(a.profit_factor), opt(c.profit_factor)]}
              tones={[pf(a.profit_factor) < 1 ? "loss" : "", pf(c.profit_factor) < 1 ? "loss" : ""]}
            />
            <Row label="Resultado" values={[pct(a.return_pct), pct(c.return_pct)]} tones={[pnlClass(a.return_pct), pnlClass(c.return_pct)]} />
            <Row label="Comprar e segurar" values={[pct(a.buy_hold_pct), pct(c.buy_hold_pct)]} />
            <Row label="Queda máxima" values={[`-${money(a.max_drawdown_pct)}%`, `-${money(c.max_drawdown_pct)}%`]} />
          </tbody>
        </table>
      </div>
      <p className={`rb-verdict ${v.tone}`}>{v.text}</p>
    </section>
  );
}

function filterVerdict(base: CompareMetrics, withF: CompareMetrics, baseConf?: Segment, withConf?: Segment): { tone: "" | "gain" | "loss"; text: string } {
  const better = pf(withF.profit_factor) > pf(base.profit_factor) && withF.return_pct >= base.return_pct - 0.01;
  const confBetter = baseConf && withConf ? pf(withConf.profit_factor) >= pf(baseConf.profit_factor) && withConf.return_pct >= baseConf.return_pct - 0.01 : null;
  if (withF.trades < 10) return { tone: "", text: "Com os filtros sobraram poucas operações; o resultado pode ser acaso. Use um período maior ou filtros menos rígidos." };
  if (better && confBetter !== false)
    return { tone: "gain", text: confBetter ? "Os filtros melhoraram o resultado, inclusive no período de confirmação." : "Os filtros melhoraram o resultado no período todo." };
  if (better && confBetter === false)
    return { tone: "", text: "Os filtros melhoraram o período de ajuste, mas não o de confirmação. Cuidado com o excesso de ajuste." };
  return { tone: "loss", text: "Nesta configuração os filtros não ajudaram. Tente outros filtros ou desligue-os." };
}

export function FilterCompare({
  base,
  withF,
  baseSegments,
  segments,
  filtered,
  reasons,
}: {
  base: CompareMetrics;
  withF: CompareMetrics;
  baseSegments: Segment[];
  segments: Segment[];
  filtered: number;
  reasons: { reason: string; count: number }[];
}) {
  const bc = baseSegments[1];
  const wc = segments[1];
  const v = filterVerdict(base, withF, bc, wc);
  return (
    <section className="rb">
      <h3>Com filtros × sem filtros</h3>
      <p className="muted small">
        Mesma estratégia e mesmo período, rodada também sem os filtros e sem o stop/alvo pelo ATR.
        {filtered > 0 && ` Os filtros barraram ${filtered} entrada${filtered > 1 ? "s" : ""}`}
        {reasons.length > 0 && `: ${reasons.map((r) => `${r.reason.charAt(0).toLowerCase()}${r.reason.slice(1)} (${r.count})`).join(", ")}`}
        {filtered > 0 && "."}
      </p>
      <div className="table-wrap">
        <table className="rb-table">
          <thead>
            <tr>
              <th />
              <th className="num">Sem filtros</th>
              <th className="num">Com filtros</th>
            </tr>
          </thead>
          <tbody>
            <Row label="Operações" values={[String(base.trades), String(withF.trades)]} />
            <Row label="Taxa de acerto" values={[`${money(base.win_rate_pct, 1)}%`, `${money(withF.win_rate_pct, 1)}%`]} tones={["", withF.win_rate_pct > base.win_rate_pct ? "gain" : ""]} />
            <Row label="Ganho médio ÷ perda média" values={[opt(base.payoff), opt(withF.payoff)]} />
            <Row
              label="Fator de lucro"
              values={[opt(base.profit_factor), opt(withF.profit_factor)]}
              tones={[pf(base.profit_factor) < 1 ? "loss" : "", pf(withF.profit_factor) < 1 ? "loss" : pf(withF.profit_factor) > pf(base.profit_factor) ? "gain" : ""]}
            />
            <Row label="Resultado" values={[pct(base.return_pct), pct(withF.return_pct)]} tones={[pnlClass(base.return_pct), pnlClass(withF.return_pct)]} />
            <Row label="Queda máxima" values={[`-${money(base.max_drawdown_pct)}%`, `-${money(withF.max_drawdown_pct)}%`]} />
            {bc && wc && (
              <>
                <Row label="Acerto na confirmação" values={[`${money(bc.win_rate_pct, 1)}%`, `${money(wc.win_rate_pct, 1)}%`]} />
                <Row label="Resultado na confirmação" values={[pct(bc.return_pct), pct(wc.return_pct)]} tones={[pnlClass(bc.return_pct), pnlClass(wc.return_pct)]} />
              </>
            )}
          </tbody>
        </table>
      </div>
      <p className={`rb-verdict ${v.tone}`}>{v.text}</p>
    </section>
  );
}
