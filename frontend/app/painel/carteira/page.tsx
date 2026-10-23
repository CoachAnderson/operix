"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { PageHead } from "@/components/ui";
import { api } from "@/lib/api";
import { money } from "@/lib/format";

interface Holding {
  asset: string;
  free: number;
  locked: number;
  total: number;
  usd: number | null;
  brl: number | null;
}
interface Account {
  id: string;
  label: string;
  exchange: "binance" | "ctrader" | "mt5";
  venue: "live" | "testnet";
  real: boolean;
  broker_name: string | null;
  ok: boolean;
  message?: string;
  bots: number;
  kind?: "assets" | "margin";
  holdings?: Holding[];
  hidden_holdings?: number;
  unpriced?: string[];
  currency?: string | null;
  balance?: number;
  equity?: number | null;
  margin_free?: number | null;
  leverage?: number | null;
  total_usd?: number | null;
  total_brl?: number | null;
}
interface PositionRow {
  bot_id: string;
  bot: string;
  symbol: string;
  market: "crypto" | "forex" | "b3";
  venue: "paper" | "testnet" | "live";
  side: "long" | "short";
  qty: number;
  avg_price: number;
  price: number | null;
  pnl: number | null;
  pnl_currency: string | null;
}
interface Wallet {
  updated_at: number;
  usd_brl: number | null;
  prices_ok: boolean;
  totals: { real_usd: number; real_brl: number | null; test_usd: number; test_brl: number | null; incomplete: boolean };
  accounts: Account[];
  positions: PositionRow[];
  simulated: { bot_id: string; bot: string; symbol: string; market: string; value: number; currency: string | null }[];
}

const EXCHANGE: Record<Account["exchange"], string> = { binance: "Binance", ctrader: "cTrader", mt5: "MetaTrader 5" };
const HIDE_KEY = "oi-carteira-oculta";

function venueLabel(a: Account): string {
  if (a.real) return "Conta real";
  return a.exchange === "binance" ? "Testnet" : "Conta demo";
}
const qtyFmt = (v: number) => v.toLocaleString("pt-BR", { maximumFractionDigits: v >= 1000 ? 2 : v >= 1 ? 4 : 8 });
const px = (v: number) => money(v, v >= 100 ? 2 : v >= 1 ? 4 : 6);

