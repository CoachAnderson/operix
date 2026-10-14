"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Loading, PageHead, StatusTag, Stripe, VenueTag, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { MODE_LABEL, pnlClass, signed } from "@/lib/format";
import type { Bot, BotSummary, StrategyInfo, Subscription } from "@/lib/types";

export default function BotsPage() {
  const { data: bots, loading, error } = useApi<Bot[]>("/bots");
  const { data: sub } = useApi<Subscription | null>("/billing/subscription");
  const { data: strategies } = useApi<StrategyInfo[]>("/strategies");
  const [summaries, setSummaries] = useState<Record<string, BotSummary>>({});

  useEffect(() => {
    if (!bots?.length) return;
    Promise.all(bots.map((b) => api<BotSummary>(`/bots/${b.id}`).catch(() => null))).then((list) =>
      setSummaries(Object.fromEntries(list.filter(Boolean).map((s) => [s!.bot.id, s!]))),
    );
  }, [bots]);

  const active = sub?.status === "active";
  const strategyName = (code: string) => strategies?.find((s) => s.code === code)?.name ?? code;

  return (
    <>
      <PageHead title="Robôs" lead={active ? `Plano ${sub!.plan.name}, até ${sub!.plan.max_bots} robôs` : undefined}>
        {active && (
          <Link className="btn btn-primary" href="/painel/robos/novo">
            Criar robô
          </Link>
        )}
      </PageHead>

      {sub && !active && (
        <div className="notice" style={{ marginBottom: 20 }}>
          <strong>{sub.status === "past_due" ? "Pagamento recusado" : "Assinatura inativa"}</strong>
          Seus robôs ficam pausados até a assinatura ser regularizada. <Link href="/painel/assinatura">Ver assinatura</Link>
        </div>
      )}
      {!sub && (
        <div className="notice" style={{ marginBottom: 20 }}>
          <strong>Escolha um plano para começar</strong>
          Todo plano inclui a simulação, para você testar sem arriscar dinheiro. <Link href="/painel/assinatura">Ver planos</Link>
        </div>
      )}

      {loading && <Loading />}
      {error && <p className="loss">{error}</p>}
      {bots && bots.length === 0 && active && (
        <div className="panel empty">
          <p style={{ margin: "0 auto 14px" }}>Nenhum robô ainda. Crie o primeiro na simulação: preços reais, saldo fictício.</p>
          <Link className="btn btn-primary" href="/painel/robos/novo">
            Criar robô
          </Link>
        </div>
      )}

      <div className="ledger">
        {bots?.map((b) => {
          const s = summaries[b.id];
          return (
            <Link key={b.id} href={`/painel/robos/${b.id}`} className="entry">
              <Stripe venue={b.venue} />
              <div className="entry-body">
                <div>
                  <div className="title">{b.name}</div>
                  <div className="muted small">
                    {b.symbol}, {strategyName(b.strategy)}
                  </div>
                </div>
                <div className="small" style={{ display: "grid", gap: 2 }}>
                  <VenueTag venue={b.venue} market={b.market} />
                  <span className="muted">
                    {b.market === "forex" ? `Forex, ${MODE_LABEL[b.exec_mode].toLowerCase()}` : MODE_LABEL[b.exec_mode]}
                  </span>
                </div>
                <div>
                  <StatusTag status={b.status} />
                  {b.status_reason && b.status !== "running" && <div className="muted small">{b.status_reason}</div>}
                </div>
                <div className={`figure ${pnlClass(s?.realized_pnl_today)}`} title="Resultado realizado hoje (moeda de cotação)">
                  {s ? signed(s.realized_pnl_today) : "—"}
                  <div className="muted small" style={{ fontWeight: 400 }}>hoje</div>
                </div>
              </div>
            </Link>
          );
        })}
      </div>
    </>
  );
}
