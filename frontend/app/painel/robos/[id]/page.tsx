"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { OrdersTable } from "@/components/OrdersTable";
import { TradingViewWidget } from "@/components/TradingViewWidget";
import { ErrorText, Loading, StatusTag, Stripe, VenueTag, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { B3_POINT_VALUE, MODE_LABEL, dateTime, money, pnlClass, price, qty, signed, venueLabel } from "@/lib/format";
import type { BotSummary, Credential, Order, Venue } from "@/lib/types";

export default function BotDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const summary = useApi<BotSummary>(`/bots/${id}`);
  const orders = useApi<Order[]>(`/orders?bot_id=${id}&limit=50`);
  const { data: creds } = useApi<Credential[]>("/credentials");
  const action = useAction();
  const [edit, setEdit] = useState<Record<string, string> | null>(null);

  useEffect(() => {
    const t = setInterval(() => {
      void summary.reload();
      void orders.reload();
    }, 15_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const s = summary.data;
  if (!s) return summary.error ? <p className="loss">{summary.error}</p> : <Loading />;
  const b = s.bot;
  const quote = b.symbol.endsWith("USDT") ? "USDT" : "";

  async function act(path: string, method = "POST", confirmText?: string) {
    if (confirmText && !window.confirm(confirmText)) return;
    let ok = false;
    await action.run(async () => {
      await api(`/bots/${id}${path}`, { method });
      ok = true;
    });
    if (!ok) return;
    if (method === "DELETE") return router.replace("/painel");
    await Promise.all([summary.reload(), orders.reload()]);
  }

  function startEdit() {
    setEdit({
      exec_mode: b.exec_mode,
      venue: b.venue,
      credential_id: b.credential_id ?? "",
      order_size_quote: b.order_size_quote ?? "",
      order_lots: b.order_lots ?? "",
      allow_short: String(b.allow_short),
      stop_loss_pct: b.stop_loss_pct ?? "",
      take_profit_pct: b.take_profit_pct ?? "",
      max_daily_loss_quote: b.max_daily_loss_quote ?? "",
      max_trades_per_day: String(b.max_trades_per_day),
    });
  }

  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!edit) return;
    if (edit.venue === "live" && b.venue !== "live" && !window.confirm("Passar este robô para a CONTA REAL? As próximas ordens usarão o dinheiro da sua conta na corretora.")) return;
    const body = {
      exec_mode: edit.exec_mode,
      venue: edit.venue,
      credential_id: edit.venue === "paper" && !margin ? null : edit.credential_id || null,
      ...(margin ? { order_lots: edit.order_lots, allow_short: edit.allow_short === "true" } : { order_size_quote: edit.order_size_quote }),
      stop_loss_pct: edit.stop_loss_pct || null,
      take_profit_pct: edit.take_profit_pct || null,
      max_daily_loss_quote: edit.max_daily_loss_quote || null,
      max_trades_per_day: Number(edit.max_trades_per_day),
    };
    const ok = await action.run(() => api(`/bots/${id}`, { method: "PATCH", json: body }));
    if (ok) {
      setEdit(null);
      await summary.reload();
    }
  }

  const running = b.status === "running";
  const forex = b.market === "forex";
  const isB3 = b.market === "b3";
  const margin = b.market !== "crypto"; // forex e B3: lotes/contratos, comprado e vendido
  const exchange = { crypto: "binance", forex: "ctrader", b3: "mt5" }[b.market];
  const lotsLabel = isB3 ? "Contratos por ordem" : "Lotes por ordem";
  const sign = s.position?.side === "short" ? -1 : 1;

  return (
    <>
      <header className="entry" style={{ marginBottom: 24, minHeight: 0 }}>
        <Stripe venue={b.venue} />
        <div style={{ flex: 1, padding: "18px 20px", display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
          <div>
            <h1>{b.name}</h1>
            <p className="muted" style={{ marginTop: 4 }}>
              {b.symbol}, modo {MODE_LABEL[b.exec_mode].toLowerCase()}, <VenueTag venue={b.venue} market={b.market} />
            </p>
          </div>
          <div className="actions">
            {running ? (
              <button className="btn" disabled={action.busy} onClick={() => act("/stop")}>Parar robô</button>
            ) : (
              <button
                className="btn btn-primary"
                disabled={action.busy}
                onClick={() => act("/start", "POST", b.venue === "live" ? "Ligar o robô na CONTA REAL? Ele vai usar seu saldo na Binance." : undefined)}
              >
                Ligar robô
              </button>
            )}
            {s.position && (
              <button className="btn btn-danger" disabled={action.busy} onClick={() => act("/close-position", "POST", "Vender toda a posição agora, a preço de mercado?")}>
                Encerrar posição
              </button>
            )}
          </div>
        </div>
      </header>

      <ErrorText>{action.error}</ErrorText>
      {b.status_reason && !running && (
        <div className={`notice ${b.status === "error" || b.status === "paused_risk" ? "notice-danger" : ""}`} style={{ marginBottom: 16 }}>
          <strong><StatusTag status={b.status} /></strong>
          {b.status_reason}
        </div>
      )}

      <dl className="figures" style={{ margin: 0 }}>
        <div>
          <dt>Situação</dt>
          <dd style={{ fontSize: "1rem" }}><StatusTag status={b.status} /></dd>
        </div>
        <div>
          <dt>Resultado hoje {quote && `(${quote})`}</dt>
          <dd className={pnlClass(s.realized_pnl_today)}>{signed(s.realized_pnl_today)}</dd>
        </div>
        <div>
          <dt>Resultado acumulado</dt>
          <dd className={pnlClass(s.realized_pnl_total)}>{signed(s.realized_pnl_total)}</dd>
        </div>
        <div>
          <dt>Ordens hoje</dt>
          <dd>{s.trades_today} de {b.max_trades_per_day}</dd>
        </div>
        {b.venue === "paper" && (
          <div>
            <dt>Saldo simulado</dt>
            <dd>{money(b.paper_quote_balance)}</dd>
          </div>
        )}
      </dl>

      <section className="section">
        <TradingViewWidget heading={<h2>Gráfico</h2>} symbol={b.symbol} market={b.market} timeframe={String(b.params.timeframe ?? "1h")} strategy={b.strategy} />
      </section>

      <section className="section">
        <h2>Posição</h2>
        {s.position ? (
          <p>
            {s.position.side === "short" ? "Vendido" : "Comprado"} em{" "}
            {isB3 ? `${qty(Number(s.position.qty) / (B3_POINT_VALUE[b.symbol] ?? 1))} contrato(s) de ${b.symbol}` : `${qty(s.position.qty)}${forex ? " unidades" : ""}`} a {price(s.position.avg_price)}, desde{" "}
            {dateTime(s.position.opened_at)}.
            {b.stop_loss_pct && ` Stop em ${price(Number(s.position.avg_price) * (1 - (sign * Number(b.stop_loss_pct)) / 100))}.`}
            {b.take_profit_pct && ` Alvo em ${price(Number(s.position.avg_price) * (1 + (sign * Number(b.take_profit_pct)) / 100))}.`}
            {margin && " Stop e alvo também ficam registrados na corretora."}
            {isB3 && b.strategy === "ema_cross_day" && " Day trade: zera 10 minutos antes do fim do pregão."}
          </p>
        ) : (
          <p className="muted">Sem posição aberta. Última verificação: {dateTime(b.last_tick_at)}.</p>
        )}
      </section>

      <section className="section">
        <div className="page-head" style={{ marginBottom: 12 }}>
          <h2>Configuração</h2>
          {!edit && <button className="btn" onClick={startEdit}>Ajustar</button>}
        </div>
        {!edit ? (
          <dl className="figures">
            <div>
              <dt>{margin ? lotsLabel : "Valor por ordem"}</dt>
              <dd style={{ fontSize: "1.1rem" }}>
                {margin ? `${isB3 ? qty(b.order_lots) : money(b.order_lots)}${b.allow_short ? ", compra e venda" : ", só compra"}` : money(b.order_size_quote)}
              </dd>
            </div>
            <div><dt>Stop loss</dt><dd style={{ fontSize: "1.1rem" }}>{b.stop_loss_pct ? `${money(b.stop_loss_pct)}%` : "Desligado"}</dd></div>
            <div><dt>Alvo de lucro</dt><dd style={{ fontSize: "1.1rem" }}>{b.take_profit_pct ? `${money(b.take_profit_pct)}%` : "Desligado"}</dd></div>
            <div><dt>Perda máxima/dia</dt><dd style={{ fontSize: "1.1rem" }}>{b.max_daily_loss_quote ? money(b.max_daily_loss_quote) : "Sem limite"}</dd></div>
          </dl>
        ) : (
          <form className="form panel" onSubmit={saveEdit} style={{ maxWidth: 720 }}>
            <div className="grid-2">
              <label>
                Modalidade
                <select value={edit.exec_mode} onChange={(e) => setEdit({ ...edit, exec_mode: e.target.value })}>
                  <option value="signals">Sinais</option>
                  <option value="auto">Automático</option>
                </select>
              </label>
              <label>
                Ambiente
                <span className="hint">Troca só com o robô parado e sem posição.</span>
                <select value={edit.venue} onChange={(e) => setEdit({ ...edit, venue: e.target.value, credential_id: "" })}>
                  {(["paper", "testnet", "live"] as Venue[]).map((v) => (
                    <option key={v} value={v}>{venueLabel(v, b.market)}</option>
                  ))}
                </select>
              </label>
              {(edit.venue !== "paper" || margin) && (
                <label>
                  {isB3 ? "Conexão do MetaTrader 5" : forex ? "Conta cTrader" : "Credencial"}
                  <select required value={edit.credential_id} onChange={(e) => setEdit({ ...edit, credential_id: e.target.value })}>
                    <option value="">Escolha…</option>
                    {creds?.filter((c) => c.exchange === exchange && (c.venue === edit.venue || (margin && edit.venue === "paper"))).map((c) => (
                      <option key={c.id} value={c.id}>{c.label} (final {c.key_last4})</option>
                    ))}
                  </select>
                </label>
              )}
              {margin ? (
                <>
                  <label>
                    {lotsLabel}
                    <input type="number" min={isB3 ? "1" : "0.01"} step={isB3 ? "1" : "0.01"} required value={edit.order_lots} onChange={(e) => setEdit({ ...edit, order_lots: e.target.value })} />
                  </label>
                  <label>
                    Direção
                    <select value={edit.allow_short} onChange={(e) => setEdit({ ...edit, allow_short: e.target.value })}>
                      <option value="true">Comprado e vendido</option>
                      <option value="false">Só comprado</option>
                    </select>
                  </label>
                </>
              ) : (
                <label>
                  Valor por ordem
                  <input type="number" min="1" step="any" required value={edit.order_size_quote} onChange={(e) => setEdit({ ...edit, order_size_quote: e.target.value })} />
                </label>
              )}
              <label>
                Stop loss (%)
                <input type="number" min="0.1" max="50" step="any" value={edit.stop_loss_pct} onChange={(e) => setEdit({ ...edit, stop_loss_pct: e.target.value })} />
              </label>
              <label>
                Alvo de lucro (%)
                <input type="number" min="0.1" max="500" step="any" value={edit.take_profit_pct} onChange={(e) => setEdit({ ...edit, take_profit_pct: e.target.value })} />
              </label>
              <label>
                Perda máxima no dia
                <input type="number" min="1" step="any" value={edit.max_daily_loss_quote} onChange={(e) => setEdit({ ...edit, max_daily_loss_quote: e.target.value })} />
              </label>
              <label>
                Máximo de ordens por dia
                <input type="number" min="1" max="500" required value={edit.max_trades_per_day} onChange={(e) => setEdit({ ...edit, max_trades_per_day: e.target.value })} />
              </label>
            </div>
            <div className="actions">
              <button className="btn btn-primary" disabled={action.busy}>Salvar ajustes</button>
              <button type="button" className="btn btn-quiet" onClick={() => setEdit(null)}>Cancelar</button>
            </div>
          </form>
        )}
      </section>

      <section className="section">
        <h2>Ordens</h2>
        {orders.data ? <OrdersTable orders={orders.data} /> : <Loading />}
      </section>

      <section className="section actions">
        {b.venue === "paper" && !s.position && (
          <button className="btn btn-quiet" onClick={() => act("/paper-reset?balance=1000", "POST", "Reiniciar o saldo simulado para 1.000 USDT?")}>
            Reiniciar saldo simulado
          </button>
        )}
        {!running && !s.position && (
          <button className="btn btn-quiet loss" onClick={() => act("", "DELETE", "Excluir este robô e o histórico de ordens dele?")}>
            Excluir robô
          </button>
        )}
        <Link className="btn btn-quiet" href={`/painel/backtest?robo=${b.id}`}>Testar esta configuração no histórico</Link>
        <Link className="btn btn-quiet" href="/painel">Voltar aos robôs</Link>
      </section>
    </>
  );
}
