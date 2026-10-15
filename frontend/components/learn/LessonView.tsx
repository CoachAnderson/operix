"use client";

import Link from "next/link";
import { LESSONS, MODULES, findLesson, type Block } from "@/lib/learn/lessons";
import { useProgress } from "./progress";
import { Quiz } from "./Quiz";
import { Rich } from "./rich";
import { VISUALS } from "./visuals";

function BlockView({ b }: { b: Block }) {
  if ("p" in b)
    return (
      <p>
        <Rich text={b.p} />
      </p>
    );
  if ("h" in b) return <h2>{b.h}</h2>;
  if ("tip" in b)
    return (
      <aside className="lesson-tip">
        <strong>Na prática</strong>
        <Rich text={b.tip} />
      </aside>
    );
  if ("warn" in b)
    return (
      <aside className="lesson-warn">
        <strong>Atenção</strong>
        <Rich text={b.warn} />
      </aside>
    );
  if ("list" in b)
    return (
      <ul>
        {b.list.map((t, i) => (
          <li key={i}>
            <Rich text={t} />
          </li>
        ))}
      </ul>
    );
  if ("steps" in b)
    return (
      <ol className="lesson-steps">
        {b.steps.map((t, i) => (
          <li key={i}>
            <Rich text={t} />
          </li>
        ))}
      </ol>
    );
  if ("table" in b)
    return (
      <div className="table-wrap">
        <table className="lesson-table">
          <thead>
            <tr>
              {b.table.head.map((h, i) => (
                <th key={i}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {b.table.rows.map((r, i) => (
              <tr key={i}>
                {r.map((c, j) => (j === 0 ? <th key={j}>{c}</th> : <td key={j}>{c}</td>))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  const V = VISUALS[b.visual];
  return (
    <figure className="lesson-visual">
      <figcaption>{b.title}</figcaption>
      <V />
    </figure>
  );
}

export function LessonView({ slug }: { slug: string }) {
  const found = findLesson(slug)!;
  const { lesson, module, index } = found;
  const { isDone, mark } = useProgress();
  const prev = LESSONS[index - 1];
  const next = LESSONS[index + 1];
  const moduleNo = MODULES.findIndex((m) => m.id === module.id) + 1;
  const pos = module.lessons.findIndex((l) => l.slug === slug) + 1;

  return (
    <article className="lesson">
      <nav className="lesson-crumbs" aria-label="Você está em">
        <Link href="/aprender">Aprender</Link> <span aria-hidden="true">›</span> Módulo {moduleNo}: {module.title}
      </nav>
      <header className="lesson-head">
        <p className="lesson-meta">
          Aula {pos} de {module.lessons.length} · {lesson.minutes} min{isDone(slug) && <span className="lesson-done-tag">Concluída</span>}
        </p>
        <h1>{lesson.title}</h1>
        <p className="lesson-summary">{lesson.summary}</p>
      </header>

      <div className="lesson-body">
        {lesson.blocks.map((b, i) => (
          <BlockView key={i} b={b} />
        ))}
      </div>

      {lesson.practice && (
        <aside className="lesson-practice">
          <p>{lesson.practice.text}</p>
          <Link className="btn btn-primary" href={lesson.practice.href}>
            {lesson.practice.label}
          </Link>
        </aside>
      )}

      <Quiz key={slug} questions={lesson.quiz} onFinish={() => mark(slug)} />

      {lesson.sources && (
        <section className="lesson-sources">
          <h2>Fontes</h2>
          <ul>
            {lesson.sources.map((s) => (
              <li key={s.url}>
                <a href={s.url} target="_blank" rel="noopener noreferrer">
                  {s.label}
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}

      <nav className="lesson-nav" aria-label="Outras aulas">
        {prev ? (
          <Link href={`/aprender/${prev.slug}`} className="lesson-nav-prev">
            <span>Anterior</span>
            {prev.title}
          </Link>
        ) : (
          <span />
        )}
        {next ? (
          <Link href={`/aprender/${next.slug}`} className="lesson-nav-next" onClick={() => !isDone(slug) && mark(slug)}>
            <span>Próxima</span>
            {next.title}
          </Link>
        ) : (
          <Link href="/aprender" className="lesson-nav-next">
            <span>Fim da trilha</span>
            Voltar ao início
          </Link>
        )}
      </nav>
    </article>
  );
}
