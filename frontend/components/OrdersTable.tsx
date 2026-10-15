"use client";

import { B3_POINT_VALUE, dateTime, money, price, pnlClass, qty, signed } from "@/lib/format";
import type { Order } from "@/lib/types";
import { VenueTag } from "./ui";

const STATUS: Record<string, string> = {
  FILLED: "Executada",
  PARTIALLY_FILLED: "Parcial",
  NEW: "Enviando",
  UNKNOWN: "Conferindo",
  REJECTED: "Recusada",
  CANCELED: "Cancelada",
};

export function OrdersTable({ orders, showVenue = false }: { orders: Order[]; showVenue?: boolean }) {
  if (!orders.length) return <div className="table-wrap empty">Nenhuma ordem ainda.</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Quando</th>
            {showVenue && <th>Ambiente</th>}
            <th>Par</th>
            <th>Lado</th>
            <th className="num">Quantidade</th>
            <th className="num">Preço médio</th>
            <th className="num">Taxa</th>
            <th className="num">Resultado</th>
            <th>Situação</th>
            <th>Motivo</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id}>
              <td>{dateTime(o.created_at)}</td>
              {showVenue && (
                <td>
                  <VenueTag venue={o.venue} />
                </td>
              )}
              <td>{o.symbol}</td>
              <td className={`side-${o.side}`}>{o.side === "BUY" ? "Compra" : "Venda"}</td>
              {/* Futuros da B3: o motor guarda pontos × valor do ponto; aqui mostra contratos */}
              <td className="num">{B3_POINT_VALUE[o.symbol] ? `${qty(Number(o.qty) / B3_POINT_VALUE[o.symbol])} contr.` : qty(o.qty)}</td>
              <td className="num">{price(o.price)}</td>
              <td className="num">{money(o.fee_quote, 4)}</td>
              <td className={`num ${pnlClass(o.realized_pnl)}`}>{o.realized_pnl ? signed(o.realized_pnl) : ""}</td>
              <td title={o.error ?? undefined}>{STATUS[o.status] ?? o.status}</td>
              <td className="muted">{o.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
