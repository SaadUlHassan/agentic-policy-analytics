import { describe, expect, it } from "vitest";

import { lastSeq, liveStatus, mergeEvents, pendingQuestion, terminalStatus } from "@/lib/events";
import type { AgentEvent } from "@/lib/types";

const ev = (seq: number, type = "rationale", detail: Record<string, unknown> = {}): AgentEvent => ({
  seq,
  ts: "2026-10-25T00:00:00Z",
  agent: "coordinator",
  type,
  title: `event ${seq}`,
  detail,
});

describe("mergeEvents", () => {
  it("orders by seq and drops duplicates from a replay after reconnect", () => {
    const merged = mergeEvents([ev(1), ev(2)], [ev(2), ev(4), ev(3)]);
    expect(merged.map((e) => e.seq)).toEqual([1, 2, 3, 4]);
  });

  it("is idempotent", () => {
    const once = mergeEvents([], [ev(1), ev(2)]);
    expect(mergeEvents(once, [ev(1), ev(2)])).toEqual(once);
  });

  it("tracks the resume cursor", () => {
    expect(lastSeq([])).toBe(0);
    expect(lastSeq(mergeEvents([], [ev(5), ev(3)]))).toBe(5);
  });
});

describe("terminalStatus", () => {
  it("is null while running and set once a terminal status event arrives", () => {
    expect(terminalStatus([ev(1, "status", { status: "running" })])).toBeNull();
    expect(terminalStatus([ev(1, "status", { status: "running" }), ev(2, "status", { status: "completed" })])).toBe(
      "completed",
    );
  });
});

describe("clarification state", () => {
  const question = { question: "Which sector?", options: ["ICT"], version: 1 };

  it("treats the latest question as pending until anything else happens", () => {
    const paused = [ev(1, "status", { status: "running" }), ev(2, "clarification", question)];
    expect(pendingQuestion(paused)).toEqual(question);
    expect(liveStatus(paused)).toBe("awaiting_input");

    const answered = [...paused, ev(3, "status", { status: "queued" })];
    expect(pendingQuestion(answered)).toBeNull();
    expect(liveStatus(answered)).toBe("queued");
  });
});
