"use client";

import { brl } from "@/lib/format";
import type { Plan } from "@/lib/types";

export function planFeatures(p: Plan): string[] {
  return [
    `Até ${p.max_bots} robô${p.max_bots > 1 ? "s" : ""}`,
    p.allow_auto ? "Execução automática e por sinais" : "Somente sinais: você confirma cada ordem",
    p.allow_live ? "Simulação, testnet e conta real" : "Simulação e testnet",
    "Estratégias de day trade e swing trade",
  ];
}

export function PlanList({
  plans,
  currentPlanId,
  onChoose,
  busyId,
  chooseLabel = "Assinar",
}: {
  plans: Plan[];
  currentPlanId?: string;
  onChoose: (p: Plan) => void;
  busyId?: string | null;
  chooseLabel?: string;
}) {
  return (
    <div className="plans">
      {plans.map((p) => {
        const current = p.id === currentPlanId;
        return (
          <article key={p.id} className={`plan${current ? " current" : ""}`}>
            <h2>{p.name}</h2>
            <div>
              <span className="price">{brl(p.price_monthly)}</span>
              <span className="muted"> por mês</span>
            </div>
            {p.description && <p className="muted">{p.description}</p>}
            <ul>
              {planFeatures(p).map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
            <button className={`btn ${current ? "" : "btn-primary"}`} disabled={current || busyId === p.id} onClick={() => onChoose(p)}>
              {current ? "Seu plano atual" : busyId === p.id ? "Abrindo pagamento…" : chooseLabel}
            </button>
          </article>
        );
      })}
    </div>
  );
}
