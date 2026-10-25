import { describe, expect, it } from "vitest";

import { lastSeq, mergeEvents, terminalStatus } from "@/lib/events";
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
