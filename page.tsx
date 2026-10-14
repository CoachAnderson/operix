"use client";

import { useState } from "react";
import { Loading, PageHead, useApi } from "@/components/ui";
import { brl, date } from "@/lib/format";

interface AdminSub {
  id: string;
  user_email: string;
  plan_name: string;
  price: string;
  status: string;
  mp_preapproval_id: string | null;
  next_payment_at: string | null;
  created_at: string;
}

const STATUS: Record<string, string> = { active: "Ativa", pending: "Aguardando pagamento", paused: "Pausada", past_due: "Pagamento recusado", cancelled: "Cancelada" };

export default function AdminSubscriptions() {
  const [status, setStatus] = useState("");
  const { data } = useApi<AdminSub[]>(`/admin/subscriptions${status ? `?status=${status}` : ""}`);
  return (
    <>
      <PageHead title="Assinaturas">
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filtrar por situação">
          <option value="">Todas</option>
          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </PageHead>
      {!data ? (
        <Loading />
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Assinante</th><th>Plano</th><th className="num">Valor</th><th>Situação</th><th>Origem</th><th>Próxima cobrança</th><th>Criada</th></tr></thead>
            <tbody>
              {data.map((s) => (
                <tr key={s.id}>
                  <td>{s.user_email}</td>
                  <td>{s.plan_name}</td>
                  <td className="num">{brl(s.price)}</td>
                  <td className={s.status === "past_due" ? "loss" : s.status === "active" ? "gain" : ""}>{STATUS[s.status] ?? s.status}</td>
                  <td className="muted">{s.mp_preapproval_id ? `Mercado Pago ${s.mp_preapproval_id}` : "Cortesia"}</td>
                  <td>{date(s.next_payment_at)}</td>
                  <td>{date(s.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.length === 0 && <div className="empty">Nenhuma assinatura.</div>}
        </div>
      )}
    </>
  );
}
