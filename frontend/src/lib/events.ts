import { type AgentEvent, type AnalysisStatus, TERMINAL_STATUSES } from "@/lib/types";

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
