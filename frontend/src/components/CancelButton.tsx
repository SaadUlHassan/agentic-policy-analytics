"use client";

import { useState } from "react";

import { ApiError, cancelAnalysis } from "@/lib/api";

/** Queued or paused analyses stop at once; a running one stops at its next step. */
export function CancelButton({ analysisId, requested }: { analysisId: string; requested: boolean }) {
  const [pending, setPending] = useState(requested);
  const [error, setError] = useState<string | null>(null);

  async function cancel() {
    setPending(true);
    setError(null);
    try {
      await cancelAnalysis(analysisId);
    } catch (err) {
      if (err instanceof ApiError && err.code === "ALREADY_TERMINAL") return;
      setError(err instanceof Error ? err.message : "Could not cancel");
      setPending(false);
    }
  }

  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        onClick={() => void cancel()}
        disabled={pending}
        className="rounded-lg border border-border px-3 py-1 text-xs text-ink-2 hover:bg-surface disabled:opacity-50"
      >
        {pending ? "Cancelling…" : "Cancel analysis"}
      </button>
      {error && (
        <span role="alert" className="text-xs text-critical">
          {error}
        </span>
      )}
    </span>
  );
}
