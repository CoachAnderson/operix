"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { GLOSSARY } from "@/lib/learn/lessons";

const norm = (s: string) =>
  s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();

export default function GlossaryPage() {
  const [q, setQ] = useState("");
  const items = useMemo(() => {
    const t = norm(q.trim());
    return t ? GLOSSARY.filter((g) => norm(g.term).includes(t) || norm(g.def).includes(t)) : GLOSSARY;
  }, [q]);
  return (
    <div className="glossary">
      <nav className="lesson-crumbs" aria-label="Você está em">
        <Link href="/aprender">Aprender</Link> <span aria-hidden="true">›</span> Glossário
      </nav>
      <h1>Glossário</h1>
      <p className="lesson-summary">Os termos do mercado em uma frase cada.</p>
      <label className="glossary-search">
        <span className="sr-only">Buscar termo</span>
        <input type="search" placeholder="Buscar: stop, RSI, spread…" value={q} onChange={(e) => setQ(e.target.value)} />
      </label>
      {items.length ? (
        <dl className="glossary-list">
          {items.map((g) => (
            <div key={g.term}>
              <dt>{g.term}</dt>
              <dd>
                {g.def}{" "}
                {g.lesson && (
                  <Link href={`/aprender/${g.lesson}`} className="glossary-link">
                    Ver na aula
                  </Link>
                )}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="muted">Nenhum termo encontrado.</p>
      )}
    </div>
  );
}
