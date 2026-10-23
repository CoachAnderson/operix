"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { CandleChart, type OHLC } from "@/components/CandleChart";
import { EquityChart } from "@/components/EquityChart";
import { StrategyParamsFields, cleanParams, defaultParams } from "@/components/StrategyParams";
import { ErrorText, Loading, PageHead, useAction, useApi } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime, money, pnlClass, price, signed } from "@/lib/format";
import type { BotFilters, BotSummary, Credential, Market, StrategyInfo } from "@/lib/types";
import { FiltersFields, cleanFilters } from "@/components/FiltersFields";
import { FilterCompare, SplitTable, type Segment } from "@/components/RobustnessView";
import { StatsView, type Analysis } from "@/components/StatsView";

/** Custos padrão por mercado (taxa por lado em % e escorregamento em centésimos de %). */
const MARKET_COSTS: Record<Market, { fee_pct: string; slippage_bps: string }> = {
  crypto: { fee_pct: "0.1", slippage_bps: "5" },
  forex: { fee_pct: "0.003", slippage_bps: "0.5" },
  b3: { fee_pct: "0.0015", slippage_bps: "0.6" },
};

interface Metrics {
  trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  avg_win: number;
  avg_loss: number;
  payoff: number | null;
  expectancy: number;
  expectancy_pct: number;
  profit_factor: number | null;
  net_pnl: number;
  return_pct: number;
  buy_hold_pct: number;
  max_drawdown_pct: number;
  fees_total: number;
  exposure_pct: number;
  avg_hold_minutes: number;
  best_trade: number;
  worst_trade: number;
  max_consecutive_losses: number;
  final_balance: number;
  long_trades: number;
  short_trades: number;
}
interface Trade {
  side: "long" | "short";
  entry_time: number;
  exit_time: number;
  entry_price: number;
  exit_price: number;
  qty: number;
  pnl: number;
  return_pct: number;
  fees: number;
  exit_reason: string;
  tag?: string | null;
  move_pct?: number;
}
interface Result {
  metrics: Metrics;
  trades: Trade[];
  equity: [number, number, number][];
  monthly: { month: string; trades: number; wins: number; pnl: number }[];
  warnings: string[];
  candles: number;
  start: number;
  end: number;
  symbol: string;
  market: Market;
  timeframe: string;
  config: { initial_balance: number; order_size_quote: number };
  ohlc: OHLC[];
  segments: Segment[];
  baseline?: { metrics: Metrics; segments: Segment[] };
  filtered_entries: number;
  filter_reasons: { reason: string; count: number }[];
  analysis?: Analysis;
}

const PRESETS: [string, number][] = [
  ["1 mês", 30],
  ["3 meses", 90],
  ["6 meses", 182],
  ["1 ano", 365],
  ["2 anos", 730],
];

const iso = (d: Date) => d.toISOString().slice(0, 10);
const daysAgo = (n: number) => iso(new Date(Date.now() - n * 86_400_000));
const pct = (v: number) => `${v > 0 ? "+" : ""}${money(v)}%`;

function hold(minutes: number): string {
  if (minutes < 120) return `${Math.round(minutes)} min`;
  if (minutes < 2880) return `${money(minutes / 60, 1)} h`;
  return `${money(minutes / 1440, 1)} dias`;
}

