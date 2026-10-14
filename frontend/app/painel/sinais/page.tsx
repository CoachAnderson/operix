"use client";

import { useEffect } from "react";
import { ErrorText, Loading, PageHead, Stripe, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime, price } from "@/lib/format";
import type { Bot, Signal } from "@/lib/types";

const STATUS: Record<Signal["status"], string> = {
  pending: "Aguardando você",
  executed: "Executado",
  dismissed: "Descartado",
  expired: "Expirou",
  failed: "Falhou",
};

export default function SignalsPage() {
  const pending = useApi<Signal[]>("/signals?status=pending");
  const history = useApi<Signal[]>("/signals?limit=50");
  const { data: bots } = useApi<Bot[]>("/bots");
  const action = useAction();

  useEffect(() => {
    const t = setInterval(() => void pending.reload(), 20_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const bot = (id: string) => bots?.find((b) => b.id === id);

  async function decide(sig: Signal, verb: "execute" | "dismiss") {
    const b = bot(sig.bot_id);
    if (verb === "execute" && b?.venue === "live" && !window.confirm(`Enviar ${sig.side === "BUY" ? "compra" : "venda"} de ${sig.symbol} na CONTA REAL?`)) return;
    await action.run(() => api(`/signals/${sig.id}/${verb}`, { method: "POST" }));
    await Promise.all([pending.reload(), history.reload()]);
  }

  return (
    <>
      <PageHead title="Sinais" lead="Robôs no modo sinais avisam aqui. Cada sinal vale por alguns minutos; depois expira." />
      <ErrorText>{action.error}</ErrorText>

      {pending.loading && !pending.data && <Loading />}
      {pending.data?.length === 0 && <div className="panel empty">Nenhum sinal esperando. Quando um robô encontrar uma entrada ou saída, ele aparece aqui.</div>}
      <div className="ledger">
        {pending.data?.map((s) => {
          const b = bot(s.bot_id);
          return (
            <article key={s.id} className="signal">
              {b && <Stripe venue={b.venue} />}
              <div className="entry-body">
                <span className={`side side-${s.side}`}>{s.side === "BUY" ? "Comprar" : "Vender"}</span>
                <div>
                  <div className="title">
                    {s.symbol} perto de {price(s.ref_price)}
                  </div>
                  <div className="muted small">
                    {b?.name}: {s.reason}. Expira às {new Date(s.expires_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}.
                  </div>
                </div>
                <div className="actions">
                  <button className="btn btn-primary" disabled={action.busy} onClick={() => decide(s, "execute")}>
                    {s.side === "BUY" ? "Comprar agora" : "Vender agora"}
                  </button>
                  <button className="btn btn-quiet" disabled={action.busy} onClick={() => decide(s, "dismiss")}>
                    Descartar
                  </button>
                </div>
              </div>
            </article>
          );
        })}
      </div>

      <section className="section">
        <h2>Histórico</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Quando</th>
                <th>Robô</th>
                <th>Sinal</th>
                <th className="num">Preço de referência</th>
                <th>Motivo</th>
                <th>Situação</th>
              </tr>
            </thead>
            <tbody>
              {history.data?.map((s) => (
                <tr key={s.id}>
                  <td>{dateTime(s.created_at)}</td>
                  <td>{bot(s.bot_id)?.name ?? "—"}</td>
                  <td className={`side-${s.side}`}>{s.side === "BUY" ? "Compra" : "Venda"} {s.symbol}</td>
                  <td className="num">{price(s.ref_price)}</td>
                  <td className="muted">{s.reason}</td>
                  <td>{STATUS[s.status]}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {history.data?.length === 0 && <div className="empty">Sem histórico.</div>}
        </div>
      </section>
    </>
  );
}