export default function WalletPage() {
  const [data, setData] = useState<Wallet | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    try {
      setHidden(localStorage.getItem(HIDE_KEY) === "1");
    } catch {
      /* sem armazenamento: começa visível */
    }
  }, []);

  const load = useCallback(async (fresh = false) => {
    setBusy(true);
    try {
      setData(await api<Wallet>(`/wallet${fresh ? "?atualizar=true" : ""}`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Não foi possível carregar a carteira");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => {
      if (!document.hidden) void load();
    }, 60_000);
    return () => clearInterval(t);
  }, [load]);

  function toggleHidden() {
    const v = !hidden;
    setHidden(v);
    try {
      localStorage.setItem(HIDE_KEY, v ? "1" : "0");
    } catch {
      /* ignora */
    }
  }

  // Valores escondidos (para mostrar a tela a alguém sem expor o saldo).
  const m = (v: number | null | undefined, d = 2) => (hidden ? "•••••" : v === null || v === undefined ? "—" : money(v, d));
  const brl = (v: number | null | undefined) => (hidden ? "R$ •••••" : v === null || v === undefined ? "—" : `R$ ${money(v)}`);
  const usd = (v: number | null | undefined) => (hidden ? "US$ •••••" : v === null || v === undefined ? "—" : `US$ ${money(v)}`);

  return (
    <div style={{ display: "grid", gap: 24 }}>
      <PageHead
        title="Carteira"
        lead="Saldos das suas contas conectadas, em um lugar só. É apenas consulta: o dinheiro continua na corretora, e a plataforma não guarda, não deposita e não saca valores."
      >
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button type="button" className="btn" onClick={toggleHidden} aria-pressed={hidden}>
            {hidden ? "Mostrar valores" : "Esconder valores"}
          </button>
          <button type="button" className="btn" onClick={() => load(true)} disabled={busy}>
            {busy ? "Atualizando…" : "Atualizar agora"}
          </button>
        </div>
      </PageHead>

      {error && <p className="loss">{error}</p>}
      {!data && !error && <p className="muted">Consultando suas contas…</p>}

      {data && (
        <>
          <dl className="figures" style={{ margin: 0 }}>
            <div>
              <dt>Patrimônio nas contas reais</dt>
              <dd>{brl(data.totals.real_brl)}</dd>
              <span className="muted small">
                {usd(data.totals.real_usd)}
                {data.totals.incomplete && " · alguma conta real não pôde ser lida ou convertida"}
              </span>
            </div>
            <div>
              <dt>Testnet e contas demo</dt>
              <dd>{brl(data.totals.test_brl)}</dd>
              <span className="muted small">{usd(data.totals.test_usd)} · dinheiro de teste</span>
            </div>
            <div>
              <dt>Dólar (USDT/BRL)</dt>
              <dd>{data.usd_brl ? `R$ ${money(data.usd_brl, 3)}` : "—"}</dd>
              <span className="muted small">cotação usada na conversão</span>
            </div>
            <div>
              <dt>Posições abertas dos robôs</dt>
              <dd>{data.positions.length}</dd>
              <span className="muted small">atualizado às {new Date(data.updated_at).toLocaleTimeString("pt-BR")}</span>
            </div>
          </dl>
          {!data.prices_ok && <p className="notice small">Sem cotações da Binance agora: os saldos aparecem, mas sem a conversão para real e dólar.</p>}

          <section className="section" style={{ display: "grid", gap: 12 }}>
            <h2>Contas</h2>
            {data.accounts.length === 0 && (
              <p className="muted">
                Nenhuma conta conectada. <Link href="/painel/corretora">Conecte a Binance, o cTrader ou o MetaTrader 5</Link> para ver os saldos aqui.
              </p>
            )}
            {data.accounts.map((a) => (
              <article key={a.id} className="panel" style={{ display: "grid", gap: 12 }}>
                <header style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", gap: "4px 16px", alignItems: "baseline" }}>
                  <div>
                    <strong>{a.label}</strong>{" "}
                    <span className="muted small">
                      {EXCHANGE[a.exchange]}
                      {a.broker_name ? ` · ${a.broker_name}` : ""} · {venueLabel(a)}
                      {a.bots > 0 && ` · ${a.bots} robô${a.bots > 1 ? "s" : ""} usa${a.bots > 1 ? "m" : ""} esta conta`}
                    </span>
                  </div>
                  {a.ok && (
                    <div style={{ textAlign: "right" }}>
                      <strong>{a.total_brl !== null && a.total_brl !== undefined ? brl(a.total_brl) : a.currency ? `${a.currency} ${m(a.equity ?? a.balance)}` : "—"}</strong>
                      {a.total_usd !== null && a.total_usd !== undefined && <span className="muted small"> · {usd(a.total_usd)}</span>}
                    </div>
                  )}
                </header>

                {!a.ok && (
                  <p className="small">
                    <span className="loss">{a.message}</span> <Link href="/painel/corretora">Ver conexões</Link>
                  </p>
                )}

                {a.ok && a.kind === "assets" && (
                  <>
                    {a.holdings && a.holdings.length > 0 ? (
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Ativo</th>
                              <th className="num">Quantidade</th>
                              <th className="num">Em ordens</th>
                              <th className="num">Em US$</th>
                              <th className="num">Em R$</th>
                            </tr>
                          </thead>
                          <tbody>
                            {a.holdings.map((h) => (
                              <tr key={h.asset}>
                                <td>
                                  <strong>{h.asset}</strong>
                                </td>
                                <td className="num">{hidden ? "•••••" : qtyFmt(h.total)}</td>
                                <td className="num">{h.locked ? (hidden ? "•••••" : qtyFmt(h.locked)) : "—"}</td>
                                <td className="num">{m(h.usd)}</td>
                                <td className="num">{m(h.brl)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="muted small">Conta sem saldo.</p>
                    )}
                    {!!a.hidden_holdings && <p className="muted small">E mais {a.hidden_holdings} ativos de valor menor.</p>}
                    {a.unpriced && a.unpriced.length > 0 && (
                      <p className="muted small">Sem cotação em dólar na Binance (fora do total): {a.unpriced.join(", ")}.</p>
                    )}
                  </>
                )}

                {a.ok && a.kind === "margin" && (
                  <dl className="figures" style={{ margin: 0 }}>
                    <div>
                      <dt>Saldo</dt>
                      <dd>
                        {a.currency ?? ""} {m(a.balance)}
                      </dd>
                    </div>
                    {a.equity !== null && a.equity !== undefined && (
                      <div>
                        <dt>Patrimônio</dt>
                        <dd>
                          {a.currency ?? ""} {m(a.equity)}
                        </dd>
                        <span className="muted small">saldo + resultado das posições abertas</span>
                      </div>
                    )}
                    {a.margin_free !== null && a.margin_free !== undefined && (
                      <div>
                        <dt>Margem livre</dt>
                        <dd>
                          {a.currency ?? ""} {m(a.margin_free)}
                        </dd>
                      </div>
                    )}
                    {a.leverage ? (
                      <div>
                        <dt>Alavancagem da conta</dt>
                        <dd>1:{money(a.leverage, 0)}</dd>
                      </div>
                    ) : null}
                  </dl>
                )}
              </article>
            ))}
          </section>

          {data.positions.length > 0 && (
            <section className="section" style={{ display: "grid", gap: 12 }}>
              <h2>Com os robôs agora</h2>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Robô</th>
                      <th>Ativo</th>
                      <th>Posição</th>
                      <th className="num">Quantidade</th>
                      <th className="num">Entrada</th>
                      <th className="num">Preço atual</th>
                      <th className="num">Resultado aberto</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.positions.map((p) => (
                      <tr key={p.bot_id}>
                        <td>
                          <Link href={`/painel/robos/${p.bot_id}`}>{p.bot}</Link>
                          <span className="muted small"> · {p.venue === "paper" ? "simulação" : p.venue === "live" ? "conta real" : "teste"}</span>
                        </td>
                        <td>{p.symbol}</td>
                        <td>{p.side === "short" ? "Vendido" : "Comprado"}</td>
                        <td className="num">{hidden ? "•••••" : p.market === "b3" ? `${money(p.qty, 0)} contr.` : qtyFmt(p.qty)}</td>
                        <td className="num">{px(p.avg_price)}</td>
                        <td className="num">{p.price ? px(p.price) : "—"}</td>
                        <td className={`num ${p.pnl === null ? "" : p.pnl >= 0 ? "gain" : "loss"}`}>
                          {p.pnl === null ? "ver no robô" : hidden ? "•••••" : `${p.pnl >= 0 ? "+" : ""}${money(p.pnl)} ${p.pnl_currency ?? ""}`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {data.simulated.length > 0 && (
            <section className="section" style={{ display: "grid", gap: 12 }}>
              <h2>Simulação</h2>
              <p className="muted small">Saldo fictício de cada robô em simulação, com a posição aberta pelo preço atual. Não é dinheiro real.</p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Robô</th>
                      <th>Ativo</th>
                      <th className="num">Saldo simulado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.simulated.map((s) => (
                      <tr key={s.bot_id}>
                        <td>
                          <Link href={`/painel/robos/${s.bot_id}`}>{s.bot}</Link>
                        </td>
                        <td>{s.symbol}</td>
                        <td className="num">
                          {m(s.value)} {s.currency ?? ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <p className="muted small">
            Valores convertidos com as cotações da Binance (dólar = USDT). Saldo do cTrader sem o resultado das posições abertas; no MetaTrader 5, o patrimônio já
            inclui esse resultado. As contas são lidas com as chaves e conexões que você cadastrou, só para consulta.
          </p>
        </>
      )}
    </div>
  );
}
