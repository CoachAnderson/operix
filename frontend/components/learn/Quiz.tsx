"use client";

import { useState } from "react";
import type { Question } from "@/lib/learn/lessons";

/** Quiz curto: resposta imediata com explicação. Chama onFinish quando todas forem respondidas. */
export function Quiz({ questions, onFinish }: { questions: Question[]; onFinish: (correct: number) => void }) {
  const [answers, setAnswers] = useState<(number | null)[]>(() => questions.map(() => null));

  function choose(qi: number, oi: number) {
    if (answers[qi] !== null) return;
    const next = answers.map((a, i) => (i === qi ? oi : a));
    setAnswers(next);
    if (next.every((a) => a !== null)) onFinish(next.filter((a, i) => a === questions[i].answer).length);
  }

  const finished = answers.every((a) => a !== null);
  const correct = answers.filter((a, i) => a === questions[i].answer).length;

  return (
    <section className="quiz" aria-labelledby="quiz-title">
      <h2 id="quiz-title">Confira o que ficou</h2>
      {questions.map((q, qi) => {
        const a = answers[qi];
        return (
          <fieldset key={qi} className="quiz-q">
            <legend>
              {qi + 1}. {q.q}
            </legend>
            <div className="quiz-options">
              {q.options.map((o, oi) => {
                const state = a === null ? "" : oi === q.answer ? "right" : oi === a ? "wrong" : "dim";
                return (
                  <button key={oi} type="button" className={`quiz-opt ${state}`} onClick={() => choose(qi, oi)} disabled={a !== null} aria-pressed={a === oi}>
                    {o}
                  </button>
                );
              })}
            </div>
            {a !== null && (
              <p className={`quiz-why ${a === q.answer ? "gain" : "loss"}`} role="status">
                <strong>{a === q.answer ? "Isso mesmo." : "Não é bem isso."}</strong> {q.why}
              </p>
            )}
          </fieldset>
        );
      })}
      {finished && (
        <div className="quiz-done">
          <strong>
            {correct} de {questions.length} certas.
          </strong>{" "}
          {correct === questions.length ? "Aula concluída." : "Aula concluída. Se quiser, releia o trecho das que errou."}
          {correct < questions.length && (
            <button type="button" className="btn btn-quiet" onClick={() => setAnswers(questions.map(() => null))}>
              Refazer o quiz
            </button>
          )}
        </div>
      )}
    </section>
  );
}
