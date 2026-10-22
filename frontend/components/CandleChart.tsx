"use client";

import { useEffect, useRef } from "react";
import { money } from "@/lib/format";
import { FullscreenFrame } from "./FullscreenFrame";
import { useAppearanceVersion } from "./Appearance";

export type OHLC = [number, number, number, number, number]; // tempo (ms), abertura, máxima, mínima, fechamento
export interface ChartTrade {
  side?: "long" | "short";
  entry_time: number;
  exit_time: number;
  entry_price: number;
  exit_price: number;
  pnl: number;
  exit_reason: string;
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * Candles com as entradas e saídas marcadas, usando TradingView Lightweight Charts (Apache 2.0).
 * O logotipo do TradingView no canto é a atribuição exigida pela licença; não remova.
 */
export function CandleChart({ ohlc, trades, title = "Operações no gráfico", heading }: { ohlc: OHLC[]; trades: ChartTrade[]; title?: string; heading?: React.ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const version = useAppearanceVersion(); // redesenha com as cores do tema quando ele muda

  useEffect(() => {
    if (!box.current || ohlc.length < 2) return;
    let disposed = false;
    let cleanup = () => {};

    void import("lightweight-charts").then(({ createChart, CandlestickSeries, createSeriesMarkers, ColorType }) => {
      if (disposed || !box.current) return;
      // A biblioteca exibe UTC; desloca para o fuso do navegador.
      const tz = -new Date().getTimezoneOffset() * 60;
      const toTime = (ms: number) => (Math.floor(ms / 1000) + tz) as never;
      const first = ohlc[0][0];
      const step = ohlc[1][0] - ohlc[0][0];
      const last = ohlc[ohlc.length - 1][0];
      const snap = (ms: number) => Math.min(last, first + Math.floor((ms - first) / step) * step);

      const ink = cssVar("--ink");
      const muted = cssVar("--muted");
      const rule = cssVar("--rule");
      const gain = cssVar("--gain");
      const loss = cssVar("--loss");

      const chart = createChart(box.current, {
        autoSize: true, // acompanha o tamanho da caixa, inclusive em tela cheia
        layout: {
          background: { type: ColorType.Solid, color: cssVar("--surface") },
          textColor: muted,
          fontFamily: getComputedStyle(document.body).fontFamily,
          attributionLogo: true,
        },
        grid: { vertLines: { color: rule }, horzLines: { color: rule } },
        rightPriceScale: { borderColor: rule },
        timeScale: { borderColor: rule, timeVisible: step < 86_400_000 },
        localization: { locale: "pt-BR", priceFormatter: (p: number) => money(p, p >= 100 ? 2 : 4) },
        crosshair: { horzLine: { labelBackgroundColor: ink }, vertLine: { labelBackgroundColor: ink } },
      });
      const series = chart.addSeries(CandlestickSeries, {
        upColor: gain,
        downColor: loss,
        borderUpColor: gain,
        borderDownColor: loss,
        wickUpColor: gain,
        wickDownColor: loss,
      });
      series.setData(ohlc.map(([t, o, h, l, c]) => ({ time: toTime(t), open: o, high: h, low: l, close: c })));

      const inRange = trades.filter((t) => t.exit_time >= first);
      const markers = inRange
        .flatMap((t) => [
          t.side === "short"
            ? { time: toTime(snap(Math.max(t.entry_time, first))), position: "aboveBar" as const, shape: "arrowDown" as const, color: ink, text: "V" }
            : { time: toTime(snap(Math.max(t.entry_time, first))), position: "belowBar" as const, shape: "arrowUp" as const, color: ink, text: "C" },
          {
            time: toTime(snap(t.exit_time)),
            position: t.side === "short" ? ("belowBar" as const) : ("aboveBar" as const),
            shape: t.side === "short" ? ("arrowUp" as const) : ("arrowDown" as const),
            color: t.pnl > 0 ? gain : loss,
            text: `${t.pnl > 0 ? "+" : ""}${money(t.pnl)}`,
          },
        ])
        .sort((a, b) => (a.time as number) - (b.time as number));
      createSeriesMarkers(series, markers);

      // Abre mostrando as últimas operações.
      const lastTrades = inRange.slice(-8);
      if (lastTrades.length) {
        chart.timeScale().setVisibleRange({
          from: toTime(snap(lastTrades[0].entry_time) - step * 20),
          to: toTime(Math.min(last, snap(lastTrades[lastTrades.length - 1].exit_time) + step * 20)),
        });
      } else chart.timeScale().fitContent();

      cleanup = () => chart.remove();
    });

    return () => {
      disposed = true;
      cleanup();
    };
  }, [ohlc, trades, version]);

  return (
    <FullscreenFrame title={title} heading={heading}>
      {() => (
        <figure className="chart" style={{ padding: 0, margin: 0, height: "100%" }}>
          <div ref={box} className="chart-box chart-box-candles" aria-label="Gráfico de candles com as entradas compradas (C), vendidas (V) e as saídas marcadas" role="img" />
        </figure>
      )}
    </FullscreenFrame>
  );
}
