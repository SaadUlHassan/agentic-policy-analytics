import { type AgentEvent, type AnalysisStatus, type ClarificationQuestion, TERMINAL_STATUSES } from "@/lib/types";

/** Merge incoming events into the timeline: ordered by seq, duplicates dropped.
 *  The server may replay events after a reconnect, so merging must be idempotent. */
export function mergeEvents(current: AgentEvent[], incoming: AgentEvent[]): AgentEvent[] {
  const bySeq = new Map(current.map((e) => [e.seq, e]));
  for (const event of incoming) bySeq.set(event.seq, event);
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq);
}

/** Highest sequence number seen: the cursor to resume from after a disconnect. */
export function lastSeq(events: AgentEvent[]): number {
  return events.length ? events[events.length - 1].seq : 0;
}

export function terminalStatus(events: AgentEvent[]): AnalysisStatus | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    const status = e.type === "status" ? (e.detail.status as AnalysisStatus) : null;
    if (status && TERMINAL_STATUSES.has(status)) return status;
  }
  return null;
}

/** The status the event history implies right now (a question means the analysis is paused). */
export function liveStatus(events: AgentEvent[]): AnalysisStatus | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.type === "clarification") return "awaiting_input";
    if (e.type === "status" && e.detail.status) return e.detail.status as AnalysisStatus;
  }
  return null;
}

/** The question waiting for an answer: the latest one, if nothing has happened since. */
export function pendingQuestion(events: AgentEvent[]): ClarificationQuestion | null {
  const last = events[events.length - 1];
  return last?.type === "clarification" ? (last.detail as ClarificationQuestion) : null;
}
