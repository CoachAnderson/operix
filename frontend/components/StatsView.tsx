"use client";

import { money, pnlClass, signed } from "@/lib/format";

export interface StatGroup {
  trades: number;
  wins: number;
  losses: number;
  ties: number;
  hit_pct: number | null;
  ci_low_pct: number | null;
  ci_high_pct: number | null;
  p_value: number | null;
  net_wins: number;
  pnl: number;
  avg_move_pct: number;
}

export interface Analysis extends StatGroup {
  significant: boolean;
  avg_abs_move_pct: number;
  avg_cost_pct: number;
  by_tag: (StatGroup & { tag: string })[];
  by_hour: (StatGroup & { hour: number })[];
  long_hit_pct: number | null;
  short_hit_pct: number | null;
}

const MIN_HOUR_TRADES = 30;
const pv = (p: number | null) => (p === null ? "—" : p < 0.0001 ? "< 0,0001" : money(p, 4));
const sgn = (v: number, d: number) => `${v > 0 ? "+" : ""}${money(v, d)}`;
const hit = (v: number | null, d = 1) => (v === null ? "—" : `${money(v, d)}%`);

function verdict(a: Analysis): { tone: "" | "gain" | "loss"; text: string } {
  const n = a.wins + a.losses;
  if (n < 30) return { tone: "", text: `Só ${n} operações com direção definida: pouco para qualquer conclusão estatística.` };
  const costs = a.avg_move_pct <= a.avg_cost_pct;
  if (!a.significant)
    return {
      tone: "loss",
      text: `O acerto de direção (${hit(a.hit_pct)}) não se distingue de 50% (p = ${pv(a.p_value)}): com estes dados, a regra não mostrou vantagem sobre o acaso.${costs ? " E os custos ficam com parte de cada operação." : ""}`,
    };
  if ((a.hit_pct ?? 50) < 50)
    return {
      tone: "loss",
      text: `O acerto de direção (${hit(a.hit_pct)}) ficou abaixo de 50% de forma significativa (p = ${pv(a.p_value)}). Neste período, a regra errou a direção mais do que o acaso.`,
    };
  return costs
    ? {
        tone: "",
        text: `O acerto de direção (${hit(a.hit_pct)}) é acima de 50% (p = ${pv(a.p_value)}), mas o ganho médio de preço por operação (${sgn(a.avg_move_pct, 4)}%) não paga o custo médio de ida e volta (${money(a.avg_cost_pct, 4)}%).`,
      }
    : {
        tone: "gain",
        text: `O acerto de direção (${hit(a.hit_pct)}) é acima de 50% (p = ${pv(a.p_value)}) e o movimento médio a favor (${sgn(a.avg_move_pct, 4)}%) supera o custo médio (${money(a.avg_cost_pct, 4)}%). Confirme em outro período antes de usar dinheiro real.`,
      };
}

export function StatsView({ a, pre = "", tagLabel = "Padrão" }: { a: Analysis; pre?: string; tagLabel?: string }) {
  const v = verdict(a);
  const hours = a.by_hour.filter((h) => h.trades >= MIN_HOUR_TRADES && h.hit_pct !== null);
  const ranked = [...hours].sort((x, y) => (y.hit_pct ?? 0) - (x.hit_pct ?? 0));
  return (
    <section className="rb">
      <h3>Acerto de direção e teste estatístico</h3>
      <p className="muted small">
        Acerto de direção = o preço andou a favor da operação, sem contar taxa e escorregamento. Saída no mesmo preço da entrada é empate e fica fora do
        teste. O teste binomial diz se o acerto é diferente dos 50% que o acaso daria.
      </p>
      <dl className="figures" style={{ margin: 0 }}>
        <div>
          <dt>Acerto de direção</dt>
          <dd>{hit(a.hit_pct, 2)}</dd>
          <span className="muted small">
            {a.wins} a favor, {a.losses} contra
          </span>
        </div>
        <div>
          <dt>Intervalo de 95%</dt>
          <dd>
            {a.ci_low_pct === null ? "—" : `${money(a.ci_low_pct, 1)}–${money(a.ci_high_pct, 1)}%`}
          </dd>
          <span className="muted small">onde o acerto verdadeiro provavelmente está</span>
        </div>
        <div>
          <dt>p-valor contra 50%</dt>
          <dd className={a.significant ? "" : "muted"}>{pv(a.p_value)}</dd>
          <span className="muted small">{a.significant ? "diferente do acaso (abaixo de 0,05)" : "não se distingue do acaso"}</span>
        </div>
        <div>
          <dt>Empates</dt>
          <dd>{a.ties}</dd>
          <span className="muted small">saída no preço da entrada</span>
        </div>
        <div>
          <dt>Movimento médio a favor</dt>
          <dd className={a.avg_move_pct > a.avg_cost_pct ? "gain" : "loss"}>{sgn(a.avg_move_pct, 4)}%</dd>
          <span className="muted small">por operação, antes dos custos</span>
        </div>
        <div>
          <dt>Custo de ida e volta</dt>
          <dd>{money(a.avg_cost_pct, 4)}%</dd>
          <span className="muted small">taxa e escorregamento por operação</span>
        </div>
      </dl>
      <p className={`rb-verdict ${v.tone}`}>{v.text}</p>

      {a.by_tag.length > 0 && (
        <div className="table-wrap">
          <table className="rb-table">
            <thead>
              <tr>
                <th>{tagLabel}</th>
                <th className="num">Operações</th>
                <th className="num">Acerto de direção</th>
                <th className="num">p-valor</th>
                <th className="num">Resultado</th>
              </tr>
            </thead>
            <tbody>
              {a.by_tag.map((g) => (
                <tr key={g.tag}>
                  <th scope="row">{g.tag}</th>
                  <td className="num">{g.trades}</td>
                  <td className="num">{hit(g.hit_pct)}</td>
                  <td className="num">{pv(g.p_value)}</td>
                  <td className={`num ${pnlClass(g.pnl)}`}>
                    {pre}
                    {signed(g.pnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {a.by_hour.length > 1 && (
        <details>
          <summary>Por hora do dia (horário de Brasília)</summary>
          <p className="muted small">
            Horários com menos de {MIN_HOUR_TRADES} operações aparecem apagados. Escolher só os melhores horários depois de ver o resultado infla o acerto: entre
            24 horários, alguns parecem bons por pura sorte. Confirme em outro período antes de filtrar.
            {ranked.length >= 2 && (
              <>
                {" "}
                Melhor: {String(ranked[0].hour).padStart(2, "0")}h ({hit(ranked[0].hit_pct)}). Pior: {String(ranked[ranked.length - 1].hour).padStart(2, "0")}h (
                {hit(ranked[ranked.length - 1].hit_pct)}).
              </>
            )}
          </p>
          <div className="table-wrap">
            <table className="rb-table">
              <thead>
                <tr>
                  <th>Hora</th>
                  <th className="num">Operações</th>
                  <th className="num">Acerto de direção</th>
                  <th className="num">p-valor</th>
                  <th className="num">Resultado</th>
                </tr>
              </thead>
              <tbody>
                {a.by_hour.map((g) => (
                  <tr key={g.hour} className={g.trades < MIN_HOUR_TRADES ? "muted" : ""}>
                    <th scope="row">{String(g.hour).padStart(2, "0")}h</th>
                    <td className="num">{g.trades}</td>
                    <td className="num">{hit(g.hit_pct)}</td>
                    <td className="num">{pv(g.p_value)}</td>
                    <td className={`num ${pnlClass(g.pnl)}`}>
                      {pre}
                      {signed(g.pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </section>
  );
}
