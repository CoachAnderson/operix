"use client";

import { useEffect, useRef, useState } from "react";
import { FullscreenFrame } from "./FullscreenFrame";

/** Mapa do tempo gráfico do robô para o formato do TradingView. */
const TV_INTERVAL: Record<string, string> = { "1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D" };

const STUDIES: Record<string, string[]> = {
  rsi_reversion: ["STD;RSI"],
};

/**
 * Gráfico avançado do TradingView (widget gratuito, dados do próprio TradingView: BINANCE:<par> ou FX:<par>).
 * Mostra o mercado com todas as ferramentas do TradingView; as ordens do robô ficam na tabela abaixo.
 */
export function TradingViewWidget({ symbol, market = "crypto", timeframe = "1h", strategy, heading }: { symbol: string; market?: "crypto" | "forex" | "b3"; timeframe?: string; strategy?: string; heading?: React.ReactNode }) {
  // Forex: cotação agregada do TradingView (FX:). As cotações da sua corretora podem diferir alguns pontos.
  // B3: série contínua do vencimento atual (WIN1!, WDO1!). O widget gratuito mostra a B3 com atraso.
  const tvSymbol = market === "forex" ? `FX:${symbol}` : market === "b3" ? `BMFBOVESPA:${symbol}1!` : `BINANCE:${symbol}`;
  const box = useRef<HTMLDivElement>(null);
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    setDark(mq.matches);
    const on = (e: MediaQueryListEvent) => setDark(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.innerHTML = '<div class="tradingview-widget-container__widget" style="height:100%;width:100%"></div>';
    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.type = "text/javascript";
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: tvSymbol,
      interval: TV_INTERVAL[timeframe] ?? "60",
      timezone: "America/Sao_Paulo",
      theme: dark ? "dark" : "light",
      style: "1",
      locale: "br",
      allow_symbol_change: true,
      hide_side_toolbar: false,
      calendar: false,
      studies: STUDIES[strategy ?? ""] ?? [],
      support_host: "https://www.tradingview.com",
    });
    el.appendChild(script);
    return () => {
      el.innerHTML = "";
    };
  }, [tvSymbol, timeframe, strategy, dark]);

  return (
    <div className="tv-wrap">
      <FullscreenFrame title={`${symbol} no TradingView`} heading={heading}>
        {() => <div className="tradingview-widget-container chart-box chart-box-tv" ref={box} />}
      </FullscreenFrame>
      <p className="muted small tv-credit">
        Gráfico por{" "}
        <a href={`https://br.tradingview.com/symbols/${tvSymbol.replace(":", "-")}/`} rel="noopener nofollow" target="_blank">
          TradingView
        </a>
        . As cotações podem diferir um pouco das usadas pelo robô.
      </p>
    </div>
  );
}
