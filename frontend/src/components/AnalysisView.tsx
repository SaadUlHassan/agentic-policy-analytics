"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AgentTimeline } from "@/components/AgentTimeline";
import { CancelButton } from "@/components/CancelButton";
import { ClarificationCard } from "@/components/ClarificationCard";
import { PlanCard } from "@/components/PlanCard";
import { ReportView } from "@/components/ReportView";
import { StatusBadge } from "@/components/StatusBadge";
import { UsageSummary } from "@/components/UsageSummary";
import { type ExportFormat, exportUrl, getAnalysis } from "@/lib/api";
import { liveStatus, pendingQuestion } from "@/lib/events";
import { type AnalysisDetail, type Plan, TERMINAL_STATUSES } from "@/lib/types";
import { useEventStream } from "@/lib/useEventStream";

const EXPORTS: Record<ExportFormat, string> = {
  md: "Report (Markdown)",
  json: "Evidence bundle (JSON)",
  csv: "Source values (CSV)",
};

export function AnalysisView({ id }: { id: string }) {
  const { events, connected, finalStatus } = useEventStream(id);
  const [analysis, setAnalysis] = useState<AnalysisDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  // Load on open, again once the stream reports a terminal status (the report is then stored),
  // and after a clarification answer was sent or refused.
  useEffect(() => {
    getAnalysis(id)
      .then(setAnalysis)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, [id, finalStatus, reload]);

  const livePlan = events.find((e) => e.type === "plan")?.detail as Plan | undefined;
  const plan = analysis?.plan ?? livePlan;
  const status = finalStatus ?? liveStatus(events) ?? analysis?.status ?? "queued";
  // The stream is authoritative once it has events; before that, the stored question.
  const question = events.length ? pendingQuestion(events) : (analysis?.clarification ?? null);

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
        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge status={status} />
          {analysis && !TERMINAL_STATUSES.has(status) && (
            <CancelButton analysisId={id} requested={analysis.cancel_requested && status === "running"} />
          )}
        </div>
        {analysis?.report && (
          <nav aria-label="Export" className="flex flex-wrap items-center gap-2 text-xs text-ink-2">
            <span className="text-ink-3">Export:</span>
            {(Object.entries(EXPORTS) as [ExportFormat, string][]).map(([format, label]) => (
              <a key={format} href={exportUrl(id, format)} download className="underline">
                {label}
              </a>
            ))}
          </nav>
        )}
        {analysis?.usage && finalStatus && <UsageSummary usage={analysis.usage} />}
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
          {question && (
            <ClarificationCard
              key={question.version}
              analysisId={id}
              question={question}
              onAnswered={() => setReload((n) => n + 1)}
            />
          )}
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
