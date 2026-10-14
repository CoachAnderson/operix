"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { StrategyParamsFields, cleanParams, defaultParams } from "@/components/StrategyParams";
import { ErrorText, Loading, PageHead, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { VENUE_HINT, venueLabel } from "@/lib/format";
import type { Bot, Credential, ExecMode, Market, StrategyInfo, Subscription, Venue } from "@/lib/types";
import { BinanceSignup } from "@/components/BinanceSignup";

const DEFAULT_SYMBOL: Record<Market, string> = { crypto: "BTCUSDT", forex: "EURUSD" };

export default function NewBotPage() {
  const router = useRouter();
  const { data: strategies } = useApi<StrategyInfo[]>("/strategies");
  const { data: sub, loading: subLoading } = useApi<Subscription | null>("/billing/subscription");
  const { data: creds } = useApi<Credential[]>("/credentials");
  const { busy, error, run } = useAction();

  const [strategy, setStrategy] = useState<string>("");
  const [params, setParams] = useState<Record<string, string>>({});
  const [form, setForm] = useState({
    market: "crypto" as Market,
    name: "",
    symbol: "BTCUSDT",
    allow_short: false,
    exec_mode: "signals" as ExecMode,
    venue: "paper" as Venue,
    credential_id: "",
    order_size_quote: "50",
    order_lots: "0.01",
    stop_loss_pct: "2",
    take_profit_pct: "4",
    max_daily_loss_quote: "",
    max_trades_per_day: "10",
    paper_quote_balance: "1000",
  });

  const forex = form.market === "forex";
  const selected = strategies?.find((s) => s.code === strategy);
  const plan = sub?.status === "active" ? sub.plan : null;
  const exchange = forex ? "ctrader" : "binance";
  // Forex na simulação usa qualquer conta cTrader do cliente (para cotações); nos demais, a do ambiente.
  const venueCreds = useMemo(
    () => creds?.filter((c) => c.exchange === exchange && (forex && form.venue === "paper" ? true : c.venue === form.venue)) ?? [],
    [creds, exchange, forex, form.venue],
  );
  const needsCred = forex || form.venue !== "paper";

  function chooseStrategy(s: StrategyInfo) {
    setStrategy(s.code);
    setParams(defaultParams(s));
    if (!form.name) setForm((f) => ({ ...f, name: s.name }));
  }

  function chooseMarket(m: Market) {
    setForm((f) => ({
      ...f,
      market: m,
      symbol: DEFAULT_SYMBOL[m],
      allow_short: m === "forex",
      credential_id: "",
      stop_loss_pct: m === "forex" ? "0.5" : "2",
      take_profit_pct: m === "forex" ? "1" : "4",
      paper_quote_balance: m === "forex" ? "10000" : "1000",
    }));
  }

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm({ ...form, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const body = {
      name: form.name,
      market: form.market,
      symbol: form.symbol.trim().toUpperCase().replace("/", ""),
      strategy,
      params: cleanParams(params),
      allow_short: forex && form.allow_short,
      exec_mode: form.exec_mode,
      venue: form.venue,
      credential_id: needsCred ? form.credential_id || null : null,
      order_size_quote: forex ? null : form.order_size_quote,
      order_lots: forex ? form.order_lots : null,
      stop_loss_pct: form.stop_loss_pct || null,
      take_profit_pct: form.take_profit_pct || null,
      max_daily_loss_quote: form.max_daily_loss_quote || null,
      max_trades_per_day: Number(form.max_trades_per_day),
      paper_quote_balance: form.paper_quote_balance,
    };
    const bot = await run(() => api<Bot>("/bots", { json: body }));
    if (bot) router.push(`/painel/robos/${bot.id}`);
  }

  if (!strategies || subLoading) return <Loading />;
  if (!plan)
    return (
      <div className="notice">
        <strong>Assinatura inativa</strong>
        Para criar robôs, <Link href="/painel/assinatura">escolha um plano</Link>.
      </div>
    );

  return (
    <>
      <PageHead title="Criar robô" lead="Escolha o mercado, a estratégia, onde ele vai operar e os limites de risco." />
      <form className="form" onSubmit={submit} style={{ maxWidth: 720 }}>
        <fieldset>
          <legend>Mercado</legend>
          <div className="choice">
            <label>
              <input type="radio" name="market" checked={!forex} onChange={() => chooseMarket("crypto")} />
              Cripto
              <span className="hint">Binance à vista. Compra e vende o que tem.</span>
            </label>
            <label>
              <input type="radio" name="market" checked={forex} onChange={() => chooseMarket("forex")} />
              Forex
              <span className="hint">Corretoras com cTrader. Opera comprado e vendido, em lotes.</span>
            </label>
          </div>
        </fieldset>

        <fieldset>
          <legend>Estratégia</legend>
          {(["day", "swing"] as const).map((style) => (
            <div key={style} style={{ display: "grid", gap: 8 }}>
              <span className="muted small">{style === "day" ? "Day trade: fecha no mesmo dia" : "Swing trade: segura por dias"}</span>
              <div className="choice">
                {strategies
                  .filter((s) => s.style === style)
                  .map((s) => (
                    <label key={s.code}>
                      <input type="radio" name="strategy" checked={strategy === s.code} onChange={() => chooseStrategy(s)} required />
                      {s.name}
                      <span className="hint">{s.description}</span>
                    </label>
                  ))}
              </div>
            </div>
          ))}
        </fieldset>

        {selected && (
          <fieldset>
            <legend>Parâmetros</legend>
            <StrategyParamsFields strategy={selected} params={params} onChange={setParams} />
          </fieldset>
        )}

        <div className="grid-2">
          <label>
            Nome do robô
            <input required maxLength={80} value={form.name} onChange={set("name")} />
          </label>
          <label>
            {forex ? "Símbolo" : "Par"}
            <span className="hint">{forex ? "Como aparece no cTrader, ex.: EURUSD, GBPUSD, XAUUSD" : "Formato da Binance, ex.: BTCUSDT, ETHUSDT"}</span>
            <input required pattern="[A-Za-z0-9/]{5,20}" value={form.symbol} onChange={set("symbol")} />
          </label>
        </div>

        {forex && (
          <fieldset>
            <legend>Direção</legend>
            <div className="choice">
              <label>
                <input type="radio" name="dir" checked={form.allow_short} onChange={() => setForm({ ...form, allow_short: true })} />
                Comprado e vendido
                <span className="hint">Entra vendido quando a estratégia indica queda.</span>
              </label>
              <label>
                <input type="radio" name="dir" checked={!form.allow_short} onChange={() => setForm({ ...form, allow_short: false })} />
                Só comprado
                <span className="hint">Ignora os sinais de venda a descoberto.</span>
              </label>
            </div>
          </fieldset>
        )}

        <fieldset>
          <legend>Modalidade</legend>
          <div className="choice">
            <label>
              <input type="radio" name="mode" checked={form.exec_mode === "signals"} onChange={() => setForm({ ...form, exec_mode: "signals" })} />
              Sinais
              <span className="hint">O robô avisa; você confirma cada ordem no painel.</span>
            </label>
            <label>
              <input type="radio" name="mode" disabled={!plan.allow_auto} checked={form.exec_mode === "auto"} onChange={() => setForm({ ...form, exec_mode: "auto" })} />
              Automático
              <span className="hint">{plan.allow_auto ? "O robô envia as ordens sozinho." : `Não incluso no plano ${plan.name}.`}</span>
            </label>
          </div>
        </fieldset>

        <fieldset>
          <legend>Onde operar</legend>
          <div className="choice">
            {(["paper", "testnet", "live"] as Venue[]).map((v) => {
              const blocked = v === "live" && !plan.allow_live;
              return (
                <label key={v}>
                  <input type="radio" name="venue" disabled={blocked} checked={form.venue === v} onChange={() => setForm({ ...form, venue: v, credential_id: "" })} />
                  {venueLabel(v, form.market)}
                  <span className="hint">
                    {blocked
                      ? `Não incluso no plano ${plan.name}.`
                      : forex && v === "testnet"
                        ? "Conta demo da sua corretora no cTrader."
                        : forex && v === "live"
                          ? "Ordens reais na sua conta cTrader."
                          : VENUE_HINT[v]}
                  </span>
                </label>
              );
            })}
          </div>
          {form.venue === "paper" && (
            <label>
              Saldo simulado inicial
              <input type="number" min="10" step="any" value={form.paper_quote_balance} onChange={set("paper_quote_balance")} />
            </label>
          )}
          {needsCred &&
            (venueCreds.length ? (
              <label>
                {forex ? "Conta cTrader" : "Credencial da Binance"}
                {forex && form.venue === "paper" && <span className="hint">Usada só para as cotações; nenhuma ordem vai para ela.</span>}
                <select required value={form.credential_id} onChange={set("credential_id")}>
                  <option value="">Escolha…</option>
                  {venueCreds.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.label} ({venueLabel(c.venue, form.market)})
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <p className="notice small">
                Nenhuma {forex ? "conta cTrader" : `chave de ${venueLabel(form.venue).toLowerCase()}`} conectada para este ambiente.{" "}
                <Link href="/painel/corretora">Conectar corretora</Link>
                {!forex && form.venue === "live" && (
                  <>
                    {" "}
                    <BinanceSignup compact />
                  </>
                )}
              </p>
            ))}
          {form.venue === "live" && (
            <p className="notice notice-danger small">
              <strong>Dinheiro de verdade</strong>
              As ordens deste robô usam o saldo da sua conta{forex ? " e a alavancagem dela" : ""}. Para ligar, é preciso 2FA ativo e o termo de risco aceito.
            </p>
          )}
        </fieldset>

        <fieldset>
          <legend>Tamanho e limites de risco</legend>
          <div className="grid-2">
            {forex ? (
              <label>
                Lotes por ordem
                <span className="hint">0,01 = micro lote (1.000 unidades da moeda base, na maioria das corretoras).</span>
                <input type="number" required min="0.01" step="0.01" value={form.order_lots} onChange={set("order_lots")} />
              </label>
            ) : (
              <label>
                Valor por ordem (USDT)
                <input type="number" required min="1" step="any" value={form.order_size_quote} onChange={set("order_size_quote")} />
              </label>
            )}
            <label>
              Máximo de ordens por dia
              <input type="number" required min="1" max="500" value={form.max_trades_per_day} onChange={set("max_trades_per_day")} />
            </label>
            <label>
              Stop loss (%)
              <span className="hint">{forex ? "Enviado à corretora junto com a ordem. 0,5% ≈ 50 pips no EURUSD." : "Vende se cair isso desde a compra. Vazio desliga."}</span>
              <input type="number" min="0.01" max="50" step="any" value={form.stop_loss_pct} onChange={set("stop_loss_pct")} />
            </label>
            <label>
              Alvo de lucro (%)
              <span className="hint">{forex ? "Também fica na corretora, mesmo se o sistema cair." : "Vende se subir isso desde a compra. Vazio desliga."}</span>
              <input type="number" min="0.01" max="500" step="any" value={form.take_profit_pct} onChange={set("take_profit_pct")} />
            </label>
            <label>
              Perda máxima no dia
              <span className="hint">Na moeda da conta. Ao atingir, o robô pausa até você religar.</span>
              <input type="number" min="1" step="any" value={form.max_daily_loss_quote} onChange={set("max_daily_loss_quote")} />
            </label>
          </div>
        </fieldset>

        <ErrorText>{error}</ErrorText>
        <div className="actions">
          <button className="btn btn-primary" disabled={busy || !strategy}>
            {busy ? "Criando…" : "Criar robô"}
          </button>
          <Link className="btn btn-quiet" href="/painel">Cancelar</Link>
        </div>
        <p className="muted small">O robô é criado parado. Revise e ligue na próxima tela.</p>
      </form>
    </>
  );
}
