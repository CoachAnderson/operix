"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

interface Check {
  level: "ok" | "warn" | "fail" | "info";
  title: string;
  detail: string;
}
interface Entry {
  at: number;
  kind: "decision" | "risk";
  action: string;
  detail: string;
}
interface Diagnostics {
  checks: Check[];
  journal: Entry[];
  counts: Record<string, number>;
  timeframe: string;
  strategy: string;
  next_decision_at: number;
}

const ACTION: Record<string, { label: string; tone: string }> = {
  executed: { label: "Executou", tone: "gain" },
  signal: { label: "Sinal criado", tone: "gain" },
  hold: { label: "Sem entrada", tone: "muted" },
  blocked: { label: "Bloqueado", tone: "loss" },
  skipped: { label: "Pulado", tone: "warn-text" },
  error: { label: "Erro", tone: "loss" },
};
const COUNT_LABEL: Record<string, string> = {
  executed: "execuções",
  signal: "sinais",
  hold: "sem entrada",
  blocked: "bloqueadas",
  skipped: "puladas",
  error: "erros",
};
const ICON: Record<Check["level"], { mark: string; tone: string; label: string }> = {
  ok: { mark: "✓", tone: "gain", label: "ok" },
  info: { mark: "i", tone: "muted", label: "informação" },
  warn: { mark: "!", tone: "warn-text", label: "atenção" },
  fail: { mark: "✕", tone: "loss", label: "problema" },
};
const ORDER: Record<Check["level"], number> = { fail: 0, warn: 1, info: 2, ok: 3 };

function detailText(e: Entry): string {
  if (e.detail) return e.detail;
  if (e.action === "hold") return e.kind === "decision" ? "A estratégia não deu sinal neste candle." : "Posição conferida, sem saída.";
  return "";
}

/** "Por que o robô entrou ou não entrou?": conferência das causas comuns + diário das últimas decisões. */
export function BotDiagnostics({ botId }: { botId: string }) {
  const [data, setData] = useState<Diagnostics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      setData(await api<Diagnostics>(`/bots/${botId}/diagnostics`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Não foi possível fazer o diagnóstico");
    } finally {
      setBusy(false);
    }
  }, [botId]);

  useEffect(() => {
    void load();
    const t = setInterval(() => {
      if (!document.hidden) void load();
    }, 30_000);
    return () => clearInterval(t);
  }, [load]);

  const checks = data ? [...data.checks].sort((a, b) => ORDER[a.level] - ORDER[b.level]) : [];
  const problems = checks.filter((c) => c.level === "fail").length;
  const warnings = checks.filter((c) => c.level === "warn").length;

  return (
    <div style={{ display: "grid", gap: 14, gridTemplateColumns: "minmax(0, 1fr)", minWidth: 0 }}>
      <div className="page-head" style={{ marginBottom: 0, alignItems: "center" }}>
        <h2>Por que entrou ou não entrou?</h2>
        <button type="button" className="btn" onClick={() => load()} disabled={busy}>
          {busy ? "Verificando…" : "Verificar agora"}
        </button>
      </div>
      {error && <p className="loss">{error}</p>}
      {data && (
        <>
          <p className={problems ? "loss" : warnings ? "warn-text" : "gain"} role="status">
            {problems
              ? `${problems} problema${problems > 1 ? "s" : ""} impedindo as entradas. Veja abaixo como resolver.`
              : warnings
                ? "Nada bloqueando, mas há pontos de atenção."
                : "Tudo certo: o robô entra quando a estratégia der sinal."}{" "}
            <span className="muted small">
              Próxima avaliação por volta de {new Date(data.next_decision_at).toLocaleTimeString("pt-BR")} ({data.strategy}, {data.timeframe}).
            </span>
          </p>
          <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 8 }}>
            {checks.map((c) => (
              <li key={c.title} style={{ display: "grid", gridTemplateColumns: "24px minmax(0, 1fr)", gap: 10, alignItems: "start" }}>
                <span
                  className={ICON[c.level].tone}
                  aria-label={ICON[c.level].label}
                  style={{ fontWeight: 700, width: 22, height: 22, borderRadius: "50%", border: "1.5px solid currentColor", display: "grid", placeItems: "center", fontSize: 12 }}
                >
                  {ICON[c.level].mark}
                </span>
                <span>
                  <strong>{c.title}</strong>
                  {c.detail && <span className="muted small" style={{ display: "block" }}>{c.detail}</span>}
                </span>
              </li>
            ))}
          </ul>

          <details open={data.journal.length > 0 && problems === 0} style={{ minWidth: 0 }}>
            <summary>
              Últimas decisões do robô ({data.journal.length})
              {Object.keys(data.counts).length > 0 &&
                ": " +
                  Object.entries(data.counts)
                    .map(([k, v]) => `${v} ${COUNT_LABEL[k] ?? k}`)
                    .join(", ")}
            </summary>
            {data.journal.length === 0 ? (
              <p className="muted small" style={{ marginTop: 8 }}>
                Nenhuma decisão registrada ainda. O motor registra uma a cada candle fechado; se continuar vazio, o motor não está avaliando este robô.
              </p>
            ) : (
              <div className="table-wrap" style={{ marginTop: 8, maxHeight: 360, overflowY: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Quando</th>
                      <th>Tipo</th>
                      <th>Resultado</th>
                      <th>Motivo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.journal.map((e, i) => (
                      <tr key={`${e.at}-${i}`}>
                        <td style={{ whiteSpace: "nowrap" }}>
                          {new Date(e.at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                        </td>
                        <td>{e.kind === "decision" ? "Candle" : "Risco"}</td>
                        <td className={ACTION[e.action]?.tone ?? ""}>{ACTION[e.action]?.label ?? e.action}</td>
                        <td className="small">{detailText(e)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </details>
        </>
      )}
    </div>
  );
}
