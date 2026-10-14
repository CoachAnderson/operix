"use client";

import { OrdersTable } from "@/components/OrdersTable";
import { Loading, PageHead, useApi } from "@/components/ui";
import type { Order } from "@/lib/types";

export default function OrdersPage() {
  const { data, error } = useApi<Order[]>("/orders?limit=200");
  return (
    <>
      <PageHead title="Ordens" lead="Todas as ordens dos seus robôs, da mais recente para a mais antiga." />
      {error && <p className="loss">{error}</p>}
      {data ? <OrdersTable orders={data} showVenue /> : <Loading />}
    </>
  );
}
