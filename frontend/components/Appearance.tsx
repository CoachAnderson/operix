"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  APPEARANCE_EVENT,
  DEFAULT_APPEARANCE,
  applyAppearance,
  loadLocal,
  normalize,
  saveLocal,
  type Appearance,
  type ThemeMode,
} from "@/lib/appearance";

/** Muda de valor sempre que o tema efetivo pode ter mudado (escolha do usuário ou tema do aparelho). */
export function useAppearanceVersion(): number {
  const [v, setV] = useState(0);
  useEffect(() => {
    const bump = () => setV((x) => x + 1);
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    window.addEventListener(APPEARANCE_EVENT, bump);
    mq.addEventListener("change", bump);
    return () => {
      window.removeEventListener(APPEARANCE_EVENT, bump);
      mq.removeEventListener("change", bump);
    };
  }, []);
  return v;
}

let timer: ReturnType<typeof setTimeout> | null = null;
let onSaved: ((ok: boolean) => void) | null = null;

/** Aplica já, guarda no navegador e, logado, salva na conta (agrupando mudanças seguidas). */
export function persistAppearance(a: Appearance, opts: { account?: boolean; onDone?: (ok: boolean) => void } = {}): void {
  saveLocal(a); // antes de aplicar: quem ouve o evento lê a escolha nova
  applyAppearance(a);
  if (!opts.account) return;
  onSaved = opts.onDone ?? null;
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => {
    api("/me/appearance", { method: "PUT", json: a })
      .then(() => onSaved?.(true))
      .catch(() => onSaved?.(false));
  }, 700);
}

/** Ao entrar no painel: a escolha salva na conta vale em todos os aparelhos. */
export function syncFromAccount(server: unknown): void {
  if (!server) return; // conta sem escolha: mantém a do navegador
  const a = normalize(server);
  const local = loadLocal();
  if (JSON.stringify(local) === JSON.stringify(a)) return;
  saveLocal(a);
  applyAppearance(a);
}

const NEXT: Record<ThemeMode, ThemeMode> = { auto: "light", light: "dark", dark: "auto" };
const LABEL: Record<ThemeMode, string> = { auto: "Tema: automático", light: "Tema: claro", dark: "Tema: escuro" };

function Icon({ mode }: { mode: ThemeMode }) {
  if (mode === "light")
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </svg>
    );
  if (mode === "dark")
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden="true">
        <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
      </svg>
    );
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <circle cx="12" cy="12" r="8" />
      <path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor" />
    </svg>
  );
}

/** Botão rápido: automático → claro → escuro. */
export function ThemeToggle({ account = false, compact = false }: { account?: boolean; compact?: boolean }) {
  const [mode, setMode] = useState<ThemeMode | null>(null);
  const version = useAppearanceVersion(); // acompanha mudanças feitas na tela Aparência
  useEffect(() => setMode((loadLocal() ?? DEFAULT_APPEARANCE).theme), [version]);
  if (!mode) return <span className="theme-toggle" aria-hidden="true" style={{ visibility: "hidden" }}>Tema</span>;
  function cycle() {
    const a = { ...(loadLocal() ?? DEFAULT_APPEARANCE), theme: NEXT[mode!] };
    setMode(a.theme);
    persistAppearance(a, { account });
  }
  return (
    <button type="button" className="theme-toggle" onClick={cycle} title={`${LABEL[mode]} (clique para trocar)`} aria-label={`${LABEL[mode]}. Trocar tema`}>
      <Icon mode={mode} />
      {!compact && LABEL[mode]}
    </button>
  );
}