function BacktestView() {
  const search = useSearchParams();
  const botId = search.get("robo");
  const presetSymbol = search.get("simbolo"); // vindo de Mercados
  const { data: strategies } = useApi<StrategyInfo[]>("/strategies");
  const action = useAction();
  const [result, setResult] = useState<Result | null>(null);
  const [strategy, setStrategy] = useState("");
  const [params, setParams] = useState<Record<string, string>>({});
  const [preset, setPreset] = useState<number | null>(182);
  const { data: creds } = useApi<Credential[]>("/credentials");
  const [form, setForm] = useState({
    market: "crypto" as Market,
    credential_id: "",
    order_lots: "0.10",
    allow_short: true,
    symbol: "BTCUSDT",
    start: daysAgo(182),
    end: daysAgo(0),
    initial_balance: "1000",
    order_size_quote: "100",
    stop_loss_pct: "2",
    take_profit_pct: "4",
    max_daily_loss_quote: "",
    fee_pct: "0.1",
    slippage_bps: "5",
    risk_pct: "",
    max_leverage: "",
  });
  const [botName, setBotName] = useState<string | null>(null);
  const [filters, setFilters] = useState<BotFilters>({});
  const [oos, setOos] = useState("30");

  // Pré-preenche com a configuração de um robô (?robo=ID)
  useEffect(() => {
    if (presetSymbol && /^[A-Z0-9]{5,20}$/.test(presetSymbol)) setForm((f) => ({ ...f, market: "crypto", symbol: presetSymbol }));
  }, [presetSymbol]);

  useEffect(() => {
    if (!botId) return;
    api<BotSummary>(`/bots/${botId}`)
      .then(({ bot }) => {
        setBotName(bot.name);
        setStrategy(bot.strategy);
        setFilters(bot.filters ?? {});
        setParams(Object.fromEntries(Object.entries(bot.params).map(([k, v]) => [k, String(v)])));
        setForm((f) => ({
          ...f,
          market: bot.market,
          credential_id: bot.credential_id ?? "",
          order_lots: bot.order_lots ?? f.order_lots,
          allow_short: bot.allow_short,
          fee_pct: MARKET_COSTS[bot.market].fee_pct,
          slippage_bps: MARKET_COSTS[bot.market].slippage_bps,
          initial_balance: bot.market === "crypto" ? f.initial_balance : "10000",
          symbol: bot.symbol,
          order_size_quote: bot.order_size_quote ?? f.order_size_quote,
          stop_loss_pct: bot.stop_loss_pct ?? "",
          take_profit_pct: bot.take_profit_pct ?? "",
          max_daily_loss_quote: bot.max_daily_loss_quote ?? "",
          risk_pct: bot.sizing_mode === "risk" ? (bot.risk_pct ?? "") : "",
          max_leverage: bot.max_leverage ?? "",
        }));
      })
      .catch(() => {});
  }, [botId]);

  useEffect(() => {
    if (strategies && !strategy) {
      setStrategy(strategies[0].code);
      setParams(defaultParams(strategies[0]));
    }
  }, [strategies, strategy]);

  const selected = strategies?.find((s) => s.code === strategy);
  const forex = form.market === "forex";
  const isB3 = form.market === "b3";
  const margin = form.market !== "crypto";
  const ctCreds = creds?.filter((c) => c.exchange === "ctrader") ?? [];
  const mt5Creds = creds?.filter((c) => c.exchange === "mt5") ?? [];
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });

  function chooseMarket(m: Market) {
    setForm((f) => ({
      ...f,
      market: m,
      credential_id: "",
      symbol: { crypto: "BTCUSDT", forex: "EURUSD", b3: "WIN" }[m],
      order_lots: m === "b3" ? "1" : "0.10",
      allow_short: m !== "crypto",
      fee_pct: MARKET_COSTS[m].fee_pct,
      slippage_bps: MARKET_COSTS[m].slippage_bps,
      stop_loss_pct: m === "crypto" ? "2" : "0.5",
      take_profit_pct: m === "crypto" ? "4" : "1",
      initial_balance: m === "crypto" ? "1000" : "10000",
    }));
  }

  function applyPreset(days: number) {
    setPreset(days);
    setForm({ ...form, start: daysAgo(days), end: daysAgo(0) });
  }

  async function run(e: React.FormEvent) {
    e.preventDefault();
    const body = {
      strategy,
      params: cleanParams(params),
      market: form.market,
      credential_id: margin ? form.credential_id || null : null,
      order_lots: margin ? Number(form.order_lots) : null,
      allow_short: margin && form.allow_short,
      symbol: form.symbol.trim().toUpperCase().replace("/", ""),
      start: form.start,
      end: form.end,
      initial_balance: Number(form.initial_balance),
      order_size_quote: Number(form.order_size_quote),
      stop_loss_pct: form.stop_loss_pct ? Number(form.stop_loss_pct) : null,
      take_profit_pct: form.take_profit_pct ? Number(form.take_profit_pct) : null,
      max_daily_loss_quote: form.max_daily_loss_quote ? Number(form.max_daily_loss_quote) : null,
      fee_rate: Number(form.fee_pct) / 100,
      slippage_bps: Number(form.slippage_bps),
      filters: cleanFilters(filters),
      oos_pct: Number(oos),
      risk_pct: form.risk_pct ? Number(form.risk_pct) : null,
      max_leverage: margin && form.max_leverage ? Number(form.max_leverage) : null,
    };
    const res = await action.run(() => api<Result>("/backtest", { json: body }));
    if (res) setResult(res);
  }

  if (!strategies) return <Loading />;

  return (
    <>
      <PageHead
        title="Backtest"
        lead={botName ? `Testando a configuração do robô ${botName} no histórico.` : "Teste uma estratégia no histórico (Binance, cTrader ou MetaTrader 5) antes de ligar um robô."}
      />
      <div className="bt-layout">
        <form className="form panel" onSubmit={run}>
          <div className="presets" role="group" aria-label="Mercado">
            <button type="button" className="btn" aria-pressed={form.market === "crypto"} onClick={() => chooseMarket("crypto")}>Cripto (Binance)</button>
            <button type="button" className="btn" aria-pressed={forex} onClick={() => chooseMarket("forex")}>Forex (cTrader)</button>
            <button type="button" className="btn" aria-pressed={isB3} onClick={() => chooseMarket("b3")}>Futuros B3 (MT5)</button>
          </div>
          {isB3 &&
            (mt5Creds.length ? (
              <label>
                Conexão do MetaTrader 5 (fonte do histórico)
                <span className="hint">O conector precisa estar aberto. O histórico vem da série contínua da sua corretora.</span>
                <select required value={form.credential_id} onChange={set("credential_id")}>
                  <option value="">Escolha…</option>
                  {mt5Creds.map((c) => (
                    <option key={c.id} value={c.id}>{c.label}</option>
                  ))}
                </select>
              </label>
            ) : (
              <p className="notice small">
                Conecte o MetaTrader 5 em <Link href="/painel/corretora">Corretora</Link> para baixar o histórico da B3.
              </p>
            ))}
          {forex &&
            (ctCreds.length ? (
              <label>
                Conta cTrader (fonte do histórico)
                <select required value={form.credential_id} onChange={set("credential_id")}>
                  <option value="">Escolha…</option>
                  {ctCreds.map((c) => (
                    <option key={c.id} value={c.id}>{c.label}</option>
                  ))}
                </select>
              </label>
            ) : (
              <p className="notice small">
                Conecte uma conta cTrader em <Link href="/painel/corretora">Corretora</Link> para baixar o histórico de forex.
              </p>
            ))}
          <label>
            Estratégia
            <select
              value={strategy}
              onChange={(e) => {
                const s = strategies.find((x) => x.code === e.target.value)!;
                setStrategy(s.code);
                setParams(defaultParams(s));
                if (s.timeframe === "1m" && (preset === null || preset > 30)) applyPreset(30); // limite do histórico de 1 minuto
              }}
            >
              {(["day", "swing"] as const).map((style) => (
                <optgroup key={style} label={style === "day" ? "Day trade" : "Swing trade"}>
                  {strategies
                    .filter((s) => s.style === style)
                    .map((s) => (
                      <option key={s.code} value={s.code}>
                        {s.name}
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </label>
          {selected && <StrategyParamsFields strategy={selected} params={params} onChange={setParams} />}
          {selected?.trade_bars && (
            <p className="notice small">
              Cada operação dura {selected.trade_bars} candle: entra na abertura e sai no fechamento. Candles de 1 minuto: o teste aceita até 32 dias. Em cripto à
              vista só entram as compras; para testar as vendas, use forex ou B3 com &quot;operar vendido&quot;.
            </p>
          )}
          {isB3 ? (
            <label>
              Ativo
              <select value={form.symbol} onChange={set("symbol")}>
                <option value="WIN">WIN · Mini Ibovespa</option>
                <option value="WDO">WDO · Mini dólar</option>
              </select>
            </label>
          ) : (
            <label>
              {forex ? "Símbolo" : "Par"}
              <input required pattern="[A-Za-z0-9\/]{5,20}" value={form.symbol} onChange={set("symbol")} />
            </label>
          )}
          {margin && (
            <label className="check">
              <input type="checkbox" checked={form.allow_short} onChange={(e) => setForm({ ...form, allow_short: e.target.checked })} />
              <span>Operar também vendido</span>
            </label>
          )}
          <div style={{ display: "grid", gap: 8 }}>
            <span style={{ fontWeight: 550, fontSize: "0.95rem" }}>Período</span>
            <div className="presets">
              {PRESETS.map(([label, d]) => (
                <button key={d} type="button" className="btn" aria-pressed={preset === d} onClick={() => applyPreset(d)}>
                  {label}
                </button>
              ))}
            </div>
            <div className="grid-2">
              <label className="small">
                De
                <input type="date" required min={form.market === "crypto" ? "2017-08-17" : undefined} value={form.start} onChange={(e) => { setPreset(null); set("start")(e); }} />
              </label>
              <label className="small">
                Até
                <input type="date" required value={form.end} onChange={(e) => { setPreset(null); set("end")(e); }} />
              </label>
            </div>
          </div>
          <div className="grid-2">
            <label>
              Saldo inicial
              <input type="number" min="10" step="any" required value={form.initial_balance} onChange={set("initial_balance")} />
            </label>
            {isB3 ? (
              <label>
                Contratos por ordem
                <input type="number" min="1" step="1" required value={form.order_lots} onChange={set("order_lots")} />
              </label>
            ) : forex ? (
              <label>
                Lotes por ordem
                <input type="number" min="0.01" step="0.01" required value={form.order_lots} onChange={set("order_lots")} />
              </label>
            ) : (
              <label>
                Valor por ordem
                <input type="number" min="1" step="any" required value={form.order_size_quote} onChange={set("order_size_quote")} />
              </label>
            )}
            <label>
              Stop loss (%)
              <input type="number" min="0.1" max="50" step="any" value={form.stop_loss_pct} onChange={set("stop_loss_pct")} />
            </label>
            <label>
              Risco por operação (%)
              <span className="hint">Vazio = tamanho fixo. Com valor, o tamanho sai do saldo e do stop.</span>
              <input type="number" min="0.05" max="10" step="0.05" placeholder="Fixo" value={form.risk_pct} onChange={set("risk_pct")} />
            </label>
            {margin && (
              <label>
                Alavancagem máxima
                <span className="hint">Vazio = sem limite.</span>
                <input type="number" min="0.1" max="500" step="0.1" placeholder="Sem limite" value={form.max_leverage} onChange={set("max_leverage")} />
              </label>
            )}
            <label>
              Alvo de lucro (%)
              <input type="number" min="0.1" max="500" step="any" value={form.take_profit_pct} onChange={set("take_profit_pct")} />
            </label>
          </div>
          {selected && (
            <FiltersFields value={filters} onChange={setFilters} timeframe={params.timeframe || selected.timeframe} family={selected.family} />
          )}
          <label>
            Período de confirmação
            <span className="hint">Parte final do período separada para conferir se o resultado se mantém em dados que você não usou para ajustar.</span>
            <select value={oos} onChange={(e) => setOos(e.target.value)}>
              <option value="0">Não separar</option>
              <option value="20">Últimos 20%</option>
              <option value="30">Últimos 30%</option>
              <option value="40">Últimos 40%</option>
              <option value="50">Últimos 50%</option>
            </select>
          </label>
          <details>
            <summary>Custos e limites</summary>
            <div className="grid-2" style={{ marginTop: 12 }}>
              <label>
                Taxa por lado (%)
                <input type="number" min="0" max="1" step="any" value={form.fee_pct} onChange={set("fee_pct")} />
              </label>
              <label>
                Slippage (0,01% = 1)
                <input type="number" min="0" max="200" step="any" value={form.slippage_bps} onChange={set("slippage_bps")} />
              </label>
              <label>
                Perda máxima no dia
                <input type="number" min="1" step="any" value={form.max_daily_loss_quote} onChange={set("max_daily_loss_quote")} />
              </label>
            </div>
          </details>
          <ErrorText>{action.error}</ErrorText>
          <button className="btn btn-primary" disabled={action.busy || !strategy}>
            {action.busy ? "Baixando histórico e simulando…" : "Rodar backtest"}
          </button>
        </form>

        <div>{result ? <ResultView r={result} /> : <EmptyResult />}</div>
      </div>
      {result && result.ohlc?.length > 1 && (
        <section className="section">
          <CandleChart
            ohlc={result.ohlc}
            trades={result.trades}
            heading={
              <div style={{ display: "grid", gap: 4 }}>
                <h2>Operações no gráfico</h2>
                <p className="muted small">C marca entrada comprada e V entrada vendida; a marca de saída mostra o resultado. Arraste para navegar e use a rolagem para aproximar.</p>
              </div>
            }
          />
        </section>
      )}
    </>
  );
}

function EmptyResult() {
  return (
    <div className="panel" style={{ display: "grid", gap: 10 }}>
      <h2>Como o teste funciona</h2>
      <p className="muted">
        O robô decide no fechamento de cada candle e a ordem entra na abertura do seguinte, como na operação real. Stop e alvo
        são checados pelas máximas e mínimas; se os dois forem atingidos no mesmo candle, conta o stop. Taxa e slippage entram
        em toda compra e venda.
      </p>
      <p className="muted">Para ter confiança no resultado, procure mais de 100 operações e um período com alta, queda e lateralização.</p>
    </div>
  );
}

function ResultView({ r }: { r: Result }) {
  const m = r.metrics;
  const unit = r.market === "b3" ? "" : r.market === "forex" ? "" : r.symbol.endsWith("USDT") ? " USDT" : "";
  const pre = r.market === "b3" ? "R$ " : "";
  const range = `${new Date(r.start).toLocaleDateString("pt-BR")} a ${new Date(r.end).toLocaleDateString("pt-BR")}`;
  const beat = m.return_pct - m.buy_hold_pct;

  return (
    <div style={{ display: "grid", gap: 24 }}>
      <p className="verdict">
        {m.trades === 0 ? (
          <>Nenhuma operação em {r.symbol} de {range}.</>
        ) : (
          <>
            Em <strong>{m.trades} operações</strong>
            {m.short_trades > 0 && ` (${m.long_trades} compradas e ${m.short_trades} vendidas)`} em {r.symbol} ({r.timeframe}) de {range}, o robô acertou{" "}
            <strong>{money(m.win_rate_pct, 1)}%</strong> e o saldo foi de {pre}{money(r.config.initial_balance)} para{" "}
            <strong className={pnlClass(m.net_pnl)}>{pre}{money(m.final_balance)}{unit}</strong> ({pct(m.return_pct)}). Comprar e segurar o
            mesmo tamanho de posição daria {pct(m.buy_hold_pct)}
            {beat >= 0 ? `; o robô ficou ${money(beat)} pontos percentuais acima.` : `, ${money(-beat)} pontos percentuais acima do robô.`}
          </>
        )}
      </p>

      {r.analysis && r.analysis.trades > 0 && <StatsView a={r.analysis} pre={pre} />}

      {r.segments?.length === 2 && <SplitTable segments={r.segments} />}
      {r.baseline && (
        <FilterCompare
          base={r.baseline.metrics}
          withF={m}
          baseSegments={r.baseline.segments}
          segments={r.segments}
          filtered={r.filtered_entries}
          reasons={r.filter_reasons}
        />
      )}

      <dl className="figures" style={{ margin: 0 }}>
        <div>
          <dt>Taxa de acerto</dt>
          <dd>{money(m.win_rate_pct, 1)}%</dd>
          <span className="muted small">{m.wins} ganhos, {m.losses} perdas</span>
        </div>
        <div>
          <dt>Resultado médio por operação</dt>
          <dd className={pnlClass(m.expectancy)}>{signed(m.expectancy)}</dd>
          <span className="muted small">{pct(m.expectancy_pct)} do valor aplicado</span>
        </div>
        <div>
          <dt>Ganho médio ÷ perda média</dt>
          <dd>{m.payoff === null ? "—" : money(m.payoff)}</dd>
          <span className="muted small">{signed(m.avg_win)} contra {signed(m.avg_loss)}</span>
        </div>
        <div>
          <dt>Fator de lucro</dt>
          <dd className={m.profit_factor !== null && m.profit_factor < 1 ? "loss" : ""}>{m.profit_factor === null ? "—" : money(m.profit_factor)}</dd>
          <span className="muted small">acima de 1 = ganhos superam perdas</span>
        </div>
        <div>
          <dt>Queda máxima do saldo</dt>
          <dd className="loss">-{money(m.max_drawdown_pct)}%</dd>
          <span className="muted small">pior sequência: {m.max_consecutive_losses} perdas</span>
        </div>
        <div>
          <dt>Tempo posicionado</dt>
          <dd>{money(m.exposure_pct, 0)}%</dd>
          <span className="muted small">média de {hold(m.avg_hold_minutes)} por operação</span>
        </div>
      </dl>

      <div style={{ display: "grid", gap: 8 }}>
        {r.warnings.map((w, i) => (
          <p key={i} className={`notice small ${i === r.warnings.length - 1 ? "" : ""}`}>
            {w}
          </p>
        ))}
      </div>

      {r.equity.length > 1 && (
        <section style={{ display: "grid", gap: 10 }}>
          <h2>Evolução do saldo</h2>
          <EquityChart points={r.equity} initial={r.config.initial_balance} />
          <p className="muted small">Taxas pagas no período: {pre}{money(m.fees_total)}{unit}. {r.candles.toLocaleString("pt-BR")} candles analisados.</p>
        </section>
      )}

      {r.monthly.length > 0 && (
        <section style={{ display: "grid", gap: 10 }}>
          <h2>Mês a mês</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Mês</th>
                  <th className="num">Operações</th>
                  <th className="num">Acerto</th>
                  <th className="num">Resultado</th>
                </tr>
              </thead>
              <tbody>
                {r.monthly.map((x) => (
                  <tr key={x.month}>
                    <td>{new Date(`${x.month}-15`).toLocaleDateString("pt-BR", { month: "long", year: "numeric" })}</td>
                    <td className="num">{x.trades}</td>
                    <td className="num">{money((x.wins / x.trades) * 100, 0)}%</td>
                    <td className={`num ${pnlClass(x.pnl)}`}>{signed(x.pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {r.trades.length > 0 && (
        <section style={{ display: "grid", gap: 10 }}>
          <h2>Operações</h2>
          {m.trades > r.trades.length && <p className="muted small">Mostrando as {r.trades.length} mais recentes de {m.trades}.</p>}
          <div className="table-wrap" style={{ maxHeight: 480, overflowY: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Lado</th>
                  <th>Entrada</th>
                  <th>Saída</th>
                  <th className="num">Preço de entrada</th>
                  <th className="num">Preço de saída</th>
                  <th className="num">Resultado</th>
                  <th>Motivo da saída</th>
                </tr>
              </thead>
              <tbody>
                {[...r.trades].reverse().map((t, i) => (
                  <tr key={i}>
                    <td className={t.side === "short" ? "side-SELL" : "side-BUY"}>{t.side === "short" ? "Vendido" : "Comprado"}</td>
                    <td>{dateTime(new Date(t.entry_time).toISOString())}</td>
                    <td>{dateTime(new Date(t.exit_time).toISOString())}</td>
                    <td className="num">{price(t.entry_price)}</td>
                    <td className="num">{price(t.exit_price)}</td>
                    <td className={`num ${pnlClass(t.pnl)}`}>
                      {signed(t.pnl)} <span className="muted small">({pct(t.return_pct)})</span>
                    </td>
                    <td className="muted">{t.exit_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      <p className="muted small">
        <Link href="/painel/robos/novo">Criar um robô com esta estratégia</Link>
      </p>
    </div>
  );
}

export default function BacktestPage() {
  return (
    <Suspense>
      <BacktestView />
    </Suspense>
  );
}
