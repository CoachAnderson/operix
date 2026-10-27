"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { dateTime, money, pnlClass, signed } from "@/lib/format";

interface Slot {
  i: number;
  buy: number;
  sell: number;
  status: "holding" | "armed" | "idle";
  qty: number | null;
  cost: number | null;
  bought_at: number | null;
}
interface Ladder {
  kind: "grid" | "dca";
  price: number | null;
  status: string;
  capital: number | null;
  order_size: number;
  pending: boolean;
  last_error: string | null;
  profit: number;
  rounds: number;
  open_result?: number | null;
  // grade
  started?: boolean;
  lower?: number;
  upper?: number;
  step_min_pct?: number;
  stop?: number | null;
  slots?: Slot[];
  lots?: number;
  held_cost?: number;
  next_buy?: number | null;
  next_sell?: number | null;
  // DCA
  cycle?: number;
  orders?: number;
  max_orders?: number;
  trigger?: "drop" | "time";
  avg?: number | null;
  take?: number | null;
  cost?: number;
  done?: boolean;
  next_time?: number | null;
  plan?: { k: number; quote: number; drop_pct: number; price: number | null; done: boolean }[];
}

const px = (v: number | null | undefined) => (v === null || v === undefined ? "—" : money(v, v >= 100 ? 2 : v >= 1 ? 4 : 8));

