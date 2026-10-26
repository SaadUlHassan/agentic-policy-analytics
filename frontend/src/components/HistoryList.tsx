"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import { listAnalyses } from "@/lib/api";
import type { AnalysisStatus, AnalysisSummary } from "@/lib/types";

const FILTERS: { value: "" | AnalysisStatus; label: string }[] = [
  { value: "", label: "All" },
  { value: "completed", label: "Completed" },
  { value: "completed_with_limitations", label: "With limitations" },
  { value: "awaiting_input", label: "Needs input" },
  { value: "running", label: "Running" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

/** Newest first, a page at a time (keyset pagination on the server). */
export function HistoryList() {
  const [status, setStatus] = useState<"" | AnalysisStatus>("");
  const [items, setItems] = useState<AnalysisSummary[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Bumped on every filter change: a page requested under an older filter is discarded on arrival.
  const generation = useRef(0);

  useEffect(() => {
    let cancelled = false;
    listAnalyses({ status: status || undefined })
      .then((page) => {
        if (cancelled) return;
        setItems(page.items);
        setCursor(page.next_cursor);
        setError(null);
      })
      .catch((err: unknown) => !cancelled && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
    };
  }, [status]);

  async function loadMore() {
    const requestedIn = generation.current;
    setLoading(true);
    try {
      const page = await listAnalyses({ cursor, status: status || undefined });
      if (requestedIn !== generation.current) return;
      setItems((current) => [...(current ?? []), ...page.items]);
      setCursor(page.next_cursor);
    } catch (err) {
      if (requestedIn === generation.current) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (requestedIn === generation.current) setLoading(false);
    }
  }

  function filterBy(next: "" | AnalysisStatus) {
    generation.current += 1;
    setLoading(false);
    setStatus(next);
    setItems(null);
    setCursor(null);
  }

  return (
    <div className="flex flex-col gap-2">
      <label className="flex items-center gap-2 text-xs text-ink-3">
        Show
        <select
          value={status}
          onChange={(e) => filterBy(e.target.value as "" | AnalysisStatus)}
          className="rounded border border-border bg-surface px-1 py-0.5 text-ink-2"
        >
          {FILTERS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
      </label>
      {error && <p className="text-sm text-critical">Could not load history: {error}</p>}
      {items === null && !error && <p className="text-sm text-ink-3">Loading history…</p>}
      {items?.length === 0 && <p className="text-sm text-ink-3">No analyses{status ? " with this status" : " yet"}.</p>}
      {items && items.length > 0 && (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
          {items.map((item) => (
            <li key={item.id}>
              <Link href={`/analyses/${item.id}`} className="flex flex-col gap-1 p-3 hover:bg-background sm:flex-row sm:items-center sm:justify-between">
                <span className="text-sm">{item.query}</span>
                <span className="flex items-center gap-3">
                  <StatusBadge status={item.status} />
                  <time dateTime={item.created_at} className="text-xs text-ink-3">
                    {new Date(item.created_at).toLocaleString()}
                  </time>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {cursor && (
        <button type="button" disabled={loading} onClick={() => void loadMore()} className="self-start text-xs text-ink-2 underline disabled:opacity-50">
          {loading ? "Loading…" : "Load more"}
        </button>
      )}
    </div>
  );
}
