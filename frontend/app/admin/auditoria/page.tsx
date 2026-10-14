"use client";

import { useState } from "react";
import { Loading, PageHead, useApi } from "@/components/ui";
import { dateTime } from "@/lib/format";

interface Audit {
  id: string;
  actor_id: string | null;
  action: string;
  target: string | null;
  ip: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

const FILTERS: [string, string][] = [
  ["", "Tudo"],
  ["auth", "Acessos"],
  ["order", "Ordens"],
  ["bot", "Robôs"],
  ["billing", "Cobrança"],
  ["credential", "Credenciais"],
  ["admin", "Ações de admin"],
];

export default function AdminAudit() {
  const [action, setAction] = useState("");
  const { data } = useApi<Audit[]>(`/admin/audit?action=${action}`);
  return (
    <>
      <PageHead title="Auditoria" lead="Registro de acessos, ordens, mudanças de configuração e ações administrativas.">
        <select value={action} onChange={(e) => setAction(e.target.value)} aria-label="Filtrar eventos">
          {FILTERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </PageHead>
      {!data ? (
        <Loading />
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Quando</th><th>Evento</th><th>Quem</th><th>Alvo</th><th>IP</th><th>Detalhes</th></tr></thead>
            <tbody>
              {data.map((a) => (
                <tr key={a.id}>
                  <td>{dateTime(a.created_at)}</td>
                  <td>{a.action}</td>
                  <td className="muted small">{a.actor_id?.slice(0, 8) ?? "sistema"}</td>
                  <td className="muted small">{a.target?.slice(0, 12) ?? ""}</td>
                  <td className="muted small">{a.ip ?? ""}</td>
                  <td className="muted small" style={{ whiteSpace: "normal" }}>
                    {Object.entries(a.details).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join("; ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.length === 0 && <div className="empty">Nenhum evento.</div>}
        </div>
      )}
    </>
  );
}
