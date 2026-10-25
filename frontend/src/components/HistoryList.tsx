"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import { listAnalyses } from "@/lib/api";
import type { AnalysisSummary } from "@/lib/types";

export function HistoryList() {
  const [items, setItems] = useState<AnalysisSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listAnalyses()
      .then((page) => setItems(page.items))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  if (error) return <p className="text-sm text-critical">Could not load history: {error}</p>;
  if (items === null) return <p className="text-sm text-ink-3">Loading history…</p>;
  if (items.length === 0) return <p className="text-sm text-ink-3">No analyses yet.</p>;
  return (
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
  );
}
