"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { createAnalysis } from "@/lib/api";

export const SAMPLE_QUERIES = [
  "Analyse employment trends in the technology sector from 2020-2024",
  "How have job vacancies in financial and insurance services changed since 2020?",
  "Compare employment changes in construction and manufacturing from 2021 to 2024",
];

const MIN_LENGTH = 3;
const MAX_LENGTH = 1000;

export function QueryForm() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const trimmed = query.trim();
  const valid = trimmed.length >= MIN_LENGTH && trimmed.length <= MAX_LENGTH;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const { id } = await createAnalysis(trimmed);
      router.push(`/analyses/${id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the analysis");
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3" aria-label="New research question">
      <label htmlFor="query" className="text-sm font-medium">
        Research question
      </label>
      <textarea
        id="query"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        maxLength={MAX_LENGTH}
        rows={3}
        placeholder="e.g. Analyse employment trends in the technology sector from 2020-2024"
        className="w-full rounded-lg border border-border bg-surface p-3 text-sm outline-none focus:ring-2 focus:ring-[var(--series-1)]"
      />
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="submit"
          disabled={!valid || submitting}
          className="rounded-lg bg-[var(--series-1)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {submitting ? "Starting…" : "Run analysis"}
        </button>
        <span className="text-xs text-ink-3">
          {trimmed.length}/{MAX_LENGTH}
        </span>
      </div>
      {error && (
        <p role="alert" className="text-sm text-critical">
          {error}
        </p>
      )}
      <div className="flex flex-col gap-1">
        <span className="text-xs text-ink-3">Try a sample:</span>
        <div className="flex flex-wrap gap-2">
          {SAMPLE_QUERIES.map((sample) => (
            <button
              key={sample}
              type="button"
              onClick={() => setQuery(sample)}
              className="rounded-full border border-border px-3 py-1 text-left text-xs text-ink-2 hover:bg-surface"
            >
              {sample}
            </button>
          ))}
        </div>
      </div>
    </form>
  );
}
