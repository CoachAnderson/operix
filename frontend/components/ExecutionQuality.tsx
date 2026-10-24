"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { money, pnlClass, signed } from "@/lib/format";

interface Row {
  at: number;
  side: "BUY" | "SELL";
  exit: boolean;
  reason: string;
  ref_price: number | null;
  price: number;
  delay_s: number | null;
  slip_pct: number | null;
  net: number | null;
  fees: number | null;
  gross: number | null;
}
interface Quality {
  currency: string;
  orders: number;
  measured: number;
  delay_avg_s: number | null;
  delay_p90_s: number | null;
  delay_max_s: number | null;
  slip_avg_pct: number | null;
  slip_cost: number;
  trades: number;
  trades_with_fees: number;
  net_total: number;
  fees_total: number;
  gross_total: number;
  wins_net: number;
  wins_gross: number;
  price_ok_fee_loss: number;
  rows: Row[];
}

const secs = (v: number | null) => (v === null ? "—" : v < 10 ? `${money(v, 1)} s` : `${money(v, 0)} s`);
const pct = (v: number | null, d = 3) => (v === null ? "—" : `${v > 0 ? "+" : ""}${money(v, d)}%`);
const px = (v: number | null) => (v === null ? "—" : money(v, v >= 100 ? 2 : v >= 1 ? 4 : 6));

/** Separa o resultado em: movimento do preço (pelos preços do sinal) − escorregamento − taxas = resultado final. */
function verdicts(q: Quality): { tone: string; text: string }[] {
  const out: { tone: string; text: string }[] = [];
  const cur = q.currency;
  const move = q.gross_total + q.slip_cost; // o que a estratégia teria feito executando no preço do sinal
  const costs = q.fees_total + q.slip_cost;
  if (q.trades_with_fees >= 3) {
    if (move > 0 && q.net_total <= 0)
      out.push({
        tone: "loss",
        text: `Os custos estão transformando ganho em perda: pelo preço dos sinais, as operações renderam ${signed(move)} ${cur}, mas taxas (${money(q.fees_total)}) e escorregamento (${money(q.slip_cost)}) custaram ${money(costs)} ${cur}. Use um tempo gráfico maior, alvos maiores ou custo menor (na Binance, pagar a taxa com BNB dá desconto).`,
      });
    else if (move <= 0)
      out.push({
        tone: "loss",
        text: `Mesmo sem nenhum custo, pelo preço dos sinais as operações dariam ${signed(move)} ${cur}: a estratégia não está acertando o movimento. As taxas (${money(q.fees_total)}) e o escorregamento (${money(q.slip_cost)}) só aumentam a perda. Teste a estratégia e o par no backtest antes de continuar.`,
      });
    else out.push({ tone: "gain", text: `Pelo preço dos sinais, as operações renderam ${signed(move)} ${cur}; depois de ${money(costs)} ${cur} em custos, sobrou ${signed(q.net_total)} ${cur}.` });
  }
  if (q.delay_avg_s !== null && q.measured >= 3) {
    if (q.delay_avg_s > 10)
      out.push({ tone: "loss", text: `Atraso alto: em média ${secs(q.delay_avg_s)} entre o sinal e a execução. Confira se o motor está rodando a versão nova e se o servidor está perto da corretora.` });
    else out.push({ tone: "gain", text: `Atraso normal: em média ${secs(q.delay_avg_s)} entre o fechamento do candle e a execução.` });
  }
  return out;
}

