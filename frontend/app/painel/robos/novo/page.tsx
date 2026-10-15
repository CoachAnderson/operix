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
import { STRATEGY_LESSON } from "@/lib/learn/lessons";

/** O que muda na tela conforme o mercado. */
const MARKETS: Record<
  Market,
  { label: string; hint: string; exchange: string; symbol: string; lots: string; sl: string; tp: string; paper: string; credLabel: string; credMissing: string }
> = {
  crypto: {
    label: "Cripto",
    hint: "Binance à vista. Compra e vende o que tem.",
    exchange: "binance",
    symbol: "BTCUSDT",
    lots: "0.01",
    sl: "2",
    tp: "4",
    paper: "1000",
    credLabel: "Credencial da Binance",
    credMissing: "chave da Binance",
  },
  forex: {
    label: "Forex",
    hint: "Corretoras com cTrader. Opera comprado e vendido, em lotes.",
    exchange: "ctrader",
    symbol: "EURUSD",
    lots: "0.01",
    sl: "0.5",
    tp: "1",
    paper: "10000",
    credLabel: "Conta cTrader",
    credMissing: "conta cTrader",
  },
  b3: {
    label: "Futuros B3",
    hint: "Mini-índice (WIN) e mini-dólar (WDO) pelo MetaTrader 5 da sua corretora. Comprado e vendido, em contratos.",
    exchange: "mt5",
    symbol: "WIN",
    lots: "1",
    sl: "0.5",
    tp: "1",
    paper: "10000",
    credLabel: "Conexão do MetaTrader 5",
    credMissing: "conexão do MetaTrader 5",
  },
};

