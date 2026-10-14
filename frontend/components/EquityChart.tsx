"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { money } from "@/lib/format";

type Point = [number, number, number]; // tempo, estratégia, comprar e segurar

const H = 280;
const PAD = { top: 16, right: 92, bottom: 28, left: 64 };

function niceTicks(min: number, max: number, count = 4): number[] {
  const span = max - min || Math.abs(max) || 1;
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const start = Math.ceil(min / step) * step;
  const out: number[] = [];
  for (let v = start; v <= max + 1e-9; v += step) out.push(Number(v.toFixed(10)));
  return out;
}

const shortDate = (ms: number) => new Date(ms).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "2-digit" });

export function EquityChart({ points, initial }: { points: Point[]; initial: number }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(320, Math.round(e.contentRect.width))));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  const geo = useMemo(() => {
    const t0 = points[0][0];
    const t1 = points[points.length - 1][0];
    const values = points.flatMap((p) => [p[1], p[2]]).concat(initial);
    let lo = Math.min(...values);
    let hi = Math.max(...values);
    const pad = (hi - lo) * 0.08 || hi * 0.02 || 1;
    lo -= pad;
    hi += pad;
    const w = width - PAD.left - PAD.right;
    const h = H - PAD.top - PAD.bottom;
    const x = (t: number) => PAD.left + ((t - t0) / (t1 - t0 || 1)) * w;
    const y = (v: number) => PAD.top + (1 - (v - lo) / (hi - lo)) * h;
    const path = (i: 1 | 2) => points.map((p, k) => `${k ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[i]).toFixed(1)}`).join("");
    const n = width < 520 ? 3 : 5;
    const xticks: number[] = Array.from({ length: n }, (_, k) => t0 + ((t1 - t0) * k) / (n - 1));
    return { x, y, yticks: niceTicks(lo, hi), xticks, strat: path(1), bench: path(2), w, h };
  }, [points, width, initial]);

  function onMove(e: React.PointerEvent<SVGRectElement>) {
    const rect = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const px = e.clientX - rect.left;
    let best = 0;
    let dist = Infinity;
    points.forEach((p, k) => {
      const d = Math.abs(geo.x(p[0]) - px);
      if (d < dist) {
        dist = d;
        best = k;
      }
    });
    setHover(best);
  }

  const last = points[points.length - 1];
  const hp = hover !== null ? points[hover] : null;
  // Evita que os rótulos de fim de linha se sobreponham.
  let ys = geo.y(last[1]);
  let yb = geo.y(last[2]);
  if (Math.abs(ys - yb) < 16) {
    const mid = (ys + yb) / 2;
    [ys, yb] = ys <= yb ? [mid - 8, mid + 8] : [mid + 8, mid - 8];
  }

  return (
    <figure className="chart" ref={wrap}>
      <div className="chart-legend">
        <span><i className="swatch swatch-strategy" />Robô</span>
        <span><i className="swatch swatch-bench" />Comprar e segurar o mesmo valor</span>
      </div>
      <svg
        width={width}
        height={H}
        role="img"
        aria-label={`Evolução do saldo de ${money(initial)} para ${money(last[1])}; comprar e segurar terminaria em ${money(last[2])}.`}
      >
        {geo.yticks.map((v) => (
          <g key={v}>
            <line className="grid" x1={PAD.left} x2={PAD.left + geo.w} y1={geo.y(v)} y2={geo.y(v)} />
            <text className="tick" x={PAD.left - 8} y={geo.y(v)} textAnchor="end" dominantBaseline="middle">
              {money(v, 0)}
            </text>
          </g>
        ))}
        <line className="baseline" x1={PAD.left} x2={PAD.left + geo.w} y1={geo.y(initial)} y2={geo.y(initial)} />
        {geo.xticks.map((t, k) => (
          <text key={k} className="tick" x={geo.x(t)} y={H - 8} textAnchor={k === 0 ? "start" : k === geo.xticks.length - 1 ? "end" : "middle"}>
            {shortDate(t)}
          </text>
        ))}
        <path className="line-bench" d={geo.bench} />
        <path className="line-strategy" d={geo.strat} />
        <text className="end-label" x={PAD.left + geo.w + 8} y={ys} dominantBaseline="middle">Robô</text>
        <text className="end-label" x={PAD.left + geo.w + 8} y={yb} dominantBaseline="middle">Segurar</text>

        {hp && (
          <g pointerEvents="none">
            <line className="crosshair" x1={geo.x(hp[0])} x2={geo.x(hp[0])} y1={PAD.top} y2={PAD.top + geo.h} />
            <circle className="dot-bench" cx={geo.x(hp[0])} cy={geo.y(hp[2])} r={4.5} />
            <circle className="dot-strategy" cx={geo.x(hp[0])} cy={geo.y(hp[1])} r={4.5} />
          </g>
        )}
        <rect
          x={PAD.left}
          y={PAD.top}
          width={geo.w}
          height={geo.h}
          fill="transparent"
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        />
      </svg>
      {hp && (
        <div
          className="chart-tip"
          style={{ left: Math.min(Math.max(geo.x(hp[0]) + 12, 0), width - 200), top: 44 }}
          role="status"
        >
          <div className="muted small">{new Date(hp[0]).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })}</div>
          <div><i className="swatch swatch-strategy" />Robô <strong>{money(hp[1])}</strong></div>
          <div><i className="swatch swatch-bench" />Segurar <strong>{money(hp[2])}</strong></div>
        </div>
      )}
    </figure>
  );
}
