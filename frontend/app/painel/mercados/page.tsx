"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { PageHead } from "@/components/ui";
import { api } from "@/lib/api";
import { money } from "@/lib/format";

interface Row {
  symbol: string;
  base: string;
  status: string;
  status_label: string;
  tradable: boolean;
  price: number | null;
  change_24h_pct: number | null;
  range_24h_pct: number | null;
  quote_volume_24h: number;
  trades_24h: number;
  change_1h_pct: number | null;
  range_1h_pct: number | null;
}
interface Scan {
  quote: string;
  quotes: { quote: string; count: number }[];
  rows: Row[];
  hour_top: number;
  updated_at: number;
}

type SortKey = "quote_volume_24h" | "change_24h_pct" | "change_1h_pct" | "range_1h_pct" | "range_24h_pct" | "trades_24h";
const SORTS: { key: SortKey; label: string }[] = [
  { key: "quote_volume_24h", label: "Volume 24h" },
  { key: "range_1h_pct", label: "Movimento 1h" },
  { key: "change_1h_pct", label: "Variação 1h" },
  { key: "change_24h_pct", label: "Variação 24h" },
  { key: "range_24h_pct", label: "Movimento 24h" },
  { key: "trades_24h", label: "Negócios 24h" },
];
const MAIN_QUOTES = ["USDT", "BRL", "USDC", "FDUSD", "BTC", "ETH"];

const pct = (v: number | null, d = 2) => (v === null ? "—" : `${v > 0 ? "+" : ""}${money(v, d)}%`);
const tone = (v: number | null) => (v === null || v === 0 ? "" : v > 0 ? "gain" : "loss");
const px = (v: number | null) => (v === null ? "—" : money(v, v >= 100 ? 2 : v >= 1 ? 4 : v >= 0.01 ? 6 : 8));
function compact(v: number): string {
  if (v >= 1e9) return `${money(v / 1e9, 1)} bi`;
  if (v >= 1e6) return `${money(v / 1e6, 1)} mi`;
  if (v >= 1e3) return `${money(v / 1e3, 1)} mil`;
  return money(v, 0);
}

