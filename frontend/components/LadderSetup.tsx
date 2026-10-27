"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import { dcaPlan, gridPreview, type LadderParams } from "@/lib/ladder";

const px = (v: number | null | undefined) => (v === null || v === undefined ? "—" : money(v, v >= 100 ? 2 : v >= 1 ? 4 : 8));

/** Preço atual do par na Binance (para mostrar a faixa da grade em preço). */
export function usePairPrice(symbol: string) {
  const [price, setPrice] = useState<number | null>(null);
  useEffect(() => {
    const s = symbol.trim().toUpperCase().replace("/", "");
    if (!/^[A-Z0-9]{5,20}$/.test(s)) return;
    let stop = false;
    const t = setTimeout(async () => {
      try {
        const r = await api<{ price: number }>(`/market/price?symbol=${s}`);
        if (!stop) setPrice(r.price);
      } catch {
        if (!stop) setPrice(null);
      }
    }, 400);
    return () => {
      stop = true;
      clearTimeout(t);
    };
  }, [symbol]);
  return price;
}

/** Resumo do que a grade/o ciclo vai fazer e quanto dinheiro precisa, antes de criar ou testar. */
export function LadderSetup({
  code,
  params,
  size,
  balance,
  symbol,
  quote = "USDT",
}: {
  code: string;
  params: LadderParams;
  size: number;
  balance: number | null;
  symbol: string;
  quote?: string;
}) {
  const price = usePairPrice(symbol);
  const short = balance !== null && Number.isFinite(balance);
  if (code === "grade_spot") {
    const g = gridPreview(params, size, price);
    const cost = 0.2;
    return (
      <div className="panel" style={{ display: "grid", gap: 10 }}>
        <strong>Como a grade fica{price !== null ? ` com o preço de agora (${px(price)})` : ""}</strong>
        <dl className="figures" style={{ margin: 0 }}>
          <div>
            <dt>Faixa</dt>
            <dd style={{ fontSize: "1rem" }}>{g.lower !== null ? `${px(g.lower)} a ${px(g.upper)}` : "—"}</dd>
            <span className="muted small">{params.range_mode === "manual" ? "preços fixos" : `${params.lower_pct || 10}% abaixo e ${params.upper_pct || 10}% acima da partida`}</span>
          </div>
          <div>
            <dt>Cada grade</dt>
            <dd className={g.stepMin !== null && g.stepMin < cost * 2.5 ? "loss" : ""}>{g.stepMin !== null ? `${money(g.stepMin, 2)}%` : "—"}</dd>
            <span className="muted small">sobra ~{g.stepMin !== null ? money(Math.max(0, g.stepMin - cost), 2) : "—"}% por venda, depois das taxas</span>
          </div>
          <div>
            <dt>Dinheiro necessário</dt>
            <dd>{money(g.capital)}</dd>
            <span className="muted small">{g.grids} lotes × {money(size)} {quote}</span>
          </div>
          <div>
            <dt>Compra na partida</dt>
            <dd>{g.initial !== null ? `${g.initial} lote(s)` : "—"}</dd>
            <span className="muted small">{g.initialCost !== null ? `${money(g.initialCost)} ${quote}, a mercado` : "as grades acima do preço"}</span>
          </div>
        </dl>
        {g.stepMin !== null && g.stepMin < cost * 2.5 && (
          <p className="loss small" style={{ margin: 0 }}>
            Cada grade rende pouco perto do custo de ida e volta (~0,2% de taxa mais o escorregamento). Use menos grades ou uma faixa maior.
          </p>
        )}
        {g.outside && <p className="warn-text small" style={{ margin: 0 }}>O preço de agora está fora da faixa: o robô espera ele entrar (abaixo) ou fica só com dinheiro (acima).</p>}
        {short && balance! < g.capital && (
          <p className="loss small" style={{ margin: 0 }}>
            O saldo ({money(balance!)}) não cobre o dinheiro necessário ({money(g.capital)}). Aumente o saldo ou reduza as grades ou o valor por lote.
          </p>
        )}
      </div>
    );
  }
  const d = dcaPlan(params, size);
  return (
    <div className="panel" style={{ display: "grid", gap: 10 }}>
      <strong>Compras de cada ciclo</strong>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Compra</th>
              <th className="num">{d.byTime ? "Quando" : "Queda desde a 1ª"}</th>
              <th className="num">Valor ({quote})</th>
              {price !== null && !d.byTime && <th className="num">Preço (se começasse agora)</th>}
            </tr>
          </thead>
          <tbody>
            {d.orders.map((o) => (
              <tr key={o.k}>
                <td>{o.k + 1}ª</td>
                <td className="num">{o.k === 0 ? "na partida" : d.byTime ? `+${money(Number(params.interval_hours || 24) * o.k, 0)} h` : `−${money(o.drop, 2)}%`}</td>
                <td className="num">{money(o.quote)}</td>
                {price !== null && !d.byTime && <td className="num">{px(price * (1 - o.drop / 100))}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="small" style={{ margin: 0 }}>
        Dinheiro necessário por ciclo: <strong>{money(d.capital)} {quote}</strong>. Vende tudo com {params.take_profit_pct || 2}% acima do custo médio
        {params.stop_loss_pct ? `; stop com ${params.stop_loss_pct}% abaixo dele` : "; sem stop (espera a volta do preço)"}.
      </p>
      {short && balance! < d.capital && (
        <p className="loss small" style={{ margin: 0 }}>
          O saldo ({money(balance!)}) não cobre todas as compras do ciclo ({money(d.capital)}). Aumente o saldo ou reduza as compras ou o valor.
        </p>
      )}
    </div>
  );
}
