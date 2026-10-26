import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DataQualityPanel } from "@/components/DataQualityPanel";
import type { DatasetQuality } from "@/lib/types";

const dataset: DatasetQuality = {
  dataset_id: "mrsd_3_qtly_emp_chg_by_ind",
  title: "Quarterly Employment Change by Industry (SSIC 2020)",
  platform: "mom",
  role: "cross-check",
  series: ["mrsd_3_qtly_emp_chg_by_ind:J58-63 INFORMATION AND COMMUNICATIONS@SSIC2020"],
  from_snapshot: true,
  retrieved_at: "2026-10-25T16:31:20+00:00",
  checks: [
    { code: "PERIOD_FOOTNOTE", severity: "info", message: "period headers carry a footnote mark", count: 1 },
    { code: "UNIT_MISMATCH", severity: "error", message: "sheet states hundreds; catalogue expects x1000", count: 1 },
    { code: "SERVED_FROM_SNAPSHOT", severity: "warning", message: "using snapshot retrieved 2026-10-25", count: 1 },
  ],
  markers: [{ marker: "-", count: 3, meaning: "Nil or negligible", treatment: "set to null and excluded from calculations" }],
};

describe("DataQualityPanel", () => {
  it("summarises each dataset and lists blocking errors first, with words not only colour", () => {
    render(<DataQualityPanel datasets={[dataset]} />);
    const panel = screen.getByRole("region", { name: "Data quality" });
    expect(within(panel).getByText(/used to cross-check · 1 blocking, 1 warning/)).toBeInTheDocument();
    fireEvent.click(within(panel).getByText("mrsd_3_qtly_emp_chg_by_ind"));
    const items = within(panel).getAllByRole("listitem").map((li) => li.textContent ?? "");
    expect(items[0]).toMatch(/^✕ Blocks use\s*UNIT_MISMATCH/);
    expect(items[1]).toMatch(/^! Warning/);
    expect(items[2]).toMatch(/^i Note/);
  });

  it("shows each marker with the source's own meaning and how it was treated", () => {
    render(<DataQualityPanel datasets={[dataset]} />);
    const table = screen.getByRole("table");
    expect(within(table).getByText("Nil or negligible")).toBeInTheDocument();
    expect(within(table).getByText("set to null and excluded from calculations")).toBeInTheDocument();
  });

  it("renders nothing when the report relied on no dataset", () => {
    const { container } = render(<DataQualityPanel datasets={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