/** Situação da grade (níveis e lotes) ou do ciclo de compras, atualizada a cada 15 s. */
export function LadderStatus({ botId, quote }: { botId: string; quote: string }) {
  const [d, setD] = useState<Ladder | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setD(await api<Ladder>(`/bots/${botId}/ladder`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Não foi possível ler a situação");
    }
  }, [botId]);
  useEffect(() => {
    void load();
    const t = setInterval(() => {
      if (!document.hidden) void load();
    }, 15_000);
    return () => clearInterval(t);
  }, [load]);

  if (error) return <p className="loss small">{error}</p>;
  if (!d) return null;
  const notes = (
    <>
      {d.pending && <p className="notice small">Uma ordem está aguardando a confirmação da corretora; o robô espera antes de enviar outra.</p>}
      {d.last_error && (
        <p className="notice notice-danger small">
          <strong>A última ordem foi recusada</strong>
          {d.last_error}. O robô tenta de novo em alguns minutos. Confira o saldo livre e o valor dos lotes.
        </p>
      )}
    </>
  );

  if (d.kind === "grid") {
    if (!d.slots?.length)
      return (
        <div style={{ display: "grid", gap: 10 }}>
          <h2>Grade</h2>
          <p className="muted">
            A grade é montada quando o robô for ligado, a partir do preço daquele momento{d.price ? ` (agora ${px(d.price)})` : ""}. Dinheiro necessário:{" "}
            {money(d.capital)} {quote}.
          </p>
          {notes}
        </div>
      );
    const slots = [...d.slots].reverse(); // de cima para baixo, como no gráfico
    const total = d.slots.length;
    return (
      <div style={{ display: "grid", gap: 12, gridTemplateColumns: "minmax(0, 1fr)" }}>
        <h2>Grade</h2>
        <dl className="figures" style={{ margin: 0 }}>
          <div>
            <dt>Lotes comprados</dt>
            <dd>
              {d.lots} de {total}
            </dd>
            <span className="muted small">custo {money(d.held_cost)} {quote}</span>
          </div>
          <div>
            <dt>Lucro das grades</dt>
            <dd className={pnlClass(d.profit)}>{signed(d.profit)}</dd>
            <span className="muted small">{d.rounds} venda(s) com lucro de uma grade</span>
          </div>
          <div>
            <dt>Lotes em aberto</dt>
            <dd className={pnlClass(d.open_result ?? 0)}>{d.open_result === null || d.open_result === undefined ? "—" : signed(d.open_result)}</dd>
            <span className="muted small">se vendesse tudo agora, antes das taxas</span>
          </div>
          <div>
            <dt>Preço agora</dt>
            <dd>{px(d.price)}</dd>
            <span className="muted small">
              compra em {px(d.next_buy)} · venda em {px(d.next_sell)}
            </span>
          </div>
        </dl>
        <p className="muted small" style={{ margin: 0 }}>
          Faixa de {px(d.lower)} a {px(d.upper)}, {total} grades de {money(d.step_min_pct, 2)}%, {money(d.order_size)} {quote} por lote.
          {d.stop ? ` Stop em ${px(d.stop)}.` : " Sem stop."}
          {d.price !== null && d.lower !== undefined && d.price < d.lower && " O preço está abaixo da faixa: o robô segura os lotes e espera."}
          {d.price !== null && d.upper !== undefined && d.price > d.upper && " O preço está acima da faixa: tudo vendido, o robô espera voltar."}
        </p>
        {notes}
        <details>
          <summary>Níveis da grade ({total})</summary>
          <div className="table-wrap" style={{ marginTop: 8, maxHeight: 420, overflowY: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Grade</th>
                  <th className="num">Compra em</th>
                  <th className="num">Vende em</th>
                  <th>Situação</th>
                </tr>
              </thead>
              <tbody>
                {slots.map((x) => {
                  const here = d.price !== null && d.price >= x.buy && d.price < x.sell;
                  return (
                    <tr key={x.i} style={here ? { outline: "2px solid var(--accent)", outlineOffset: -2 } : undefined}>
                      <td>
                        {x.i + 1}
                        {here && <span className="muted small"> · preço aqui</span>}
                      </td>
                      <td className="num">{px(x.buy)}</td>
                      <td className="num">{px(x.sell)}</td>
                      <td className={x.status === "holding" ? "gain" : x.status === "armed" ? "" : "muted"}>
                        {x.status === "holding"
                          ? `Com lote (comprado a ${px(x.bought_at)}), vende em ${px(x.sell)}`
                          : x.status === "armed"
                            ? `Compra quando cair a ${px(x.buy)}`
                            : "Sem lote; arma a compra quando o preço passar acima"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </details>
      </div>
    );
  }

  const k = d.orders ?? 0;
  return (
    <div style={{ display: "grid", gap: 12, gridTemplateColumns: "minmax(0, 1fr)" }}>
      <h2>Ciclo de compras</h2>
      <dl className="figures" style={{ margin: 0 }}>
        <div>
          <dt>Ciclo atual</dt>
          <dd>{k ? `${d.cycle}º` : "—"}</dd>
          <span className="muted small">{k ? `${k} de ${d.max_orders} compras` : d.done ? "encerrado" : "começa na próxima avaliação"}</span>
        </div>
        <div>
          <dt>Preço médio</dt>
          <dd>{px(d.avg)}</dd>
          <span className="muted small">custo {money(d.cost)} {quote}</span>
        </div>
        <div>
          <dt>Vende tudo em</dt>
          <dd className="gain">{px(d.take)}</dd>
          <span className="muted small">{d.stop ? `stop em ${px(d.stop)}` : "sem stop"}</span>
        </div>
        <div>
          <dt>Em aberto</dt>
          <dd className={pnlClass(d.open_result ?? 0)}>{d.open_result === null || d.open_result === undefined ? "—" : signed(d.open_result)}</dd>
          <span className="muted small">preço agora {px(d.price)}</span>
        </div>
        <div>
          <dt>Lucro dos ciclos</dt>
          <dd className={pnlClass(d.profit)}>{signed(d.profit)}</dd>
          <span className="muted small">{d.rounds} ciclo(s) concluído(s)</span>
        </div>
      </dl>
      {d.trigger === "time" && d.next_time && <p className="muted small" style={{ margin: 0 }}>Próxima compra programada: {dateTime(new Date(d.next_time).toISOString())}.</p>}
      {notes}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Compra</th>
              <th className="num">{d.trigger === "time" ? "Quando" : "Queda desde a 1ª"}</th>
              {d.trigger !== "time" && <th className="num">Preço</th>}
              <th className="num">Valor ({quote})</th>
              <th>Situação</th>
            </tr>
          </thead>
          <tbody>
            {d.plan?.map((o) => (
              <tr key={o.k}>
                <td>{o.k + 1}ª</td>
                <td className="num">{o.k === 0 ? "na partida" : d.trigger === "time" ? "pelo intervalo" : `−${money(o.drop_pct, 2)}%`}</td>
                {d.trigger !== "time" && <td className="num">{px(o.k === 0 ? null : o.price)}</td>}
                <td className="num">{money(o.quote)}</td>
                <td className={o.done ? "gain" : "muted"}>{o.done ? "Feita" : o.k === k ? "Próxima" : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
