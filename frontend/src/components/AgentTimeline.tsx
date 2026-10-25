"use client";

import { useState } from "react";

import type { AgentEvent } from "@/lib/types";

const AGENTS = ["coordinator", "extraction", "analytics", "system"] as const;
const AGENT_COLOR: Record<string, string> = {
  coordinator: "var(--series-1)",
  extraction: "var(--series-2)",
  analytics: "var(--series-3)",
  system: "var(--text-muted)",
};

// Event types that change the course of the analysis are emphasised; tool results stay compact.
const EMPHASIS: Record<string, string> = {
  decision: "Decision",
  plan: "Plan",
  selection: "Selected",
  selection_refused: "Refused by policy",
  rejection: "Rejected",
  consistency_check: "Cross-platform check",
  refusal: "Statistic refused",
  claim_verdict: "Verification",
  provider_fallback: "Provider fallback",
  narrative_check: "Narrative check",
  quality_report: "Data quality",
  report: "Report",
  error: "Error",
  status: "Status",
};

function str(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

function EventBody({ event }: { event: AgentEvent }) {
  const d = event.detail;
  switch (event.type) {
    case "rationale":
      return <p className="text-sm italic text-ink-2">“{event.title}”</p>;
    case "decision":
      return (
        <div className="text-sm">
          <p className="font-medium">{event.title}</p>
          <p className="text-ink-2">{str(d.rationale)}</p>
          {Boolean(d.policy_override) && (
            <p className="mt-1 text-warning">
              <span aria-hidden>⚑ </span>
              {str(d.policy_override)}
            </p>
          )}
        </div>
      );
    case "claim_verdict": {
      const failures = (d.failures as { name: string; detail: string }[]) ?? [];
      return d.passed ? (
        <p className="text-sm">
          <span className="text-good" aria-hidden>
            ✓{" "}
          </span>
          {str(d.rendered)}
        </p>
      ) : (
        <div className="text-sm">
          <p className="text-critical">
            <span aria-hidden>✕ </span>Draft rejected
          </p>
          <ul className="list-disc pl-5 text-ink-2">
            {failures.map((f) => (
              <li key={f.name + f.detail}>
                {f.name}: {f.detail}
              </li>
            ))}
          </ul>
        </div>
      );
    }
    case "tool_call":
      return (
        <p className="font-mono text-xs text-ink-2">
          {event.title}({Object.entries((d.args as Record<string, unknown>) ?? {}).map(([k, v]) => `${k}=${str(v)}`).join(", ")})
        </p>
      );
    case "tool_result":
      return (
        <details className="text-xs text-ink-3">
          <summary className="cursor-pointer">{d.ok ? "result" : "error"} from {event.title}</summary>
          <pre className="mt-1 whitespace-pre-wrap break-words">{str(d.summary)}</pre>
        </details>
      );
    case "quality_report": {
      // Issues arrive per series; show one total per issue type.
      const totals = new Map<string, number>();
      for (const i of (d.issues as { code: string; count: number }[]) ?? []) {
        totals.set(i.code, (totals.get(i.code) ?? 0) + i.count);
      }
      return (
        <div className="text-sm">
          <p>
            {str(d.title)} <span className="text-ink-3">({str(d.platform)})</span>
          </p>
          <p className="text-xs text-ink-2">
            {str(d.identified)} of {str(d.series)} series identified · issues:{" "}
            {[...totals].map(([code, count]) => `${code} ×${count}`).join(", ") || "none"}
          </p>
        </div>
      );
    }
    default:
      return (
        <p className="text-sm">
          {event.title}
          {typeof d.reason === "string" && <span className="text-ink-2"> — {d.reason}</span>}
          {Array.isArray(d.problems) && <span className="text-ink-2"> — {(d.problems as string[]).join("; ")}</span>}
        </p>
      );
  }
}

export function AgentTimeline({ events, connected, finished }: { events: AgentEvent[]; connected: boolean; finished: boolean }) {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const visible = events.filter((e) => !hidden.has(e.agent));
  const toggle = (agent: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(agent)) next.delete(agent);
      else next.add(agent);
      return next;
    });

  return (
    <section aria-label="Agent activity" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">Agent activity</h2>
        <span className="text-xs text-ink-3" aria-live="polite">
          {finished ? "✓ complete" : connected ? "● live" : "○ reconnecting"} · {events.length} events
        </span>
      </div>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by agent">
        {AGENTS.map((agent) => (
          <button
            key={agent}
            type="button"
            aria-pressed={!hidden.has(agent)}
            onClick={() => toggle(agent)}
            className="flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-xs aria-[pressed=false]:opacity-40"
          >
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: AGENT_COLOR[agent] }} aria-hidden />
            {agent}
          </button>
        ))}
      </div>
      <ol className="flex flex-col gap-2">
        {visible.map((event) => (
          <li key={event.seq} className="rounded-lg border border-border bg-surface p-2" style={{ borderLeft: `3px solid ${AGENT_COLOR[event.agent] ?? "var(--border)"}` }}>
            <div className="mb-0.5 flex items-center gap-2 text-xs text-ink-3">
              <span className="font-medium text-ink-2">{event.agent}</span>
              {EMPHASIS[event.type] && <span>· {EMPHASIS[event.type]}</span>}
              <span className="ml-auto">#{event.seq}</span>
            </div>
            <EventBody event={event} />
          </li>
        ))}
      </ol>
    </section>
  );
}
