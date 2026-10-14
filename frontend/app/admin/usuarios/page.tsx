"use client";

import { useState } from "react";
import { ErrorText, Loading, PageHead, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { date, dateTime } from "@/lib/format";
import type { Plan, User } from "@/lib/types";

export default function AdminUsers() {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const users = useApi<User[]>(`/admin/users?q=${encodeURIComponent(query)}`);
  const plans = useApi<Plan[]>("/admin/plans");
  const action = useAction();
  const [grant, setGrant] = useState<{ user: User; plan_id: string; note: string } | null>(null);

  async function setStatus(u: User, status: "active" | "suspended") {
    const msg = status === "suspended" ? `Suspender ${u.email}? Os robôs param e as sessões caem. A cobrança no Mercado Pago continua até ser cancelada lá.` : `Reativar ${u.email}?`;
    if (!window.confirm(msg)) return;
    await action.run(() => api(`/admin/users/${u.id}`, { method: "PATCH", json: { status } }));
    await users.reload();
  }

  async function submitGrant(e: React.FormEvent) {
    e.preventDefault();
    if (!grant) return;
    const ok = await action.run(() => api(`/admin/users/${grant.user.id}/grant-plan`, { json: { plan_id: grant.plan_id, note: grant.note } }));
    if (ok) setGrant(null);
  }

  return (
    <>
      <PageHead title="Usuários">
        <form className="actions" onSubmit={(e) => { e.preventDefault(); setQuery(q); }}>
          <input type="search" placeholder="Nome ou e-mail" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 240 }} />
          <button className="btn">Buscar</button>
        </form>
      </PageHead>
      <ErrorText>{action.error}</ErrorText>

      {grant && (
        <form className="panel form" onSubmit={submitGrant} style={{ marginBottom: 20 }}>
          <h2>Conceder plano para {grant.user.email}</h2>
          <p className="muted small">Ativa o plano sem cobrança (cortesia, parceria, teste interno). Fica registrado na auditoria.</p>
          <label>
            Plano
            <select required value={grant.plan_id} onChange={(e) => setGrant({ ...grant, plan_id: e.target.value })}>
              <option value="">Escolha…</option>
              {plans.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <label>
            Observação
            <input value={grant.note} onChange={(e) => setGrant({ ...grant, note: e.target.value })} />
          </label>
          <div className="actions">
            <button className="btn btn-primary" disabled={action.busy}>Conceder plano</button>
            <button type="button" className="btn btn-quiet" onClick={() => setGrant(null)}>Cancelar</button>
          </div>
        </form>
      )}

      {!users.data ? (
        <Loading />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Nome</th><th>E-mail</th><th>Papel</th><th>2FA</th><th>Situação</th><th>Cadastro</th><th>Último acesso</th><th /></tr>
            </thead>
            <tbody>
              {users.data.map((u) => (
                <tr key={u.id}>
                  <td>{u.name}</td>
                  <td>{u.email}</td>
                  <td>{u.role === "admin" ? "Admin" : "Assinante"}</td>
                  <td>{u.totp_enabled ? "Sim" : "Não"}</td>
                  <td className={u.status === "suspended" ? "loss" : ""}>{u.status === "active" ? "Ativo" : "Suspenso"}</td>
                  <td>{date(u.created_at)}</td>
                  <td>{dateTime(u.last_login_at)}</td>
                  <td className="num">
                    <div className="actions" style={{ justifyContent: "flex-end" }}>
                      <button className="btn btn-quiet" onClick={() => setGrant({ user: u, plan_id: "", note: "" })}>Conceder plano</button>
                      {u.status === "active" ? (
                        <button className="btn btn-quiet loss" onClick={() => setStatus(u, "suspended")}>Suspender</button>
                      ) : (
                        <button className="btn btn-quiet" onClick={() => setStatus(u, "active")}>Reativar</button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {users.data.length === 0 && <div className="empty">Nenhum usuário encontrado.</div>}
        </div>
      )}
    </>
  );
}
