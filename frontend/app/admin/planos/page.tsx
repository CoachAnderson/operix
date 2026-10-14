"use client";

import { useState } from "react";
import { planFeatures } from "@/components/PlanList";
import { ErrorText, Loading, PageHead, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { brl } from "@/lib/format";
import type { Plan } from "@/lib/types";

type Draft = Omit<Plan, "id" | "price_monthly"> & { id?: string; price_monthly: string; sort_order: number };
const EMPTY: Draft = { code: "", name: "", description: "", price_monthly: "", max_bots: 1, allow_auto: false, allow_live: false, active: true, sort_order: 0 };

export default function AdminPlans() {
  const plans = useApi<Plan[]>("/admin/plans");
  const action = useAction();
  const [draft, setDraft] = useState<Draft | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!draft) return;
    const { id, ...body } = draft;
    const ok = await action.run(() => api(id ? `/admin/plans/${id}` : "/admin/plans", { method: id ? "PUT" : "POST", json: body }));
    if (ok) {
      setDraft(null);
      await plans.reload();
    }
  }

  return (
    <>
      <PageHead title="Planos" lead="Mudar o preço vale para novas assinaturas. Quem já assina segue no valor contratado.">
        {!draft && <button className="btn btn-primary" onClick={() => setDraft({ ...EMPTY })}>Criar plano</button>}
      </PageHead>

      {draft && (
        <form className="panel form" onSubmit={save} style={{ marginBottom: 24 }}>
          <h2>{draft.id ? `Editar ${draft.name}` : "Novo plano"}</h2>
          <div className="grid-2">
            <label>Nome<input required value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
            <label>Código<span className="hint">Minúsculas, sem espaço</span><input required pattern="[a-z0-9_-]{2,40}" value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value })} /></label>
            <label>Preço mensal (R$)<input required type="number" min="1" step="0.01" value={draft.price_monthly} onChange={(e) => setDraft({ ...draft, price_monthly: e.target.value })} /></label>
            <label>Máximo de robôs<input required type="number" min="1" max="100" value={draft.max_bots} onChange={(e) => setDraft({ ...draft, max_bots: Number(e.target.value) })} /></label>
            <label>Ordem de exibição<input type="number" value={draft.sort_order} onChange={(e) => setDraft({ ...draft, sort_order: Number(e.target.value) })} /></label>
          </div>
          <label>Descrição<input value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></label>
          <label className="check"><input type="checkbox" checked={draft.allow_auto} onChange={(e) => setDraft({ ...draft, allow_auto: e.target.checked })} />Permite execução automática</label>
          <label className="check"><input type="checkbox" checked={draft.allow_live} onChange={(e) => setDraft({ ...draft, allow_live: e.target.checked })} />Permite conta real</label>
          <label className="check"><input type="checkbox" checked={draft.active} onChange={(e) => setDraft({ ...draft, active: e.target.checked })} />Disponível para novas assinaturas</label>
          <ErrorText>{action.error}</ErrorText>
          <div className="actions">
            <button className="btn btn-primary" disabled={action.busy}>Salvar plano</button>
            <button type="button" className="btn btn-quiet" onClick={() => setDraft(null)}>Cancelar</button>
          </div>
        </form>
      )}

      {!plans.data ? (
        <Loading />
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Plano</th><th className="num">Preço</th><th>Inclui</th><th>Situação</th><th /></tr></thead>
            <tbody>
              {plans.data.map((p) => (
                <tr key={p.id}>
                  <td>{p.name}<div className="muted small">{p.code}</div></td>
                  <td className="num">{brl(p.price_monthly)}</td>
                  <td className="muted small" style={{ whiteSpace: "normal" }}>{planFeatures(p).slice(0, 3).join("; ")}</td>
                  <td>{p.active ? "Disponível" : "Oculto"}</td>
                  <td className="num">
                    <button className="btn btn-quiet" onClick={() => setDraft({ ...p, sort_order: (p as Plan & { sort_order?: number }).sort_order ?? 0 })}>Editar</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
