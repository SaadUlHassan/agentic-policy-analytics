"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AgentTimeline } from "@/components/AgentTimeline";
import { PlanCard } from "@/components/PlanCard";
import { ReportView } from "@/components/ReportView";
import { StatusBadge } from "@/components/StatusBadge";
import { getAnalysis } from "@/lib/api";
import type { AnalysisDetail, Plan } from "@/lib/types";
import { useEventStream } from "@/lib/useEventStream";

export function AnalysisView({ id }: { id: string }) {
  const { events, connected, finalStatus } = useEventStream(id);
  const [analysis, setAnalysis] = useState<AnalysisDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Load on open, and again once the stream reports a terminal status (the report is then stored).
  useEffect(() => {
    getAnalysis(id)
      .then(setAnalysis)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, [id, finalStatus]);

  const livePlan = events.find((e) => e.type === "plan")?.detail as Plan | undefined;
  const plan = analysis?.plan ?? livePlan;
  const status = finalStatus ?? analysis?.status ?? "queued";

  if (error) {
    return (
      <p role="alert" className="text-critical">
        {error}
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-2">
        <Link href="/" className="text-xs text-ink-3 underline">
          ← New question
        </Link>
        <h1 className="text-xl font-semibold">{analysis?.query ?? "Loading…"}</h1>
        <div>
          <StatusBadge status={status} />
        </div>
        {analysis?.error && (
          <p role="alert" className="text-sm text-critical">
            The analysis could not finish ({analysis.error.code}).
          </p>
        )}
      </header>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className="order-2 lg:order-1">
          <AgentTimeline events={events} connected={connected} finished={finalStatus !== null} />
        </div>
        <div className="order-1 flex flex-col gap-4 lg:order-2">
          {plan && <PlanCard plan={plan} />}
          {analysis?.report ? (
            <ReportView report={analysis.report} />
          ) : (
            !finalStatus && <p className="text-sm text-ink-3">The report appears here when the agents finish.</p>
          )}
        </div>
      </div>
    </div>
  );
}
