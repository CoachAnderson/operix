"use client";

import { money, pnlClass, signed } from "@/lib/format";

export interface StatsMetrics {
  trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  avg_win: number;
  avg_loss: number;
  payoff: number | null;
  net_pnl: number;
  return_pct: number;
  max_drawdown_pct: number;
  max_consecutive_losses: number;
  max_consecutive_wins?: number;
  months_total?: number;
  months_positive?: number;
  months_negative?: number;
  breakeven_win_rate_pct?: number | null;
}

export interface MartingaleSummary {
  multiplier: number;
  levels: number;
  max_level_reached: number;
  max_factor: number;
  max_factor_possible: number;
  max_notional: number;
  cycles_lost: number;
  worst_cycle_loss: number;
  loss_rate_pct: number;
  losses_to_bust: number;
  bust_every_cycles: number | null;
  cycle_loss_in_base_stops: number;
  cycles_won: number;
  cycle_hit_pct: number | null;
}

const pct = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "—" : `${money(v, d)}%`);

/** As estatísticas que os vendedores de robô mostram — e, ao lado, as que eles costumam esconder. */
export function PeriodStats({ m, pre = "" }: { m: StatsMetrics; pre?: string }) {
  const months = m.months_total ?? 0;
  const pos = months ? ((m.months_positive ?? 0) / months) * 100 : null;
  const neg = months ? ((m.months_negative ?? 0) / months) * 100 : null;
  const be = m.breakeven_win_rate_pct ?? null;
  const margin = be === null ? null : m.win_rate_pct - be;
  return (
    <section className="rb">
      <h3>Estatísticas do período</h3>
      <div className="grid-2" style={{ alignItems: "start", gap: 16 }}>
        <div className="table-wrap">
          <table className="rb-table">
            <tbody>
              <tr><th scope="row">Operações vencedoras</th><td className="num">{m.wins}</td></tr>
              <tr><th scope="row">Operações perdedoras</th><td className="num">{m.losses}</td></tr>
              <tr><th scope="row">Nível de acerto</th><td className="num"><strong>{pct(m.win_rate_pct)}</strong></td></tr>
              <tr><th scope="row">Meses no positivo</th><td className="num">{pct(pos, 0)} <span className="muted small">({m.months_positive ?? 0} de {months})</span></td></tr>
              <tr><th scope="row">Meses no negativo</th><td className="num">{pct(neg, 0)}</td></tr>
              <tr><th scope="row">Maior sequência vencedora</th><td className="num">{m.max_consecutive_wins ?? "—"}</td></tr>
              <tr><th scope="row">Maior sequência perdedora</th><td className="num">{m.max_consecutive_losses}</td></tr>
            </tbody>
          </table>
        </div>
        <div className="table-wrap">
          <table className="rb-table">
            <caption className="muted small" style={{ textAlign: "left", padding: "8px 12px" }}>O que essa lista não mostra</caption>
            <tbody>
              <tr><th scope="row">Acerto necessário para empatar</th><td className="num"><strong>{pct(be)}</strong></td></tr>
              <tr><th scope="row">Ganho médio × perda média</th><td className="num">{signed(m.avg_win)} × {signed(m.avg_loss)}</td></tr>
              <tr><th scope="row">Resultado do período</th><td className={`num ${pnlClass(m.net_pnl)}`}>{pre}{signed(m.net_pnl)} ({m.return_pct > 0 ? "+" : ""}{money(m.return_pct)}%)</td></tr>
              <tr><th scope="row">Queda máxima do saldo</th><td className="num loss">-{money(m.max_drawdown_pct)}%</td></tr>
            </tbody>
          </table>
        </div>
      </div>
      {margin !== null && m.trades >= 10 && (
        <p className={`rb-verdict ${margin > 0 ? "gain" : "loss"}`}>
          {margin > 0
            ? `O acerto (${pct(m.win_rate_pct)}) ficou ${money(margin, 1)} pontos acima do mínimo para empatar (${pct(be)}).`
            : `Mesmo acertando ${pct(m.win_rate_pct)}, o resultado foi negativo: com esse ganho e essa perda médios, era preciso acertar ${pct(be)}. Acerto alto não garante lucro.`}
        </p>
      )}
    </section>
  );
}

/** Mesma configuração com e sem martingale, lado a lado. */
export function MartingaleCompare({ withMg, without, mg, pre = "" }: { withMg: StatsMetrics; without: StatsMetrics; mg: MartingaleSummary; pre?: string }) {
  const better = withMg.net_pnl > without.net_pnl;
  const rows: [string, string, string, string?, string?][] = [
    ["Operações", String(without.trades), String(withMg.trades)],
    ["Acerto por operação", pct(without.win_rate_pct), pct(withMg.win_rate_pct)],
    ["Acerto contando cada ciclo como 1 operação", "—", pct(mg.cycle_hit_pct)],
    ["Resultado", `${pre}${signed(without.net_pnl)}`, `${pre}${signed(withMg.net_pnl)}`, pnlClass(without.net_pnl), pnlClass(withMg.net_pnl)],
    ["Queda máxima do saldo", `-${money(without.max_drawdown_pct)}%`, `-${money(withMg.max_drawdown_pct)}%`, "", withMg.max_drawdown_pct > without.max_drawdown_pct ? "loss" : ""],
    ["Maior tamanho de posição", "1×", `${money(mg.max_factor, 0)}× (até ${money(mg.max_factor_possible, 0)}×)`],
    ["Ciclos perdidos (todas as dobras)", "—", String(mg.cycles_lost)],
    ["Pior ciclo", "—", `${pre}${signed(mg.worst_cycle_loss)}`, "", "loss"],
  ];
  return (
    <section className="rb">
      <h3>Martingale: com e sem</h3>
      <p className="muted small">
        Multiplica por {money(mg.multiplier, 1)} a entrada depois de cada perda, até {mg.levels} vez(es) seguidas; volta ao tamanho base depois de um ganho ou
        quando perde todas as dobras (ciclo perdido).
      </p>
      <div className="table-wrap">
        <table className="rb-table">
          <thead>
            <tr>
              <th />
              <th className="num">Sem martingale</th>
              <th className="num">Com martingale</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, a, b, ta, tb]) => (
              <tr key={label}>
                <th scope="row">{label}</th>
                <td className={`num ${ta ?? ""}`}>{a}</td>
                <td className={`num ${tb ?? ""}`}>{b}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={`rb-verdict ${better ? "" : "loss"}`}>
        {better
          ? `Neste período o martingale terminou melhor, mas um único ciclo perdido custa ${money(mg.cycle_loss_in_base_stops, 0)} vezes a perda de uma entrada normal. `
          : `O martingale não melhorou o resultado. `}
        Com {pct(mg.loss_rate_pct)} de operações perdedoras, perder {mg.losses_to_bust} seguidas (e o ciclo inteiro) acontece em média uma vez a cada{" "}
        {mg.bust_every_cycles ? money(mg.bust_every_cycles, 0) : "—"} ciclos. O acerto por ciclo parece alto porque esconde essas perdas grandes; o acerto por
        operação não muda.
      </p>
    </section>
  );
}
