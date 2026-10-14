"use client";

import { useState } from "react";
import { ErrorText, Loading, PageHead, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { brl, dateTime } from "@/lib/format";

interface Stats {
  users_total: number;
  subscriptions_active: number;
  mrr: string;
  bots_running: number;
  bots_live: number;
  orders_24h: number;
  kill_switch: boolean;
}
interface KillSwitch { enabled: boolean; reason: string; at?: string }
interface FailedHook { id: string; topic: string; resource_id: string; error: string | null; created_at: string }

export default function AdminHome() {
  const stats = useApi<Stats>("/admin/stats");
  const ks = useApi<KillSwitch>("/admin/kill-switch");
  const hooks = useApi<FailedHook[]>("/admin/webhooks/failed");
  const action = useAction();
  const [reason, setReason] = useState("");

  async function toggle(enabled: boolean) {
    const text = enabled
      ? "Suspender TODAS as ordens da plataforma agora? Nenhum robô vai operar até você liberar."
      : "Liberar as operações de novo?";
    if (!window.confirm(text)) return;
    await action.run(() => api("/admin/kill-switch", { json: { enabled, reason } }));
    setReason("");
    await Promise.all([ks.reload(), stats.reload()]);
  }

  async function reprocess(id: string) {
    await action.run(() => api(`/admin/webhooks/${id}/reprocess`, { method: "POST" }));
    setTimeout(() => void hooks.reload(), 1500);
  }

  const s = stats.data;
  return (
    <>
      <PageHead title="Visão geral" />
      {stats.error && <p className="loss">{stats.error}</p>}
      {!s ? (
        <Loading />
      ) : (
        <dl className="figures">
          <div><dt>Receita recorrente mensal</dt><dd>{brl(s.mrr)}</dd></div>
          <div><dt>Assinaturas ativas</dt><dd>{s.subscriptions_active}</dd></div>
          <div><dt>Usuários</dt><dd>{s.users_total}</dd></div>
          <div><dt>Robôs rodando</dt><dd>{s.bots_running}</dd></div>
          <div><dt>Em conta real</dt><dd>{s.bots_live}</dd></div>
          <div><dt>Ordens em 24 h</dt><dd>{s.orders_24h}</dd></div>
        </dl>
      )}

      <section className={`section panel ${ks.data?.enabled ? "notice-danger" : ""}`} style={{ display: "grid", gap: 12 }}>
        <h2>Parada geral de operações</h2>
        {ks.data?.enabled ? (
          <>
            <p>
              <strong className="loss">Ativa desde {dateTime(ks.data.at)}.</strong> Nenhum robô envia ordens.{" "}
              {ks.data.reason && `Motivo: ${ks.data.reason}`}
            </p>
            <div><button className="btn btn-primary" onClick={() => toggle(false)} disabled={action.busy}>Liberar operações</button></div>
          </>
        ) : (
          <>
            <p className="muted">Use em incidente: instabilidade na corretora, falha de preço, suspeita de abuso. Vale para todos os assinantes e checa antes de cada ordem.</p>
            <div className="actions">
              <input placeholder="Motivo (fica na auditoria)" maxLength={255} value={reason} onChange={(e) => setReason(e.target.value)} style={{ maxWidth: 380 }} />
              <button className="btn btn-danger" onClick={() => toggle(true)} disabled={action.busy}>Suspender todas as ordens</button>
            </div>
          </>
        )}
        <ErrorText>{action.error}</ErrorText>
      </section>

      <section className="section">
        <h2>Notificações do Mercado Pago com falha</h2>
        {hooks.data?.length === 0 && <p className="muted">Nenhuma falha pendente.</p>}
        {!!hooks.data?.length && (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Recebida</th><th>Tipo</th><th>Recurso</th><th>Erro</th><th /></tr></thead>
              <tbody>
                {hooks.data.map((h) => (
                  <tr key={h.id}>
                    <td>{dateTime(h.created_at)}</td>
                    <td>{h.topic}</td>
                    <td>{h.resource_id}</td>
                    <td className="muted">{h.error ?? "Aguardando processamento"}</td>
                    <td className="num"><button className="btn btn-quiet" onClick={() => reprocess(h.id)}>Processar de novo</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
