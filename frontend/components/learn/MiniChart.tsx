"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Candle, Series } from "@/lib/learn/market";
import { num } from "@/lib/learn/market";

export interface ChartLine {
  values: Series;
  color: string; // valor CSS, ex.: "var(--learn-a)"
  label: string;
  width?: number;
  dash?: string;
}

export interface ChartProps {
  candles: Candle[];
  label: string; // descrição para leitores de tela
  height?: number;
  mode?: "candles" | "line";
  lines?: ChartLine[];
  band?: { upper: Series; lower: Series; color: string; label: string };
  levels?: { price: number; label: string; color: string }[];
  markers?: { i: number; kind: "buy" | "sell" }[];
  spans?: { from: number; to: number; tone: "gain" | "loss" }[];
  points?: { i: number; price: number; label: string; up: boolean }[];
  sub?: {
    values: Series;
    label: string;
    min: number;
    max: number;
    height?: number;
    levels: { v: number; color?: string }[];
  };
  readout?: boolean; // mostra abertura/máxima/mínima/fechamento ao passar o mouse
}

/** Largura real do elemento, para desenhar nítido em qualquer tela. */
function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0); // 0 = ainda no servidor: o gráfico só é desenhado no navegador
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(Math.max(260, Math.round(el.getBoundingClientRect().width)));
    const ro = new ResizeObserver(([e]) => setW(Math.max(260, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

function path(values: Series, x: (i: number) => number, y: (v: number) => number): string {
  let d = "";
  let pen = false;
  values.forEach((v, i) => {
    if (v === null || Number.isNaN(v)) {
      pen = false;
      return;
    }
    d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
    pen = true;
  });
  return d;
}

export function MiniChart({
  candles,
  label,
  height = 260,
  mode = "candles",
  lines = [],
  band,
  levels = [],
  markers = [],
  spans = [],
  points = [],
  sub,
  readout = false,
}: ChartProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const axis = 52;
  const pad = 10;
  const plotW = width - axis - pad;
  const subH = sub ? (sub.height ?? 96) : 0;
  const gap = sub ? 18 : 0;
  const total = height + gap + subH;

  const { lo, hi } = useMemo(() => {
    let lo = Infinity;
    let hi = -Infinity;
    for (const c of candles) {
      lo = Math.min(lo, mode === "line" ? c.c : c.l);
      hi = Math.max(hi, mode === "line" ? c.c : c.h);
    }
    for (const l of lines) for (const v of l.values) if (v !== null) (lo = Math.min(lo, v)), (hi = Math.max(hi, v));
    if (band) for (const s of [band.upper, band.lower]) for (const v of s) if (v !== null) (lo = Math.min(lo, v)), (hi = Math.max(hi, v));
    for (const l of levels) (lo = Math.min(lo, l.price)), (hi = Math.max(hi, l.price));
    const m = (hi - lo) * 0.08 || 1;
    return { lo: lo - m, hi: hi + m };
  }, [candles, lines, band, levels, mode]);

  const n = candles.length;
  const step = plotW / n;
  const x = (i: number) => pad + step * (i + 0.5);
  const y = (v: number) => pad + (1 - (v - lo) / (hi - lo)) * (height - 2 * pad);
  const subTop = height + gap;
  const ys = (v: number) => (sub ? subTop + (1 - (v - sub.min) / (sub.max - sub.min)) * subH : 0);
  const body = Math.max(1, Math.min(14, step * 0.62));

  const ticks = useMemo(() => {
    const raw = (hi - lo) / 4;
    const mag = 10 ** Math.floor(Math.log10(raw));
    const st = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((k) => k >= raw) ?? raw;
    const out: number[] = [];
    for (let v = Math.ceil(lo / st) * st; v <= hi; v += st) out.push(v);
    return { values: out, digits: st >= 1 ? 0 : st >= 0.1 ? 1 : 2 };
  }, [lo, hi]);
  const digits = ticks.digits;

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    const i = Math.floor((e.clientX - r.left - pad) / step);
    setHover(i >= 0 && i < n ? i : null);
  }

  const h = hover !== null ? candles[hover] : null;

  if (!width)
    return (
      <div className="mc" ref={ref}>
        <div style={{ height: total + (readout || sub ? 24 : 0) }} aria-hidden="true" />
      </div>
    );

  return (
    <div className="mc" ref={ref}>
      {(readout || sub) && (
        <div className="mc-readout" aria-live="polite">
          {h ? (
            <>
              {readout && (
                <>
                  <span>Abertura {num(h.o)}</span>
                  <span>Máxima {num(h.h)}</span>
                  <span>Mínima {num(h.l)}</span>
                  <span>Fechamento {num(h.c)}</span>
                </>
              )}
              {sub && hover !== null && sub.values[hover] !== null && (
                <span>
                  {sub.label} {num(sub.values[hover] as number, 0)}
                </span>
              )}
            </>
          ) : (
            <span className="muted">Passe o dedo ou o mouse sobre o gráfico para ver os valores.</span>
          )}
        </div>
      )}
      <svg
        width={width}
        height={total}
        viewBox={`0 0 ${width} ${total}`}
        role="img"
        aria-label={label}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        {/* grade e eixo */}
        {ticks.values.map((t) => (
          <g key={t}>
            <line x1={pad} x2={pad + plotW} y1={y(t)} y2={y(t)} className="mc-grid" />
            <text x={pad + plotW + 6} y={y(t) + 4} className="mc-axis">
              {num(t, digits)}
            </text>
          </g>
        ))}

        {/* operações sombreadas */}
        {spans.map((s, k) => (
          <rect
            key={k}
            x={x(s.from) - step / 2}
            y={pad}
            width={Math.max(step, x(s.to) - x(s.from) + step)}
            height={height - 2 * pad}
            className={s.tone === "gain" ? "mc-span-gain" : "mc-span-loss"}
          />
        ))}

        {/* canal */}
        {band && (
          <>
            <path
              d={(() => {
                const up = band.upper.map((v, i) => (v === null ? null : [x(i), y(v)])).filter(Boolean) as number[][];
                const dn = band.lower.map((v, i) => (v === null ? null : [x(i), y(v)])).filter(Boolean) as number[][];
                if (!up.length) return "";
                return `M${up.map((p) => p.join(",")).join("L")}L${dn.reverse().map((p) => p.join(",")).join("L")}Z`;
              })()}
              style={{ fill: band.color, opacity: 0.1 }}
            />
            <path d={path(band.upper, x, y)} style={{ stroke: band.color }} className="mc-line mc-thin" />
            <path d={path(band.lower, x, y)} style={{ stroke: band.color }} className="mc-line mc-thin" />
          </>
        )}

        {/* níveis horizontais */}
        {levels.map((l) => (
          <g key={l.label}>
            <line x1={pad} x2={pad + plotW} y1={y(l.price)} y2={y(l.price)} style={{ stroke: l.color }} className="mc-level" />
            <text x={pad + 4} y={y(l.price) - 5} style={{ fill: l.color }} className="mc-tag">
              {l.label}
            </text>
          </g>
        ))}

        {/* preço */}
        {mode === "line" ? (
          <path d={path(candles.map((c) => c.c), x, y)} className="mc-line mc-price" />
        ) : (
          candles.map((c, i) => {
            const up = c.c >= c.o;
            return (
              <g key={i} className={up ? "mc-up" : "mc-down"} opacity={hover !== null && hover !== i ? 0.55 : 1}>
                <line x1={x(i)} x2={x(i)} y1={y(c.h)} y2={y(c.l)} className="mc-wick" />
                <rect x={x(i) - body / 2} y={y(Math.max(c.o, c.c))} width={body} height={Math.max(1, Math.abs(y(c.o) - y(c.c)))} className="mc-body" />
              </g>
            );
          })
        )}

        {/* indicadores */}
        {lines.map((l) => (
          <path key={l.label} d={path(l.values, x, y)} style={{ stroke: l.color, strokeWidth: l.width ?? 2, strokeDasharray: l.dash }} className="mc-line" />
        ))}

        {/* topos e fundos */}
        {points.map((p, k) => (
          <g key={k}>
            <circle cx={x(p.i)} cy={y(p.price)} r={4.5} className={p.up ? "mc-pt-top" : "mc-pt-bottom"} />
            <text x={x(p.i)} y={y(p.price) + (p.up ? -9 : 17)} textAnchor="middle" className="mc-tag mc-pt-label">
              {p.label}
            </text>
          </g>
        ))}

        {/* compras e vendas */}
        {markers.map((m, k) => {
          const c = candles[m.i];
          const buy = m.kind === "buy";
          const yy = buy ? y(c.l) + 8 : y(c.h) - 8;
          const s = 6;
          return (
            <path
              key={k}
              d={buy ? `M${x(m.i)},${yy} l${-s},${s * 1.6} h${2 * s}z` : `M${x(m.i)},${yy} l${-s},${-s * 1.6} h${2 * s}z`}
              className={buy ? "mc-buy" : "mc-sell"}
            >
              <title>{buy ? "Compra" : "Venda"}</title>
            </path>
          );
        })}

        {/* painel de baixo (RSI) */}
        {sub && (
          <g>
            <rect x={pad} y={subTop} width={plotW} height={subH} className="mc-subbg" />
            {sub.levels.map((l) => (
              <g key={l.v}>
                <line x1={pad} x2={pad + plotW} y1={ys(l.v)} y2={ys(l.v)} style={{ stroke: l.color ?? "var(--muted)" }} className="mc-level" />
                <text x={pad + plotW + 6} y={ys(l.v) + 4} className="mc-axis">
                  {l.v}
                </text>
              </g>
            ))}
            <path d={path(sub.values, x, ys)} className="mc-line mc-sub" />
            <text x={pad + 4} y={subTop + 13} className="mc-tag">
              {sub.label}
            </text>
          </g>
        )}

        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={pad} y2={total} className="mc-cross" />}
      </svg>
      {(lines.length > 0 || band) && (
        <div className="mc-legend">
          {band && (
            <span>
              <i style={{ background: band.color }} /> {band.label}
            </span>
          )}
          {lines.map((l) => (
            <span key={l.label}>
              <i style={{ background: l.color }} /> {l.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
