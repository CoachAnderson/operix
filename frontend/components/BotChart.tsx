"use client";

import { useEffect, useRef, useState } from "react";
import type { IChartApi, IPriceLine, ISeriesApi, ISeriesMarkersPluginApi, SeriesMarker, Time } from "lightweight-charts";
import { api } from "@/lib/api";
import { tokenColor } from "@/lib/appearance";
import { money } from "@/lib/format";
import { useAppearanceVersion } from "./Appearance";
import { FullscreenFrame } from "./FullscreenFrame";

interface ChartOrder {
  time: number;
  side: "BUY" | "SELL";
  price: number;
  exit: boolean;
  pnl: number | null;
  reason: string;
}
interface ChartData {
  timeframe: string;
  ohlc: [number, number, number, number, number][];
  orders: ChartOrder[];
  signals: { time: number; side: "BUY" | "SELL"; price: number; status: string }[];
  position: { side: "long" | "short"; avg_price: number; stop: number | null; take: number | null; opened_at: number } | null;
}

const fmt = (p: number) => money(p, p < 10 ? 5 : p < 100 ? 4 : 2);

/**
 * Gráfico do robô: candles da corretora (pela conexão do próprio cliente) com as entradas e saídas do robô
 * e as linhas de entrada, stop e alvo da posição aberta. Atualiza sozinho.
 * TradingView Lightweight Charts (Apache 2.0): o logotipo no canto é a atribuição exigida pela licença.
 */
