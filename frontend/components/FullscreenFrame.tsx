"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type FsElement = HTMLElement & { webkitRequestFullscreen?: () => Promise<void> | void };
type FsDocument = Document & { webkitFullscreenElement?: Element | null; webkitExitFullscreen?: () => Promise<void> | void };

/**
 * Envolve um gráfico com o botão "Tela cheia".
 * Usa a tela cheia do navegador quando existe; no iPhone (sem esse recurso) ocupa a janela inteira.
 * Esc ou o botão "Sair da tela cheia" voltam ao normal.
 */
export function FullscreenFrame({ title, heading, children }: { title: string; heading?: React.ReactNode; children: (full: boolean) => React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [full, setFull] = useState(false);
  const doc = typeof document !== "undefined" ? (document as FsDocument) : null;

  const native = () => doc?.fullscreenElement ?? doc?.webkitFullscreenElement ?? null;

  const enter = useCallback(async () => {
    setFull(true);
    const el = ref.current as FsElement | null;
    try {
      if (el?.requestFullscreen) await el.requestFullscreen();
      else await el?.webkitRequestFullscreen?.();
    } catch {
      /* sem permissão para tela cheia nativa: segue ocupando a janela */
    }
  }, []);

  const exit = useCallback(async () => {
    setFull(false);
    try {
      if (native()) {
        if (doc?.exitFullscreen) await doc.exitFullscreen();
        else await doc?.webkitExitFullscreen?.();
      }
    } catch {
      /* já saiu */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const onChange = () => {
      if (!native()) setFull(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && full) void exit();
    };
    document.addEventListener("fullscreenchange", onChange);
    document.addEventListener("webkitfullscreenchange", onChange);
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = full ? "hidden" : "";
    return () => {
      document.removeEventListener("fullscreenchange", onChange);
      document.removeEventListener("webkitfullscreenchange", onChange);
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [full]);

  return (
    <div ref={ref} className={`fs-frame${full ? " is-full" : ""}`} role={full ? "dialog" : undefined} aria-label={full ? title : undefined}>
      <div className="fs-bar">
        {full ? <strong className="fs-title">{title}</strong> : <div className="fs-heading">{heading}</div>}
        <button type="button" className="btn fs-toggle" onClick={full ? exit : enter} aria-pressed={full}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {full ? (
              <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" />
            ) : (
              <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
            )}
          </svg>
          {full ? "Sair da tela cheia" : "Tela cheia"}
        </button>
      </div>
      <div className="fs-body">{children(full)}</div>
    </div>
  );
}
