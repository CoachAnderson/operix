"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { PlanList } from "@/components/PlanList";
import { Stripe, useApi } from "@/components/ui";
import { VENUE_HINT, VENUE_LABEL } from "@/lib/format";
import type { Plan, Venue } from "@/lib/types";
import { BRAND } from "@/lib/brand";

const DEMO: Venue[] = ["paper", "testnet", "live"];

export default function Home() {
  const router = useRouter();
  const { data: plans } = useApi<Plan[]>("/billing/plans");

  return (
    <div className="landing">
      <header className="landing-top">
        <span className="brand">{BRAND}</span>
        <div className="actions">
          <Link className="btn btn-quiet" href="/entrar">Entrar</Link>
          <Link className="btn btn-primary" href="/cadastro">Criar conta</Link>
        </div>
      </header>

      <section className="hero">
        <div>
          <h1>Teste a estratégia antes de arriscar um centavo.</h1>
          <p>
            Robôs de day trade e swing trade para cripto (Binance) e forex (cTrader). Comece na simulação com preços reais, passe pela testnet ou conta demo e
            só leve para a conta real quando os números convencerem você.
          </p>
          <div className="actions">
            <Link className="btn btn-primary" href="/cadastro">Começar na simulação</Link>
            <a className="btn btn-quiet" href="#planos">Ver planos</a>
          </div>
        </div>
        <div className="venue-demo" aria-label="Os três ambientes de execução">
          {DEMO.map((v) => (
            <div key={v} className="entry">
              <Stripe venue={v} />
              <div className="entry-body">
                <div>
                  <div className="title">{VENUE_LABEL[v]}</div>
                  <div className="muted small">{VENUE_HINT[v]}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="section" id="planos">
        <h2 style={{ marginBottom: 16 }}>Planos</h2>
        {plans ? <PlanList plans={plans} onChoose={() => router.push("/cadastro")} chooseLabel="Criar conta" /> : <p className="muted">Carregando planos…</p>}
      </section>

      <p className="disclaimer">
        O {BRAND} é uma ferramenta de software. Você conecta a sua própria conta, escolhe a estratégia e define os limites
        de risco; a plataforma não guarda seus recursos e não faz recomendação de investimento. Operar criptoativos
        e forex (com alavancagem) envolve risco de perda, inclusive total, e resultados passados ou simulados não garantem resultados futuros.
      </p>
    </div>
  );
}
