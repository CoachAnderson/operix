"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { PageHead } from "@/components/ui";
import { api } from "@/lib/api";
import { money, pnlClass } from "@/lib/format";

interface Seg {
  trades: number;
  win_rate_pct: number;
  profit_factor: number | null;
  return_pct: number;
  net_pnl: number;
  buy_hold_pct: number;
}
interface Row {
  strategy: string;
  name: string;
  timeframe: string;
  verdict: "approved" | "marginal" | "only_fit" | "rejected" | "few_trades" | "error";
  error?: string;
  trades?: number;
  win_rate_pct?: number;
  breakeven_win_rate_pct?: number | null;
  profit_factor?: number | null;
  return_pct?: number;
  buy_hold_pct?: number;
  max_drawdown_pct?: number;
  fit?: Seg | null;
  confirm?: Seg | null;
  start?: number;
  end?: number;
}
interface Job {
  id: string;
  status: "running" | "done" | "error";
  symbol: string;
  days: number;
  done: number;
  total: number;
  current: string;
  results: Row[];
  cached: boolean;
  error?: string;
  oos_pct?: number;
  finished_at?: number;
}

const VERDICT: Record<Row["verdict"], { label: string; tone: string; hint: string }> = {
  approved: { label: "Funcionou nos dois períodos", tone: "gain", hint: "Lucrou no ajuste e na confirmação, com operações suficientes." },
  marginal: { label: "Lucro fraco nos dois períodos", tone: "warn-text", hint: "Ganhou nos dois trechos, mas tão pouco que os custos ou um período ruim apagam o resultado." },
  only_fit: { label: "Só no primeiro período", tone: "warn-text", hint: "Ganhou no ajuste e falhou na confirmação: provável sorte daquele trecho." },
  rejected: { label: "Não funcionou", tone: "loss", hint: "Perdeu no período de ajuste." },
  few_trades: { label: "Poucas operações", tone: "muted", hint: "Operou pouco para concluir alguma coisa." },
  error: { label: "Não testada", tone: "muted", hint: "" },
};
const TF_LABEL: Record<string, string> = { "1m": "1 min", "5m": "5 min", "15m": "15 min", "30m": "30 min", "1h": "1 hora", "4h": "4 horas", "1d": "diário" };
const pct = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${money(v, d)}%`);
const pf = (v: number | null | undefined) => (v === null || v === undefined ? "—" : money(v, 2));

export default function RecommendPage() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [days, setDays] = useState(180);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const s = new URLSearchParams(window.location.search).get("simbolo");
    if (s && /^[A-Z0-9]{5,20}$/.test(s)) setSymbol(s);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  async function poll(id: string) {
    try {
      const j = await api<Job>(`/backtest/recommend/${id}`);
      setJob(j);
      if (j.status === "running") timer.current = setTimeout(() => poll(id), 1500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao acompanhar a análise");
    }
  }

  async function start(e: React.FormEvent) {
    e.preventDefault();
    if (timer.current) clearTimeout(timer.current);
    setError(null);
    setJob(null);
    try {
      const j = await api<Job>("/backtest/recommend", { json: { symbol: symbol.trim().toUpperCase().replace("/", ""), days } });
      setJob(j);
      if (j.status === "running") timer.current = setTimeout(() => poll(j.id), 1200);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Não foi possível começar a análise");
    }
  }

  const running = job?.status === "running";
  const best = job?.status === "done" ? job.results.find((r) => r.verdict === "approved") : undefined;
  const link = (r: Row, base: string) => `${base}?simbolo=${job?.symbol}&estrategia=${r.strategy}&tf=${r.timeframe}`;

  return (
    <div style={{ display: "grid", gap: 20 }}>
      <PageHead
        title="Qual estratégia usar?"
        lead="Testa todas as estratégias, em vários tempos gráficos, no histórico da moeda escolhida, com as taxas da Binance, e mostra qual se saiu melhor no período que não foi usado para escolher."
      />

      <form onSubmit={start} className="grid-2" style={{ alignItems: "end", maxWidth: 720 }}>
        <label>
          Par da Binance
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} pattern="[A-Za-z0-9\/]{5,20}" required placeholder="BTCUSDT" />
        </label>
        <label>
          Período
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={90}>Últimos 3 meses</option>
            <option value={180}>Últimos 6 meses</option>
            <option value={365}>Último ano</option>
          </select>
        </label>
        <button className="btn btn-primary" disabled={running} style={{ width: "fit-content" }}>
          {running ? "Analisando…" : "Analisar"}
        </button>
      </form>
      <p className="muted small" style={{ maxWidth: 720 }}>
        Cada combinação é testada só comprada (mercado à vista), com 0,1% de taxa por lado e 0,05% de escorregamento, stop de 2% e alvo de 4%. Os últimos 30%
        do período ficam para confirmação. Gráficos de 1 e 5 minutos usam no máximo 30 e 100 dias de histórico.
      </p>

      {error && <p className="loss">{error}</p>}

      {job && running && (
        <div className="panel" role="status" aria-live="polite" style={{ display: "grid", gap: 8 }}>
          <strong>
            Testando {job.done + 1} de {job.total}: {job.current || "baixando histórico"}
          </strong>
          <div style={{ height: 8, borderRadius: 4, background: "var(--rule)", overflow: "hidden" }}>
            <div style={{ width: `${(job.done / job.total) * 100}%`, height: "100%", background: "var(--accent)", transition: "width .3s" }} />
          </div>
          <span className="muted small">Leva de alguns segundos a poucos minutos. Pode sair da tela e voltar depois.</span>
        </div>
      )}

      {job?.status === "error" && <p className="loss">{job.error}</p>}

      {job?.status === "done" && (
        <>
          <div className={`rb-verdict ${best ? "gain" : "loss"}`} style={{ display: "grid", gap: 8 }}>
            {best ? (
              <>
                <strong>
                  Melhor para {job.symbol}: {best.name} em {TF_LABEL[best.timeframe] ?? best.timeframe}
                </strong>
                <span>
                  Na confirmação: {best.confirm?.trades} operações, acerto de {money(best.confirm?.win_rate_pct ?? 0, 1)}%, fator de lucro {pf(best.confirm?.profit_factor)}, resultado{" "}
                  {pct(best.confirm?.return_pct, 2)} (comprar e segurar: {pct(best.confirm?.buy_hold_pct, 2)}). Queda máxima no período todo: {money(best.max_drawdown_pct ?? 0, 1)}%.
                  {(best.confirm?.return_pct ?? 0) < (best.confirm?.buy_hold_pct ?? 0) &&
                    " Nesse trecho, só comprar e segurar a moeda teria rendido mais; o robô vale pelo risco menor (fica fora do mercado parte do tempo)."}
                </span>
                <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <Link className="btn" href={link(best, "/painel/backtest")}>Ver no backtest</Link>
                  <Link className="btn btn-primary" href={link(best, "/painel/robos/novo")}>Criar robô com esta (comece na simulação)</Link>
                </span>
              </>
            ) : (
              <>
                <strong>Nenhuma estratégia passou na confirmação em {job.symbol}.</strong>
                <span>
                  Nenhuma combinação lucrou nos dois períodos com operações suficientes, depois dos custos. Melhor não ligar robô nesta moeda agora: tente outro par
                  ou um período diferente.
                </span>
              </>
            )}
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Estratégia</th>
                  <th>Resultado</th>
                  <th className="num">Operações</th>
                  <th className="num">Acerto (empata com)</th>
                  <th className="num">Confirmação</th>
                  <th className="num">Ajuste</th>
                  <th className="num">Queda máx.</th>
                  <th>
                    <span className="sr-only">Ações</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {job.results.map((r) => (
                  <tr key={`${r.strategy}-${r.timeframe}`}>
                    <td>
                      <strong>{r.name}</strong>
                      <span className="muted small"> · {TF_LABEL[r.timeframe] ?? r.timeframe}</span>
                    </td>
                    <td className={`small ${VERDICT[r.verdict].tone}`} title={r.error || VERDICT[r.verdict].hint}>
                      {VERDICT[r.verdict].label}
                    </td>
                    {r.verdict === "error" ? (
                      <td colSpan={5} className="muted small">
                        {r.error}
                      </td>
                    ) : (
                      <>
                        <td className="num">{r.trades}</td>
                        <td className="num" style={{ whiteSpace: "nowrap" }}>
                          {money(r.win_rate_pct ?? 0, 1)}%{" "}
                          <span className="muted small">({r.breakeven_win_rate_pct ? `${money(r.breakeven_win_rate_pct, 1)}%` : "—"})</span>
                        </td>
                        <td className={`num ${pnlClass(r.confirm?.return_pct ?? 0)}`} title={`${r.confirm?.trades ?? 0} operações · fator de lucro ${pf(r.confirm?.profit_factor)}`}>
                          <strong>{pct(r.confirm?.return_pct, 2)}</strong>
                        </td>
                        <td className={`num ${pnlClass(r.fit?.return_pct ?? 0)}`} title={`${r.fit?.trades ?? 0} operações · fator de lucro ${pf(r.fit?.profit_factor)}`}>
                          {pct(r.fit?.return_pct, 2)}
                        </td>
                        <td className="num loss">-{money(r.max_drawdown_pct ?? 0, 1)}%</td>
                      </>
                    )}
                    <td style={{ whiteSpace: "nowrap" }}>
                      {r.verdict !== "error" && (
                        <Link className="btn btn-quiet" style={{ paddingInline: 6 }} href={link(r, "/painel/backtest")}>
                          Testar
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small">
            {job.cached ? "Resultado de uma análise recente desta moeda e período (vale por 1 hora). " : ""}
            Ajuste = primeiros {100 - (job.oos_pct ?? 30)}% do período; confirmação = últimos {job.oos_pct ?? 30}%, que não serviram para escolher. Resultado
            passado não garante resultado futuro: rode de novo de tempos em tempos e comece sempre pela simulação.
          </p>
        </>
      )}
    </div>
  );
}
