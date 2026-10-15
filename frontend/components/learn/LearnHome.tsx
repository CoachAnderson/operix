"use client";

import Link from "next/link";
import { LESSONS, MODULES, TOTAL_MINUTES } from "@/lib/learn/lessons";
import { useProgress } from "./progress";

export function LearnHome() {
  const { done, isDone } = useProgress();
  const count = LESSONS.filter((l) => isDone(l.slug)).length;
  const nextLesson = LESSONS.find((l) => !isDone(l.slug)) ?? LESSONS[0];
  const pctDone = Math.round((count / LESSONS.length) * 100);

  return (
    <>
      <section className="learn-hero">
        <div>
          <p className="learn-kicker">Aprender</p>
          <h1>Entenda o mercado em aulas de 5 minutos.</h1>
          <p className="learn-lead">
            Do primeiro candle até ler um backtest: {LESSONS.length} aulas curtas, com gráficos que você mexe e um quiz rápido no fim de cada uma. Grátis e sem
            cadastro.
          </p>
          <div className="actions">
            <Link className="btn btn-primary" href={`/aprender/${nextLesson.slug}`}>
              {count === 0 ? "Começar pela primeira aula" : count === LESSONS.length ? "Rever a trilha" : `Continuar: ${nextLesson.title}`}
            </Link>
            <Link className="btn btn-quiet" href="/aprender/glossario">
              Glossário
            </Link>
          </div>
        </div>
        <div className="learn-progress" aria-label={`Progresso: ${count} de ${LESSONS.length} aulas`}>
          <div className="learn-ring" style={{ "--p": `${pctDone}%` } as React.CSSProperties}>
            <span>{pctDone}%</span>
          </div>
          <div>
            <strong>
              {count} de {LESSONS.length} aulas
            </strong>
            <p className="muted small">Cerca de {TOTAL_MINUTES} minutos no total. O progresso fica salvo neste navegador.</p>
          </div>
        </div>
      </section>

      <ol className="learn-modules">
        {MODULES.map((m, mi) => {
          const mDone = m.lessons.filter((l) => done.includes(l.slug)).length;
          return (
            <li key={m.id} className="learn-module">
              <header>
                <span className="learn-module-no">Módulo {mi + 1}</span>
                <h2>{m.title}</h2>
                <p className="muted">{m.description}</p>
                <p className="small muted">
                  {mDone} de {m.lessons.length} concluídas · {m.lessons.reduce((a, l) => a + l.minutes, 0)} min
                </p>
              </header>
              <ol className="learn-lessons">
                {m.lessons.map((l) => (
                  <li key={l.slug}>
                    <Link href={`/aprender/${l.slug}`} className={isDone(l.slug) ? "is-done" : ""}>
                      <span className="learn-check" aria-hidden="true">
                        {isDone(l.slug) ? "✓" : ""}
                      </span>
                      <span className="learn-lesson-text">
                        <strong>{l.title}</strong>
                        <span className="muted small">{l.summary}</span>
                      </span>
                      <span className="learn-min">{l.minutes} min</span>
                      {isDone(l.slug) && <span className="sr-only">(concluída)</span>}
                    </Link>
                  </li>
                ))}
              </ol>
            </li>
          );
        })}
      </ol>
    </>
  );
}
