"use client";

import { type FormEvent, useState } from "react";

import { ApiError, type ClarificationAnswer, clarifyAnalysis } from "@/lib/api";
import type { ClarificationQuestion } from "@/lib/types";

const CONFLICT_MESSAGES: Record<string, string> = {
  CLARIFICATION_STALE: "This question was already answered. The latest state is shown.",
  NOT_AWAITING_INPUT: "The analysis is no longer waiting for an answer.",
  ALREADY_TERMINAL: "The analysis has already finished.",
};

/** The coordinator's question. The researcher picks an option, writes an answer, or lets the
 *  agents continue on their stated assumptions. */
export function ClarificationCard({
  analysisId,
  question,
  onAnswered,
}: {
  analysisId: string;
  question: ClarificationQuestion;
  onAnswered: () => void;
}) {
  const [answer, setAnswer] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(choice: ClarificationAnswer) {
    setSending(true);
    setError(null);
    try {
      await clarifyAnalysis(analysisId, question.version, choice);
      onAnswered();
    } catch (err) {
      const conflict = err instanceof ApiError ? CONFLICT_MESSAGES[err.code] : undefined;
      setError(conflict ?? (err instanceof Error ? err.message : "Could not send the answer"));
      if (conflict) onAnswered();
      setSending(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (answer.trim()) void send({ answer: answer.trim() });
  }

  return (
    <section aria-label="Question from the coordinator" className="rounded-lg border border-warning bg-surface p-4 text-sm">
      <h2 className="mb-2 text-base font-semibold">The coordinator needs your input</h2>
      <p>{question.question}</p>
      {question.options.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {question.options.map((option) => (
            <button
              key={option}
              type="button"
              disabled={sending}
              onClick={() => void send({ answer: option })}
              className="rounded-full border border-border px-3 py-1 text-left text-xs text-ink-2 hover:bg-surface disabled:opacity-50"
            >
              {option}
            </button>
          ))}
        </div>
      )}
      <form onSubmit={submit} className="mt-3 flex flex-col gap-2 sm:flex-row">
        <label htmlFor="clarification" className="sr-only">
          Your answer
        </label>
        <input
          id="clarification"
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          maxLength={500}
          placeholder="Or write your own answer"
          className="min-w-0 flex-1 rounded-lg border border-border bg-surface px-3 py-2 outline-none focus:ring-2 focus:ring-[var(--series-1)]"
        />
        <button
          type="submit"
          disabled={sending || !answer.trim()}
          className="rounded-lg bg-[var(--series-1)] px-4 py-2 font-medium text-white disabled:opacity-50"
        >
          Answer
        </button>
      </form>
      <button
        type="button"
        disabled={sending}
        onClick={() => void send({ proceed_with_assumptions: true })}
        className="mt-2 text-xs text-ink-2 underline disabled:opacity-50"
      >
        Proceed with stated assumptions
      </button>
      {error && (
        <p role="alert" className="mt-2 text-critical">
          {error}
        </p>
      )}
    </section>
  );
}
