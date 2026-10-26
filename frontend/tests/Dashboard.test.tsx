import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HistoryList } from "@/components/HistoryList";
import { SeriesChart } from "@/components/SeriesChart";
import { UsageSummary } from "@/components/UsageSummary";
import type { Chart } from "@/lib/types";

const chart: Chart = {
  id: "c1",
  title: "Job vacancies (quarterly)",
  metric: "job_vacancies",
  frequency: "quarterly",
  unit: "vacancies",
  scale: 1,
  series: [
    { series_key: "a", label: "Information & Communications", dataset_id: "M184071", citation: "S1", points: [
      { period: "2020-Q1", value: 4600 }, { period: "2020-Q2", value: 3900 }, { period: "2020-Q3", value: 4300 },
    ] },
    { series_key: "b", label: "Manufacturing", dataset_id: "M184071", citation: "S2", points: [
      { period: "2020-Q1", value: 5200 }, { period: "2020-Q2", value: 5100 }, { period: "2020-Q3", value: 5600 },
    ] },
  ],
};

afterEach(() => vi.unstubAllGlobals());

describe("SeriesChart interactions", () => {
  it("toggles series off but always keeps one visible", () => {
    render(<SeriesChart chart={chart} />);
    const ict = screen.getByRole("button", { name: /Information & Communications/ });
    const mfg = screen.getByRole("button", { name: /Manufacturing/ });
    fireEvent.click(ict);
    expect(ict).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(mfg); // the last visible series cannot be hidden
    expect(mfg).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Show table" }));
    const table = screen.getByRole("table");
    expect(within(table).queryByText(/Information & Communications/)).toBeNull();
    expect(within(table).getByText("Manufacturing [S2]")).toBeInTheDocument();
  });

  it("filters the period range shown without touching other periods' values", () => {
    render(<SeriesChart chart={chart} />);
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Show table" }));
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.firstChild?.textContent)).toEqual(["2020-Q2", "2020-Q3"]);
  });
});

describe("UsageSummary", () => {
  it("shows calls, tokens and time, and says when cost is not configured", () => {
    render(
      <UsageSummary
        usage={{ llm_calls: 12, failed_calls: 2, input_tokens: 9000, output_tokens: 1000, llm_latency_ms: 21400,
          providers: { openai: 10 }, cost_usd: null, unpriced_models: ["gpt-5.5"], active_ms: 60000 }}
      />,
    );
    expect(screen.getByLabelText("Usage")).toHaveTextContent(
      "12 LLM calls (2 failed) · openai 10 · 10,000 tokens · LLM time 21.4 s · active 60.0 s · cost not configured",
    );
  });
});

describe("HistoryList", () => {
  it("filters by status and loads further pages with the cursor", async () => {
    const page = (ids: string[], next: string | null) =>
      Response.json({ items: ids.map((id) => ({ id, query: `q ${id}`, status: "completed", created_at: "2026-10-26T00:00:00Z", finished_at: null })), next_cursor: next });
    const fetchMock = vi.fn(async (url: string) =>
      url.includes("cursor=abc") ? page(["3"], null) : url.includes("status=failed") ? page([], null) : page(["1", "2"], "abc"),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<HistoryList />);

    expect(await screen.findByText("q 1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("q 3")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "failed" } });
    expect(await screen.findByText("No analyses with this status.")).toBeInTheDocument();
    await waitFor(() => expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain("status=failed"));
  });
});