const B3_SYMBOLS = [
  { id: "WIN", label: "WIN · Mini Ibovespa", hint: "Cada ponto vale R$ 0,20 por contrato." },
  { id: "WDO", label: "WDO · Mini dólar", hint: "Cada ponto vale R$ 10 por contrato." },
];

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

  const m = MARKETS[form.market];
  const forex = form.market === "forex";
  const b3 = form.market === "b3";
  const margin = form.market !== "crypto"; // forex e B3: lotes/contratos, comprado e vendido
  const selected = strategies?.find((s) => s.code === strategy);
  const plan = sub?.status === "active" ? sub.plan : null;
  // Forex e B3 na simulação usam qualquer conexão do cliente (para cotações); nos demais, a do ambiente.
  const venueCreds = useMemo(
    () => creds?.filter((c) => c.exchange === m.exchange && (margin && form.venue === "paper" ? true : c.venue === form.venue)) ?? [],
    [creds, m.exchange, margin, form.venue],
  );
  const needsCred = margin || form.venue !== "paper";

  function chooseStrategy(s: StrategyInfo) {
    setStrategy(s.code);
    setParams(defaultParams(s));
    if (!form.name) setForm((f) => ({ ...f, name: s.name }));
  }

  function chooseMarket(market: Market) {
    const cfg = MARKETS[market];
    setForm((f) => ({
      ...f,
      market,
      symbol: cfg.symbol,
      allow_short: market !== "crypto",
      credential_id: "",
      order_lots: cfg.lots,
      stop_loss_pct: cfg.sl,
      take_profit_pct: cfg.tp,
      paper_quote_balance: cfg.paper,
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
      allow_short: margin && form.allow_short,
      exec_mode: form.exec_mode,
      venue: form.venue,
      credential_id: needsCred ? form.credential_id || null : null,
      order_size_quote: margin ? null : form.order_size_quote,
      order_lots: margin ? form.order_lots : null,
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
            {(Object.keys(MARKETS) as Market[]).map((key) => (
              <label key={key}>
                <input type="radio" name="market" checked={form.market === key} onChange={() => chooseMarket(key)} />
                {MARKETS[key].label}
                <span className="hint">{MARKETS[key].hint}</span>
              </label>
            ))}
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
          {selected && STRATEGY_LESSON[selected.code] && (
            <p className="small">
              <a href={`/aprender/${STRATEGY_LESSON[selected.code]}`} target="_blank" rel="noopener">
                Entenda como funciona &quot;{selected.name}&quot;: aula de 5 minutos, com gráfico para testar ↗
              </a>
            </p>
          )}
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
          {b3 ? (
            <label>
              Ativo
              <span className="hint">{B3_SYMBOLS.find((x) => x.id === form.symbol)?.hint} O robô opera sempre o vencimento atual e troca sozinho perto do vencimento.</span>
              <select value={form.symbol} onChange={set("symbol")}>
                {B3_SYMBOLS.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.label}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <label>
              {forex ? "Símbolo" : "Par"}
              <span className="hint">{forex ? "Como aparece no cTrader, ex.: EURUSD, GBPUSD, XAUUSD" : "Formato da Binance, ex.: BTCUSDT, ETHUSDT"}</span>
              <input required pattern="[A-Za-z0-9/]{5,20}" value={form.symbol} onChange={set("symbol")} />
            </label>
          )}
        </div>

        {b3 && selected?.style === "day" && (
          <p className="notice small">
            <strong>Day trade na B3</strong>
            O robô zera a posição 10 minutos antes do fim do pregão e não abre posição nova nos últimos 15 minutos. Só opera em dias úteis, das 9h05 às 18h20.
          </p>
        )}

        {margin && (
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
                          : b3 && v === "paper"
                            ? "Preços reais da B3 pelo seu MetaTrader 5, saldo fictício."
                            : b3 && v === "testnet"
                              ? "Conta demo da sua corretora no MetaTrader 5."
                              : b3 && v === "live"
                                ? "Ordens reais na sua conta da B3."
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
                {m.credLabel}
                {margin && form.venue === "paper" && <span className="hint">Usada só para as cotações; nenhuma ordem vai para ela.</span>}
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
                Nenhuma {margin ? m.credMissing : `chave de ${venueLabel(form.venue).toLowerCase()}`} conectada para este ambiente.{" "}
                <Link href="/painel/corretora">Conectar corretora</Link>
                {form.market === "crypto" && form.venue === "live" && (
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
              As ordens deste robô usam o saldo da sua conta{forex ? " e a alavancagem dela" : b3 ? " e a margem de garantia exigida pela corretora" : ""}. Para ligar, é preciso 2FA ativo e o termo de risco aceito.
            </p>
          )}
        </fieldset>

        <fieldset>
          <legend>Tamanho e limites de risco</legend>
          <div className="grid-2">
            {b3 ? (
              <label>
                Contratos por ordem
                <span className="hint">O conector no seu computador também tem um limite máximo por ordem.</span>
                <input type="number" required min="1" max="100" step="1" value={form.order_lots} onChange={set("order_lots")} />
              </label>
            ) : forex ? (
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
              <span className="hint">
                {b3
                  ? "Enviado ao MetaTrader 5 junto com a ordem; o robô também vigia. 0,5% ≈ 650 pontos no WIN."
                  : forex
                    ? "Enviado à corretora junto com a ordem. 0,5% ≈ 50 pips no EURUSD."
                    : "Vende se cair isso desde a compra. Vazio desliga."}
              </span>
              <input type="number" min="0.01" max="50" step="any" value={form.stop_loss_pct} onChange={set("stop_loss_pct")} />
            </label>
            <label>
              Alvo de lucro (%)
              <span className="hint">{margin ? "Também fica na corretora, mesmo se o sistema cair." : "Vende se subir isso desde a compra. Vazio desliga."}</span>
              <input type="number" min="0.01" max="500" step="any" value={form.take_profit_pct} onChange={set("take_profit_pct")} />
            </label>
            <label>
              Perda máxima no dia
              <span className="hint">{b3 ? "Em reais." : "Na moeda da conta."} Ao atingir, o robô pausa até você religar.</span>
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
