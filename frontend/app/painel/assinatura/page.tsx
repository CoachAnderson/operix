"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { PlanList } from "@/components/PlanList";
import { ErrorText, Loading, PageHead, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { date } from "@/lib/format";
import type { Plan, Subscription } from "@/lib/types";

const STATUS: Record<Subscription["status"], string> = {
  active: "Ativa",
  pending: "Aguardando pagamento",
  paused: "Pausada",
  past_due: "Pagamento recusado",
  cancelled: "Cancelada",
};

function SubscriptionView() {
  const back = useSearchParams().get("retorno");
  const plans = useApi<Plan[]>("/billing/plans");
  const sub = useApi<Subscription | null>("/billing/subscription");
  const action = useAction();
  const [busyId, setBusyId] = useState<string | null>(null);

  async function choose(p: Plan) {
    setBusyId(p.id);
    const res = await action.run(() => api<{ checkout_url: string }>("/billing/checkout", { json: { plan_id: p.id } }));
    setBusyId(null);
    if (res?.checkout_url) window.location.href = res.checkout_url;
  }

  async function cancel() {
    if (!window.confirm("Cancelar a assinatura? Os robôs param quando ela for encerrada.")) return;
    await action.run(() => api("/billing/cancel", { method: "POST" }));
    await sub.reload();
  }

  const current = sub.data;
  const active = current?.status === "active";

  if (current?.source === "admin") {
    return (
      <>
        <PageHead title="Assinatura" />
        <div className="notice">
          <strong>Acesso ilimitado de administrador</strong>
          Sua conta é de administrador: todos os robôs e recursos liberados, sem limite de robôs e sem cobrança.
        </div>
      </>
    );
  }
  const manual = active && current?.source === "manual";

  return (
    <>
      <PageHead title="Assinatura" lead="Cobrança mensal pelo Mercado Pago. Cancele quando quiser." />
      {back && current?.status === "pending" && (
        <div className="notice" style={{ marginBottom: 20 }}>
          <strong>Pagamento em análise</strong>
          Assim que o Mercado Pago confirmar, sua assinatura é ativada. Isso costuma levar poucos minutos.{" "}
          <button className="btn btn-quiet" onClick={() => sub.reload()}>Atualizar</button>
        </div>
      )}
      {sub.loading && !current && <Loading />}
      {current && (
        <dl className="figures" style={{ marginBottom: 32 }}>
          <div><dt>Plano</dt><dd>{current.plan.name}</dd></div>
          <div><dt>Situação</dt><dd className={active ? "gain" : current.status === "past_due" ? "loss" : ""}>{STATUS[current.status]}</dd></div>
          {manual ? (
            <div><dt>Liberado pela administração</dt><dd>{current.expires_at ? `até ${date(current.expires_at)}` : "sem prazo"}</dd></div>
          ) : (
            <div><dt>Próxima cobrança</dt><dd>{date(current.next_payment_at)}</dd></div>
          )}
        </dl>
      )}
      <ErrorText>{action.error}</ErrorText>
      <h2 style={{ marginBottom: 14 }}>{active ? "Trocar de plano" : "Escolha um plano"}</h2>
      {plans.data ? (
        <PlanList plans={plans.data} currentPlanId={active ? current!.plan.id : undefined} onChoose={choose} busyId={busyId} chooseLabel={active ? "Mudar para este plano" : "Assinar"} />
      ) : (
        <Loading />
      )}
      {manual && (
        <p className="muted small" style={{ marginTop: 16 }}>
          Seu acesso foi liberado pela administração, sem cobrança. Se assinar um plano, a cobrança começa a valer quando o pagamento for confirmado.
        </p>
      )}
      {active && !manual && (
        <p className="muted small" style={{ marginTop: 16 }}>
          Ao mudar de plano, a assinatura atual é cancelada assim que a nova for confirmada.{" "}
          <button className="btn btn-quiet loss" onClick={cancel} disabled={action.busy}>Cancelar assinatura</button>
        </p>
      )}
    </>
  );
}

export default function SubscriptionPage() {
  return (
    <Suspense>
      <SubscriptionView />
    </Suspense>
  );
}
