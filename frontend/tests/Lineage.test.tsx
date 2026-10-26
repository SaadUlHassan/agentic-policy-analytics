import { act, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HistoryList } from "@/components/HistoryList";
import { ReportView } from "@/components/ReportView";
import type { Report } from "@/lib/types";

// jsdom draws no SVG, so lines are stubbed to expose the props under test.
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  LineChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Line: ({ dataKey, strokeOpacity }: { dataKey: string; strokeOpacity: number }) => (
    <span data-testid={`line-${dataKey}`} data-opacity={String(strokeOpacity)} />
  ),
  CartesianGrid: () => null,
  Legend: () => null,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

afterEach(() => vi.unstubAllGlobals());

const points = [{ period: "2020-Q1", value: 1 }];
const report = {
  title: "t",
  summary: "",
  plan: { intent: "", in_scope: true, scope_note: "", sectors: [], metrics: [], start_year: 2020, end_year: 2024, sub_questions: [], assumptions: [], rationale: "" },
  // Two sectors of one dataset share one citation; the finding is about ICT only.
  findings: [{ id: "k1", kind: "comparison", text: "ICT vacancies rose.", citations: ["S1"], series: ["ict"] }],
  charts: [
    {
      id: "c1", title: "Job vacancies", metric: "job_vacancies", frequency: "quarterly", unit: "vacancies", scale: 1,
      series: [
        { series_key: "ict", label: "ICT", dataset_id: "M184071", citation: "S1", points },
        { series_key: "mfg", label: "Manufacturing", dataset_id: "M184071", citation: "S1", points },
      ],
    },
  ],
  consistency_checks: [],
  limitations: [],
  citations: [],
  verification: { claims_drafted: 1, claims_verified: 1, claims_rejected: 0 },
} as unknown as Report;

describe("finding to chart lineage", () => {
  it("highlights only the series a finding rests on, even when sectors share a citation", () => {
    render(<ReportView report={report} />);
    fireEvent.mouseEnter(within(screen.getByRole("region", { name: "Findings" })).getByRole("listitem"));
    expect(screen.getByTestId("line-ict")).toHaveAttribute("data-opacity", "1");
    expect(screen.getByTestId("line-mfg")).toHaveAttribute("data-opacity", "0.25");
  });

  it("falls back to citations for reports stored before findings recorded their series", () => {
    const legacy = { ...report, findings: [{ ...report.findings[0], series: undefined }] };
    render(<ReportView report={legacy} />);
    fireEvent.mouseEnter(within(screen.getByRole("region", { name: "Findings" })).getByRole("listitem"));
    expect(screen.getByTestId("line-mfg")).toHaveAttribute("data-opacity", "1");
  });
});

describe("HistoryList paging across a filter change", () => {
  it("discards a page that arrives after the filter changed", async () => {
    const page = (id: string, next: string | null) =>
      Response.json({ items: [{ id, query: `query ${id}`, status: "completed", created_at: "2026-10-26T00:00:00Z", finished_at: null }], next_cursor: next });
    let release!: (r: Response) => void;
    const slow = new Promise<Response>((resolve) => (release = resolve));
    vi.stubGlobal("fetch", vi.fn((url: string) => (url.includes("status=failed") ? Promise.resolve(page("failed", null)) : url.includes("cursor=older") ? slow : Promise.resolve(page("first", "older")))));
    render(<HistoryList />);
    await screen.findByText("query first");
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "failed" } });
    await screen.findByText("query failed");

    await act(async () => {
      release(page("stale", "stale-cursor"));
      await slow;
    });

    expect(screen.queryByText("query stale")).toBeNull();
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });
});
