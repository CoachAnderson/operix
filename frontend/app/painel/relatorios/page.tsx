"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ErrorText, Loading, PageHead, useAction, useApi } from "@/components/ui";
import { download } from "@/lib/api";
import type { ReportSymbol, Venue } from "@/lib/types";

type Preset = "month" | "30" | "90" | "year" | "custom";

const PRESETS: { id: Preset; label: string }[] = [
  { id: "month", label: "Este mês" },
  { id: "30", label: "Últimos 30 dias" },
  { id: "90", label: "Últimos 90 dias" },
  { id: "year", label: "Este ano" },
  { id: "custom", label: "Outro período" },
];

const VENUES: { id: Venue; label: string }[] = [
  { id: "live", label: "Conta real" },
  { id: "testnet", label: "Testnet / conta demo" },
  { id: "paper", label: "Simulação" },
];

/** Data local (fuso do navegador) no formato AAAA-MM-DD. */
function iso(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function rangeFor(preset: Preset): [string, string] | null {
  const today = new Date();
  switch (preset) {
    case "month":
      return [iso(new Date(today.getFullYear(), today.getMonth(), 1)), iso(today)];
    case "30":
    case "90": {
      const start = new Date(today);
      start.setDate(start.getDate() - Number(preset) + 1);
      return [iso(start), iso(today)];
    }
    case "year":
      return [iso(new Date(today.getFullYear(), 0, 1)), iso(today)];
    default:
      return null;
  }
}

const SIDE: Record<string, string> = { long: "comprado", short: "vendido" };

export default function ReportsPage() {
  const { data: symbols, error: loadError } = useApi<ReportSymbol[]>("/reports/symbols");
  const { busy, error, run, setError } = useAction();

  const [preset, setPreset] = useState<Preset>("month");
  const [[start, end], setRange] = useState<[string, string]>(() => rangeFor("month")!);
  const [venues, setVenues] = useState<Set<Venue>>(new Set(["live", "testnet", "paper"]));
  const [chosen, setChosen] = useState<Set<string>>(new Set());

  const openOnes = useMemo(() => symbols?.filter((s) => s.open).map((s) => s.symbol) ?? [], [symbols]);

  // Ao carregar: as moedas com posição aberta já vêm marcadas. Sem nenhuma aberta, marca todas.
  useEffect(() => {
    if (!symbols) return;
    setChosen(new Set(openOnes.length ? openOnes : symbols.map((s) => s.symbol)));
  }, [symbols, openOnes]);

  function pickPreset(p: Preset) {
    setPreset(p);
    const r = rangeFor(p);
    if (r) setRange(r);
  }

  function toggle<T>(set: Set<T>, value: T): Set<T> {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    return next;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!chosen.size) return setError("Marque pelo menos uma moeda");
    if (!venues.size) return setError("Marque pelo menos um ambiente");
    if (!start || !end || end < start) return setError("Confira as datas do período");
    const q = new URLSearchParams({ start, end });
    [...chosen].sort().forEach((s) => q.append("symbol", s));
    [...venues].forEach((v) => q.append("venue", v));
    await run(() => download(`/reports/pdf?${q}`, `relatorio-${start}-a-${end}.pdf`));
  }

  return (
    <>
      <PageHead title="Relatórios" lead="Baixe em PDF as operações dos seus robôs: resumo por moeda, posições abertas e todas as ordens do período." />
      {loadError && <p className="loss">{loadError}</p>}
      {!symbols && !loadError && <Loading />}
      {symbols && !symbols.length && (
        <div className="panel empty">
          Você ainda não tem robôs. <Link href="/painel/robos/novo">Crie um robô</Link> para gerar relatórios.
        </div>
      )}

      {symbols && symbols.length > 0 && (
        <form className="report-form" onSubmit={submit}>
          <fieldset>
            <legend>Moedas</legend>
            <div className="coin-tools">
              <p className="muted small">
                {openOnes.length
                  ? `As moedas com posição aberta já vêm marcadas (${openOnes.length}).`
                  : "Nenhuma posição aberta agora, então todas vêm marcadas."}
              </p>
              <div className="actions">
                <button type="button" className="btn btn-quiet" disabled={!openOnes.length} onClick={() => setChosen(new Set(openOnes))}>
                  Só as abertas
                </button>
                <button type="button" className="btn btn-quiet" onClick={() => setChosen(new Set(symbols.map((s) => s.symbol)))}>
                  Todas
                </button>
                <button type="button" className="btn btn-quiet" onClick={() => setChosen(new Set())}>
                  Nenhuma
                </button>
              </div>
            </div>
            <div className="coin-list">
              {symbols.map((s) => (
                <label key={s.symbol} className="coin">
                  <input type="checkbox" checked={chosen.has(s.symbol)} onChange={() => setChosen((c) => toggle(c, s.symbol))} />
                  <span className="coin-name">{s.symbol}</span>
                  <span className="coin-meta">
                    {s.market === "forex" ? "Forex" : "Cripto"} · {s.bots} robô{s.bots > 1 ? "s" : ""}
                  </span>
                  {s.open && <span className="tag-open">Aberta · {s.open_sides.map((x) => SIDE[x]).join(" e ")}</span>}
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset>
            <legend>Período</legend>
            <div className="choice">
              {PRESETS.map((p) => (
                <label key={p.id}>
                  <input type="radio" name="preset" checked={preset === p.id} onChange={() => pickPreset(p.id)} />
                  {p.label}
                </label>
              ))}
            </div>
            <div className="grid-2">
              <label>
                De
                <input type="date" value={start} max={end} required onChange={(e) => {
                    setPreset("custom");
                    setRange([e.target.value, end]);
                  }} />
              </label>
              <label>
                Até
                <input type="date" value={end} min={start} required onChange={(e) => {
                    setPreset("custom");
                    setRange([start, e.target.value]);
                  }} />
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend>Ambientes</legend>
            <div className="venue-checks">
              {VENUES.map((v) => (
                <label key={v.id} className="check">
                  <input type="checkbox" checked={venues.has(v.id)} onChange={() => setVenues((c) => toggle(c, v.id))} />
                  {v.label}
                </label>
              ))}
            </div>
            <p className="muted small">Cada ambiente sai separado no relatório: simulação nunca soma com conta real.</p>
          </fieldset>

          <div className="actions">
            <button className="btn btn-primary" disabled={busy || !chosen.size || !venues.size}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M12 4v11M7 10l5 5 5-5M5 20h14" />
              </svg>
              {busy ? "Gerando PDF…" : `Baixar PDF (${chosen.size} moeda${chosen.size === 1 ? "" : "s"})`}
            </button>
          </div>
          <ErrorText>{error}</ErrorText>
        </form>
      )}
    </>
  );
}
