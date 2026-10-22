"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import type { SizingPreview as Preview } from "@/lib/types";

const n = (v: string | null | undefined) => (v === null || v === undefined ? NaN : Number(v));

function cur(currency: string | undefined, v: number): string {
  const c = currency || "";
  return c === "BRL" ? `R$ ${money(v)}` : `${money(v)} ${c}`.trim();
}

/** Nível de alavancagem em palavras, para o cliente entender sem fórmula. */
function levelOf(x: number): { tone: string; text: string } {
  if (x <= 1) return { tone: "gain", text: "sem alavancagem" };
  if (x <= 5) return { tone: "", text: "alavancagem moderada" };
  if (x <= 20) return { tone: "warn", text: "alavancagem alta" };
  return { tone: "loss", text: "alavancagem muito alta" };
}

export function PreviewCard({ data, loading }: { data: Preview | null; loading?: boolean }) {
  if (loading && !data) return <div className="sz-card muted small">Calculando com o saldo e o preço de agora…</div>;
  if (!data) return null;
  if (!data.ok) {
    return (
      <div className="sz-card sz-blocked" role="status">
        <strong>Prévia</strong>
        <span>{data.message}</span>
      </div>
    );
  }
  const lev = n(data.leverage);
  const bal = n(data.balance);
  const notional = n(data.notional);
  const level = Number.isNaN(lev) ? null : levelOf(lev);
  const size = data.unit ? `${data.unit === "contratos" ? money(n(data.lots), 0) : money(n(data.lots))} ${data.unit}` : cur(data.currency, n(data.quote_amount));
  return (
    <div className={`sz-card ${loading ? "is-loading" : ""}`} role="status" aria-live="polite">
      <strong>Prévia da próxima entrada</strong>
      <dl className="sz-facts">
        <div>
          <dt>Tamanho</dt>
          <dd>{size}</dd>
        </div>
        <div>
          <dt>Valor movimentado</dt>
          <dd>{cur(data.currency, notional)}</dd>
        </div>
        <div>
          <dt>Saldo da conta</dt>
          <dd>{Number.isNaN(bal) ? "—" : cur(data.currency, bal)}</dd>
        </div>
        <div>
          <dt>Alavancagem efetiva</dt>
          <dd className={level?.tone ?? ""}>{Number.isNaN(lev) ? "—" : `${money(lev, lev < 10 ? 1 : 0)}×`}</dd>
        </div>
        <div>
          <dt>Se o stop for atingido</dt>
          <dd className="loss">
            {data.risk_money ? `−${cur(data.currency, n(data.risk_money))}` : "sem stop"}
            {data.risk_pct ? <span className="sz-sub"> ({money(n(data.risk_pct), 2)}% do saldo)</span> : null}
          </dd>
        </div>
      </dl>
      {level && !Number.isNaN(bal) && (
        <p className="small">
          Cada ordem movimenta {cur(data.currency, notional)}, {money(lev, 1)} vezes o saldo: <strong className={level.tone}>{level.text}</strong>.
          {lev > 1 && ` Uma variação de 1% no preço mexe ${money(lev, 1)}% no seu saldo.`}
        </p>
      )}
      {data.note && <p className="small warn-text">{data.note}.</p>}
      {data.unit === "lotes" && (
        <p className="muted small">Valores na moeda de cotação do par (USD no EURUSD). Se a conta for em outra moeda, os números são aproximados.</p>
      )}
      <p className="muted small">Calculado agora com o preço {data.price ? money(n(data.price), n(data.price) < 10 ? 5 : 2) : ""} e o saldo da conta; custos não incluídos. Muda a cada operação.</p>
    </div>
  );
}

/** Prévia que se atualiza sozinha quando a configuração muda (espera 0,7 s entre alterações). */
export function LiveSizingPreview({ body, enabled }: { body: Record<string, unknown>; enabled: boolean }) {
  const [data, setData] = useState<Preview | null>(null);
  const [loading, setLoading] = useState(false);
  const key = JSON.stringify(body);
  const seq = useRef(0);
  useEffect(() => {
    if (!enabled) return;
    const id = ++seq.current;
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await api<Preview>("/bots/sizing-preview", { json: JSON.parse(key) });
        if (id === seq.current) setData(res);
      } catch (e) {
        if (id === seq.current) setData({ ok: false, message: e instanceof Error ? e.message : "Não foi possível calcular a prévia" });
      } finally {
        if (id === seq.current) setLoading(false);
      }
    }, 700);
    return () => clearTimeout(t);
  }, [key, enabled]);
  if (!enabled) return <div className="sz-card muted small">Escolha a estratégia e a conexão para ver a prévia do tamanho e da alavancagem.</div>;
  return <PreviewCard data={data} loading={loading} />;
}