export default function MarketsPage() {
  const [quote, setQuote] = useState("USDT");
  const [data, setData] = useState<Scan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("quote_volume_24h");
  const [showPaused, setShowPaused] = useState(false);
  const [minVolume, setMinVolume] = useState(true);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      if (!document.hidden) {
        try {
          const d = await api<Scan>(`/market/binance?quote=${quote}`);
          if (!stop) {
            setData(d);
            setError(null);
          }
        } catch (e) {
          if (!stop) setError(e instanceof Error ? e.message : "Não foi possível consultar a Binance");
        }
      }
      if (!stop) timer = setTimeout(load, 60_000);
    };
    setData((d) => (d?.quote === quote ? d : null));
    void load();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [quote]);

  const quotes = useMemo(() => {
    const all = data?.quotes.map((q) => q.quote) ?? [];
    return [...MAIN_QUOTES.filter((q) => all.length === 0 || all.includes(q)), ...all.filter((q) => !MAIN_QUOTES.includes(q)).slice(0, 6)];
  }, [data]);

  const rows = useMemo(() => {
    if (!data) return [];
    const q = query.trim().toUpperCase();
    const volFloor = quote === "USDT" || quote === "USDC" || quote === "FDUSD" ? 1_000_000 : 0;
    return data.rows
      .filter((r) => showPaused || r.status === "TRADING")
      .filter((r) => !q || r.symbol.includes(q) || r.base.includes(q))
      .filter((r) => !minVolume || r.quote_volume_24h >= volFloor)
      .sort((a, b) => {
        const x = a[sort] ?? -Infinity;
        const y = b[sort] ?? -Infinity;
        return (y as number) - (x as number);
      });
  }, [data, query, sort, showPaused, minVolume, quote]);

  const trading = data?.rows.filter((r) => r.status === "TRADING").length ?? 0;
  const paused = (data?.rows.length ?? 0) - trading;

  return (
    <div style={{ display: "grid", gap: 20 }}>
      <PageHead
        title="Mercados"
        lead="Pares disponíveis agora na Binance à vista, com o quanto cada um está se mexendo. Clique em Testar para rodar um backtest ou em Robô para criar um robô com o par."
      />

      <p className="notice small">
        <strong>A Binance à vista funciona 24 horas por dia, todos os dias.</strong>
        Todo par marcado como &quot;Negociando&quot; está disponível agora. O que muda com o horário é o volume e o quanto o preço se mexe: veja as colunas da
        última hora. Para robôs de 1 minuto, prefira pares com movimento na última hora bem maior que o custo de ida e volta (cerca de 0,2% com a taxa
        padrão).
      </p>

      <div style={{ display: "grid", gap: 12 }}>
        <div className="presets" role="group" aria-label="Moeda de cotação">
          {quotes.map((q) => (
            <button key={q} type="button" className="btn" aria-pressed={quote === q} onClick={() => setQuote(q)}>
              {q}
            </button>
          ))}
        </div>
        <div className="grid-2" style={{ alignItems: "end" }}>
          <label>
            Buscar
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="BTC, SOL, PEPE…" />
          </label>
          <label>
            Ordenar por
            <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
              {SORTS.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label} (maior primeiro)
                </option>
              ))}
            </select>
          </label>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 20px" }}>
          <label className="check">
            <input type="checkbox" checked={minVolume} onChange={(e) => setMinVolume(e.target.checked)} /> Só pares com volume relevante
          </label>
          <label className="check">
            <input type="checkbox" checked={showPaused} onChange={(e) => setShowPaused(e.target.checked)} /> Mostrar pares pausados ({paused})
          </label>
        </div>
      </div>

      {error && <p className="loss">{error}</p>}
      {!data && !error && <p className="muted">Consultando a Binance…</p>}

      {data && (
        <>
          <p className="muted small">
            {trading} pares em {quote} negociando agora · mostrando {rows.length} · atualizado às {new Date(data.updated_at).toLocaleTimeString("pt-BR")} (a cada
            minuto).
            {data.hour_top > 0 && ` Colunas da última hora: os ${data.hour_top} pares com mais volume.`}
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Par</th>
                  <th className="num">Preço</th>
                  <th className="num">Variação 1h</th>
                  <th className="num">Movimento 1h</th>
                  <th className="num">Variação 24h</th>
                  <th className="num">Volume 24h ({quote})</th>
                  <th className="num">Negócios 24h</th>
                  <th>
                    <span className="sr-only">Ações</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 300).map((r) => (
                  <tr key={r.symbol} className={r.status === "TRADING" ? "" : "muted"}>
                    <td>
                      <strong>{r.base}</strong>
                      <span className="muted">/{quote}</span>
                      {r.status !== "TRADING" && <span className="small loss"> · {r.status_label}</span>}
                    </td>
                    <td className="num">{px(r.price)}</td>
                    <td className={`num ${tone(r.change_1h_pct)}`}>{pct(r.change_1h_pct)}</td>
                    <td className="num" title="Diferença entre a máxima e a mínima da última hora">
                      {r.range_1h_pct === null ? "—" : `${money(r.range_1h_pct, 2)}%`}
                    </td>
                    <td className={`num ${tone(r.change_24h_pct)}`}>{pct(r.change_24h_pct)}</td>
                    <td className="num">{compact(r.quote_volume_24h)}</td>
                    <td className="num">{compact(r.trades_24h)}</td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {r.tradable ? (
                        <>
                          <Link className="btn btn-quiet" style={{ paddingInline: 6 }} href={`/painel/backtest?simbolo=${r.symbol}`} aria-label={`Testar ${r.symbol} no backtest`}>
                            Testar
                          </Link>
                          <Link className="btn btn-quiet" style={{ paddingInline: 6 }} href={`/painel/robos/novo?simbolo=${r.symbol}`} aria-label={`Criar robô com ${r.symbol}`}>
                            Robô
                          </Link>
                        </>
                      ) : (
                        <span className="muted small">indisponível</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {rows.length > 300 && <p className="muted small">Mostrando os 300 primeiros. Use a busca para achar um par específico.</p>}
          <p className="muted small">
            Movimento 1h = diferença entre a máxima e a mínima da última hora, em % do preço. Dados públicos da Binance; a disponibilidade de cada par pode
            variar conforme o país da sua conta.
          </p>
        </>
      )}
    </div>
  );
}