export function ExecutionQuality({ botId }: { botId: string }) {
  const [q, setQ] = useState<Quality | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setQ(await api<Quality>(`/bots/${botId}/execution`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Não foi possível medir as execuções");
    }
  }, [botId]);

  useEffect(() => {
    void load();
    const t = setInterval(() => {
      if (!document.hidden) void load();
    }, 60_000);
    return () => clearInterval(t);
  }, [load]);

  if (error) return <p className="loss small">{error}</p>;
  if (!q) return null;
  const v = verdicts(q);
  return (
    <div style={{ display: "grid", gap: 14, gridTemplateColumns: "minmax(0, 1fr)", minWidth: 0 }}>
      <h2>Atraso, escorregamento e taxas</h2>
      {q.orders === 0 ? (
        <p className="muted">Nenhuma ordem executada ainda. Depois das primeiras operações, este painel mostra de onde vem o resultado.</p>
      ) : (
        <>
          <dl className="figures" style={{ margin: 0 }}>
            <div>
              <dt>Atraso médio</dt>
              <dd>{secs(q.delay_avg_s)}</dd>
              <span className="muted small">do sinal à execução · pior {secs(q.delay_max_s)}</span>
            </div>
            <div>
              <dt>Escorregamento médio</dt>
              <dd className={(q.slip_avg_pct ?? 0) > 0.05 ? "loss" : ""}>{pct(q.slip_avg_pct)}</dd>
              <span className="muted small">execução × preço do sinal · custo {money(q.slip_cost)} {q.currency}</span>
            </div>
            <div>
              <dt>Movimento do preço</dt>
              <dd className={pnlClass(q.gross_total + q.slip_cost)}>{signed(q.gross_total + q.slip_cost)}</dd>
              <span className="muted small">pelo preço dos sinais, sem custos</span>
            </div>
            <div>
              <dt>Taxas pagas</dt>
              <dd className="loss">−{money(q.fees_total)}</dd>
              <span className="muted small">entrada + saída, em {q.currency}</span>
            </div>
            <div>
              <dt>Resultado final</dt>
              <dd className={pnlClass(q.net_total)}>{signed(q.net_total)}</dd>
              <span className="muted small">{q.wins_net} de {q.trades} operações no lucro</span>
            </div>
          </dl>
          {v.map((x) => (
            <p key={x.text} className={`rb-verdict ${x.tone}`}>
              {x.text}
            </p>
          ))}
          {q.measured < q.orders && (
            <p className="muted small">
              {q.orders - q.measured} ordem(ns) anteriores a esta atualização não têm o horário do sinal; o atraso e o escorregamento valem para as novas.
            </p>
          )}
          <details>
            <summary>Ordem por ordem (últimas {q.rows.length})</summary>
            <div className="table-wrap" style={{ marginTop: 8, maxHeight: 380, overflowY: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>Quando</th>
                    <th>Ordem</th>
                    <th className="num">Preço do sinal</th>
                    <th className="num">Executado</th>
                    <th className="num">Atraso</th>
                    <th className="num">Escorreg.</th>
                    <th className="num">Antes das taxas</th>
                    <th className="num">Taxas</th>
                    <th className="num">Final</th>
                  </tr>
                </thead>
                <tbody>
                  {q.rows.map((r, i) => (
                    <tr key={`${r.at}-${i}`} title={r.reason}>
                      <td style={{ whiteSpace: "nowrap" }}>{new Date(r.at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" })}</td>
                      <td>{r.exit ? "Saída" : "Entrada"} · {r.side === "BUY" ? "compra" : "venda"}</td>
                      <td className="num">{px(r.ref_price)}</td>
                      <td className="num">{px(r.price)}</td>
                      <td className="num">{secs(r.delay_s)}</td>
                      <td className={`num ${(r.slip_pct ?? 0) > 0 ? "loss" : ""}`}>{pct(r.slip_pct)}</td>
                      <td className={`num ${r.gross === null ? "" : pnlClass(r.gross)}`}>{r.gross === null ? "—" : signed(r.gross)}</td>
                      <td className="num">{r.fees === null ? "—" : `−${money(r.fees)}`}</td>
                      <td className={`num ${r.net === null ? "" : pnlClass(r.net)}`}>{r.net === null ? "—" : signed(r.net)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </div>
  );
}
