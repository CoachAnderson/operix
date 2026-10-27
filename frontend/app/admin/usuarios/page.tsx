"use client";

import { useState } from "react";
import { ErrorText, Loading, PageHead, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { date, dateTime } from "@/lib/format";
import type { Access, Plan, User } from "@/lib/types";

const tight = { paddingInline: 6 };

const DURATIONS: { value: string; label: string }[] = [
  { value: "7", label: "7 dias" },
  { value: "30", label: "30 dias" },
  { value: "90", label: "90 dias" },
  { value: "365", label: "1 ano" },
  { value: "", label: "Sem prazo (até cancelar)" },
];

function AccessCell({ a }: { a?: Access | null }) {
  if (!a || a.source === "none") return <span className="muted">Sem acesso</span>;
  if (a.source === "admin") return <span className="gain">Ilimitado (admin)</span>;
  const expired = a.expires_at && new Date(a.expires_at) < new Date();
  return (
    <span>
      {a.plan_name}
      <span className="muted small">
        {" · "}
        {a.source === "mercadopago" ? "pago" : a.expires_at ? `liberado até ${date(a.expires_at)}` : "liberado sem prazo"}
      </span>
      {expired && <span className="loss small"> (vencido)</span>}
    </span>
  );
}

export default function AdminUsers() {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const users = useApi<User[]>(`/admin/users?q=${encodeURIComponent(query)}`);
  const plans = useApi<Plan[]>("/admin/plans");
  const action = useAction();
  const [grant, setGrant] = useState<{ user: User; plan_id: string; days: string; note: string } | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function setStatus(u: User, status: "active" | "suspended") {
    const msg =
      status === "suspended"
        ? `Suspender ${u.email}? A pessoa não consegue mais entrar, os robôs param e as sessões caem. A cobrança no Mercado Pago continua até ser cancelada lá (use "Cancelar acesso" para cancelar a cobrança também).`
        : `Reativar ${u.email}?`;
    if (!window.confirm(msg)) return;
    await action.run(() => api(`/admin/users/${u.id}`, { method: "PATCH", json: { status } }));
    await users.reload();
  }

  async function submitGrant(e: React.FormEvent) {
    e.preventDefault();
    if (!grant) return;
    const body = { plan_id: grant.plan_id, note: grant.note, days: grant.days ? Number(grant.days) : null };
    const ok = await action.run(() => api(`/admin/users/${grant.user.id}/grant-plan`, { json: body }));
    if (ok) {
      setDone(`Acesso liberado para ${grant.user.email}. Robôs pausados por falta de plano voltam a operar sozinhos.`);
      setGrant(null);
      await users.reload();
    }
  }

  async function revoke(u: User) {
    const paid = u.access?.source === "mercadopago";
    const msg = paid
      ? `Cancelar o acesso de ${u.email}?\n\nA assinatura paga também será cancelada no Mercado Pago (sem novas cobranças) e os robôs ligados serão pausados. A pessoa continua entrando e vendo o histórico.`
      : `Cancelar o acesso de ${u.email}?\n\nOs robôs ligados serão pausados. A pessoa continua entrando, vendo o histórico e pode assinar de novo.`;
    if (!window.confirm(msg)) return;
    const res = await action.run(() =>
      api<{ cancelled: number; paid_cancelled: number; bots_paused: number }>(`/admin/users/${u.id}/revoke-access`, { json: { cancel_billing: true } }),
    );
    if (res) {
      setDone(
        `Acesso de ${u.email} cancelado: ${res.bots_paused} robô(s) pausado(s)${res.paid_cancelled ? `, cobrança no Mercado Pago cancelada` : ""}.`,
      );
      await users.reload();
    }
  }

  return (
    <>
      <PageHead title="Usuários" lead="Libere ou cancele o acesso aos robôs. Administradores têm acesso ilimitado, sem assinatura.">
        <form className="actions" onSubmit={(e) => { e.preventDefault(); setQuery(q); }}>
          <input type="search" placeholder="Nome ou e-mail" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 240, maxWidth: "100%" }} />
          <button className="btn">Buscar</button>
        </form>
      </PageHead>
      <ErrorText>{action.error}</ErrorText>
      {done && (
        <p className="rb-verdict gain" role="status" style={{ marginBottom: 16 }}>
          {done}{" "}
          <button className="btn btn-quiet" onClick={() => setDone(null)}>Fechar</button>
        </p>
      )}

      {grant && (
        <form className="panel form" onSubmit={submitGrant} style={{ marginBottom: 20 }}>
          <h2>Liberar acesso para {grant.user.email}</h2>
          <p className="muted small">
            Ativa o plano sem cobrança (cortesia, parceria, teste). Substitui outra liberação manual que a pessoa já tenha. Fica registrado na auditoria.
            {grant.user.access?.source === "mercadopago" && " Atenção: ela já tem assinatura paga ativa, que continua sendo cobrada."}
          </p>
          <label>
            Plano
            <select required value={grant.plan_id} onChange={(e) => setGrant({ ...grant, plan_id: e.target.value })}>
              <option value="">Escolha…</option>
              {plans.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} · até {p.max_bots} robôs{p.allow_auto ? " · automático" : " · só sinais"}
                </option>
              ))}
            </select>
          </label>
          <label>
            Por quanto tempo
            <select value={grant.days} onChange={(e) => setGrant({ ...grant, days: e.target.value })}>
              {DURATIONS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
            </select>
          </label>
          <label>
            Observação
            <input value={grant.note} maxLength={300} onChange={(e) => setGrant({ ...grant, note: e.target.value })} placeholder="Ex.: parceria, teste interno" />
          </label>
          <div className="actions">
            <button className="btn btn-primary" disabled={action.busy}>Liberar acesso</button>
            <button type="button" className="btn btn-quiet" onClick={() => setGrant(null)}>Voltar</button>
          </div>
        </form>
      )}

      {!users.data ? (
        <Loading />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Usuário</th><th>Papel</th><th>Acesso aos robôs</th><th>Conta</th><th>Último acesso</th><th><span className="sr-only">Ações</span></th></tr>
            </thead>
            <tbody>
              {users.data.map((u) => {
                const isAdmin = u.role === "admin";
                const hasAccess = !!u.access && u.access.source !== "none" && !isAdmin;
                return (
                  <tr key={u.id}>
                    <td>
                      <strong>{u.name}</strong>
                      <div className="muted small">{u.email}</div>
                    </td>
                    <td>
                      {isAdmin ? "Admin" : "Assinante"}
                      <div className="muted small">2FA {u.totp_enabled ? "ativo" : "inativo"}</div>
                    </td>
                    <td><AccessCell a={u.access} /></td>
                    <td className={u.status === "suspended" ? "loss" : ""}>{u.status === "active" ? "Ativa" : "Suspensa"}</td>
                    <td>
                      {dateTime(u.last_login_at)}
                      <div className="muted small">desde {date(u.created_at)}</div>
                    </td>
                    <td className="num">
                      <div className="actions" style={{ justifyContent: "flex-end", gap: "0 4px", flexWrap: "wrap", whiteSpace: "nowrap", minWidth: 200 }}>
                        {!isAdmin && (
                          <button className="btn btn-quiet" style={tight} onClick={() => { setDone(null); setGrant({ user: u, plan_id: "", days: "30", note: "" }); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
                            {hasAccess ? "Trocar plano" : "Liberar acesso"}
                          </button>
                        )}
                        {hasAccess && (
                          <button className="btn btn-quiet loss" style={tight} onClick={() => revoke(u)} disabled={action.busy}>Cancelar acesso</button>
                        )}
                        {u.status === "active" ? (
                          <button className="btn btn-quiet loss" style={tight} onClick={() => setStatus(u, "suspended")}>Suspender</button>
                        ) : (
                          <button className="btn btn-quiet" style={tight} onClick={() => setStatus(u, "active")}>Reativar</button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {users.data.length === 0 && <div className="empty">Nenhum usuário encontrado.</div>}
        </div>
      )}
      <p className="muted small" style={{ marginTop: 12 }}>
        <strong>Cancelar acesso</strong> pausa os robôs e encerra a liberação ou a assinatura (cancelando a cobrança no Mercado Pago), mas a pessoa continua
        entrando. <strong>Suspender</strong> bloqueia a conta inteira.
      </p>
    </>
  );
}
