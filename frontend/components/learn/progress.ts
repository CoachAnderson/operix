"use client";

import { useCallback, useEffect, useState } from "react";

const KEY = "oi-aprender-v1";

function read(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

/** Aulas concluídas, guardadas neste navegador. */
export function useProgress() {
  const [done, setDone] = useState<string[]>([]);
  useEffect(() => {
    setDone(read());
    const onStorage = (e: StorageEvent) => {
      if (e.key === KEY) setDone(read());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const mark = useCallback((slug: string, value = true) => {
    setDone((cur) => {
      const next = value ? Array.from(new Set([...cur, slug])) : cur.filter((s) => s !== slug);
      try {
        localStorage.setItem(KEY, JSON.stringify(next));
      } catch {
        /* navegador sem armazenamento: o progresso vale só nesta visita */
      }
      return next;
    });
  }, []);

  return { done, isDone: (slug: string) => done.includes(slug), mark };
}