export function BotChart({ botId, heading }: { botId: string; heading?: React.ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const lines = useRef<IPriceLine[]>([]);
  const framed = useRef(false);
  const levels = useRef<number[]>([]); // entrada, stop e alvo: a escala de preço sempre os inclui
  const [data, setData] = useState<ChartData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [ready, setReady] = useState(0);
  const version = useAppearanceVersion();

  // Busca periódica (mais rápida em 1 minuto); pausa com a aba escondida.
  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      if (!document.hidden) {
        try {
          const d = await api<ChartData>(`/bots/${botId}/chart?limit=300`);
          if (stop) return;
          setData(d);
          setError(null);
          setUpdated(new Date());
        } catch (e) {
          if (!stop) setError(e instanceof Error ? e.message : "Não foi possível carregar o gráfico");
        }
      }
      if (!stop) timer = setTimeout(load, data?.timeframe === "1m" ? 10_000 : 30_000);
    };
    void load();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [botId, data?.timeframe]);

  // Cria o gráfico (e recria quando o tema muda, para pegar as cores novas).
  useEffect(() => {
    if (!box.current) return;
    let disposed = false;
    void import("lightweight-charts").then(({ createChart, CandlestickSeries, createSeriesMarkers, ColorType }) => {
      if (disposed || !box.current) return;
      const rule = tokenColor("--rule");
      const c = createChart(box.current, {
        autoSize: true,
        layout: {
          background: { type: ColorType.Solid, color: tokenColor("--surface") },
          textColor: tokenColor("--muted"),
          fontFamily: getComputedStyle(document.body).fontFamily,
          attributionLogo: true,
        },
        grid: { vertLines: { color: rule }, horzLines: { color: rule } },
        rightPriceScale: { borderColor: rule },
        timeScale: { borderColor: rule, timeVisible: true },
        localization: { locale: "pt-BR", priceFormatter: fmt },
        crosshair: { horzLine: { labelBackgroundColor: tokenColor("--ink") }, vertLine: { labelBackgroundColor: tokenColor("--ink") } },
      });
      const gain = tokenColor("--gain");
      const loss = tokenColor("--loss");
      const s = c.addSeries(CandlestickSeries, {
        upColor: gain,
        downColor: loss,
        borderUpColor: gain,
        borderDownColor: loss,
        wickUpColor: gain,
        wickDownColor: loss,
        autoscaleInfoProvider: (base: () => { priceRange: { minValue: number; maxValue: number } } | null) => {
          const r = base();
          if (!r || !levels.current.length) return r;
          return {
            ...r,
            priceRange: {
              minValue: Math.min(r.priceRange.minValue, ...levels.current),
              maxValue: Math.max(r.priceRange.maxValue, ...levels.current),
            },
          };
        },
      });
      chart.current = c;
      series.current = s;
      markers.current = createSeriesMarkers(s, []);
      lines.current = [];
      framed.current = false;
      setReady((x) => x + 1);
    });
    return () => {
      disposed = true;
      chart.current?.remove();
      chart.current = null;
      series.current = null;
      markers.current = null;
    };
  }, [version]);

  // Atualiza candles, marcas e linhas sem perder o zoom de quem está olhando.
  useEffect(() => {
    const c = chart.current;
    const s = series.current;
    if (!c || !s || !data || data.ohlc.length < 2) return;
    const tz = -new Date().getTimezoneOffset() * 60; // a biblioteca mostra UTC; desloca para o fuso do navegador
    const toTime = (ms: number) => (Math.floor(ms / 1000) + tz) as Time;
    const first = data.ohlc[0][0];
    const step = data.ohlc[1][0] - first;
    const last = data.ohlc[data.ohlc.length - 1][0];
    const snap = (ms: number) => Math.min(last, first + Math.floor((ms - first) / step) * step);
    s.setData(data.ohlc.map(([t, o, h, l, cl]) => ({ time: toTime(t), open: o, high: h, low: l, close: cl })));

    const ink = tokenColor("--ink");
    const gain = tokenColor("--gain");
    const loss = tokenColor("--loss");
    const accent = tokenColor("--accent") || ink;
    const ms: SeriesMarker<Time>[] = [];
    for (const o of data.orders) {
      if (o.time < first) continue;
      const buy = o.side === "BUY";
      ms.push(
        o.exit
          ? {
              time: toTime(snap(o.time)),
              position: buy ? "belowBar" : "aboveBar",
              shape: buy ? "arrowUp" : "arrowDown",
              color: (o.pnl ?? 0) > 0 ? gain : loss,
              text: `Saída ${(o.pnl ?? 0) > 0 ? "+" : ""}${money(o.pnl ?? 0)}`,
            }
          : { time: toTime(snap(o.time)), position: buy ? "belowBar" : "aboveBar", shape: buy ? "arrowUp" : "arrowDown", color: ink, text: buy ? "C" : "V" },
      );
    }
    for (const x of data.signals) {
      if (x.time < first) continue;
      ms.push({ time: toTime(snap(x.time)), position: x.side === "BUY" ? "belowBar" : "aboveBar", shape: "circle", color: accent, text: x.side === "BUY" ? "Sinal C" : "Sinal V" });
    }
    ms.sort((a, b) => (a.time as number) - (b.time as number));
    markers.current?.setMarkers(ms);

    for (const l of lines.current) s.removePriceLine(l);
    lines.current = [];
    const p = data.position;
    levels.current = p ? [p.avg_price, p.stop, p.take].filter((v): v is number => typeof v === "number") : [];
    if (p) {
      lines.current.push(s.createPriceLine({ price: p.avg_price, color: ink, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: p.side === "short" ? "Venda" : "Compra" }));
      if (p.stop) lines.current.push(s.createPriceLine({ price: p.stop, color: loss, lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title: "Stop" }));
      if (p.take) lines.current.push(s.createPriceLine({ price: p.take, color: gain, lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title: "Alvo" }));
    }
    if (!framed.current) {
      framed.current = true; // só na primeira vez: depois respeita o zoom do usuário
      const n = data.ohlc.length;
      c.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 120), to: n + 3 });
    }
  }, [data, ready]);

  const p = data?.position;
  return (
    <FullscreenFrame title="Operações do robô no gráfico" heading={heading}>
      {() => (
        <figure className="chart" style={{ padding: 0, margin: 0, height: "100%", display: "grid", gridTemplateRows: "minmax(0, 1fr) auto" }}>
          <div
            ref={box}
            className="chart-box chart-box-candles"
            role="img"
            aria-label="Gráfico de candles com as compras (C), vendas (V) e saídas do robô, e as linhas de entrada, stop e alvo da posição aberta"
          />
          <figcaption className="muted small" style={{ padding: "8px 12px", display: "flex", flexWrap: "wrap", gap: "4px 16px" }}>
            <span>C = compra · V = venda · Saída com o resultado{data?.signals.length ? " · bolinhas = sinais" : ""}</span>
            {p && (
              <span>
                Posição {p.side === "short" ? "vendida" : "comprada"} a {fmt(p.avg_price)}
                {p.stop ? ` · stop ${fmt(p.stop)}` : ""}
                {p.take ? ` · alvo ${fmt(p.take)}` : ""}
              </span>
            )}
            {error ? <span className="loss">{error}</span> : updated && <span>Atualizado às {updated.toLocaleTimeString("pt-BR")}</span>}
          </figcaption>
        </figure>
      )}
    </FullscreenFrame>
  );
}
