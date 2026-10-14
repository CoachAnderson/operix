"use client";

import { useState } from "react";
import { ErrorText, Loading, PageHead, StatusTag, VenueTag, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { MODE_LABEL, STATUS_LABEL, dateTime } from "@/lib/format";
import type { Bot } from "@/lib/types";

export default function AdminBots() {
  const [status, setStatus] = useState("");
  const bots = useApi<Bot[]>(`/admin/bots${status ? `?status=${status}` : ""}`);
  const action = useAction();

  async function stop(b: Bot) {
    if (!window.confirm(`Parar o robô "${b.name}"? O assinante verá que foi parado pela administração.`)) return;
    await action.run(() => api(`/admin/bots/${b.id}/stop`, { method: "POST" }));
    await bots.reload();
  }

  return (
    <>
      <PageHead title="Robôs">
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filtrar por situação">
          <option value="">Todos</option>
          {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </PageHead>
      <ErrorText>{action.error}</ErrorText>
      {!bots.data ? (
        <Loading />
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Robô</th><th>Par</th><th>Estratégia</th><th>Ambiente</th><th>Modalidade</th><th>Situação</th><th>Último ciclo</th><th /></tr></thead>
            <tbody>
              {bots.data.map((b) => (
                <tr key={b.id}>
                  <td>{b.name}</td>
                  <td>{b.symbol}</td>
                  <td>{b.strategy}</td>
                  <td><VenueTag venue={b.venue} /></td>
                  <td>{MODE_LABEL[b.exec_mode]}</td>
                  <td title={b.status_reason ?? undefined}><StatusTag status={b.status} /></td>
                  <td>{dateTime(b.last_tick_at)}</td>
                  <td className="num">{b.status === "running" && <button className="btn btn-quiet loss" onClick={() => stop(b)}>Parar</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {bots.data.length === 0 && <div className="empty">Nenhum robô.</div>}
        </div>
      )}
    </>
  );
}
