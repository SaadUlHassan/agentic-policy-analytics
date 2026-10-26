import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReportView } from "@/components/ReportView";
import { SERIES_COLORS, splitChart } from "@/components/SeriesChart";
import type { Chart, Report } from "@/lib/types";

const chart: Chart = {
  id: "chart1",
  title: "Employment level (annual)",
  metric: "employment_level",
  frequency: "annual",
  unit: "persons",
  scale: 1000,
  series: [
    {
      series_key: "M182841:3.4@SSIC2020",
      label: "Information & Communications",
      dataset_id: "M182841",
      citation: "S1",
      points: [
        { period: "2020", value: 157.6 },
        { period: "2024", value: 180.3 },
      ],
    },
  ],
};

const report: Report = {
  title: "ICT employment",
  summary: "",
  plan: {
    intent: "ICT employment 2020-2024",
    in_scope: true,
    scope_note: "",
    sectors: ["info_comms"],
    metrics: ["employment_level"],
    start_year: 2020,
    end_year: 2024,
    sub_questions: [],
    assumptions: [],
    rationale: "",
  },
  findings: [
    { id: "k1", kind: "comparison", text: "Employment rose by 14.4% between 2020 and 2024.", citations: ["S1"] },
  ],
  charts: [chart],
  consistency_checks: [
    { series: ["a", "b"], verdict: "consistent", periods_compared: 20, mismatches: [], citations: ["S1", "S2"] },
  ],
  limitations: [{ source: "data", text: "Vacancies are rounded to the nearest 100." }],
  citations: [
    {
      id: "S1",
      dataset_id: "M182841",
      title: "Employment (Persons) By Sector",
      publisher: "DOS",
      origin_agency: "MOM",
      platform: "singstat",
      series: ["Employment level in Information & Communications"],
      periods: ["2020", "2024"],
      url_human: "https://tablebuilder.singstat.gov.sg/table/TS/M182841",
      retrieved_at: "2026-10-25T00:00:00Z",
      source_updated_at: null,
      from_snapshot: true,
    },
  ],
  verification: {
    claims_drafted: 3,
    claims_verified: 1,
    claims_rejected: 2,
    narrative_removed: [{ text: "Tech jobs shifted regionally.", reason: "adds regions" }],
  },
};

describe("ReportView", () => {
  it("shows verified findings with citation links to their sources", () => {
    render(<ReportView report={report} />);
    const findings = screen.getByRole("region", { name: "Findings" });
    expect(within(findings).getByText(/rose by 14.4%/)).toBeInTheDocument();
    expect(within(findings).getByRole("link", { name: "[S1]" })).toHaveAttribute("href", "#cite-S1");
    expect(screen.getByText("1 of 3 drafted findings passed evidence checks; 2 were removed.")).toBeInTheDocument();
    expect(document.getElementById("cite-S1")).toHaveTextContent("served from stored snapshot");
  });

  it("discloses removed narrative and the limits of a same-origin check", () => {
    render(<ReportView report={report} />);
    expect(screen.getByText(/1 narrative sentence\(s\) removed/)).toBeInTheDocument();
    expect(screen.getByText(/not independent corroboration/)).toBeInTheDocument();
  });

  it("offers a table of the exact source values", () => {
    render(<ReportView report={report} />);
    fireEvent.click(screen.getByRole("button", { name: "Show table" }));
    const table = screen.getByRole("table");
    expect(within(table).getByText("180.3")).toBeInTheDocument();
    expect(within(table).getByText("Information & Communications [S1]")).toBeInTheDocument();
  });
});

describe("splitChart", () => {
  it("turns more series than colours into small multiples instead of cycling colours", () => {
    const many = { ...chart, series: Array.from({ length: 5 }, (_, i) => ({ ...chart.series[0], series_key: `s${i}` })) };
    const parts = splitChart(many);
    expect(parts.map((p) => p.series.length)).toEqual([3, 2]);
    expect(parts.every((p) => p.series.length <= SERIES_COLORS.length)).toBe(true);
  });
});

describe("verifier independence", () => {
  it("says when the narrative was checked by the provider that wrote it", () => {
    const same = { ...report, verification: { ...report.verification, narrative_check: { writers: ["bedrock"], judges: ["bedrock"], independent: false } } };
    render(<ReportView report={same} />);
    expect(screen.getByText(/checked by the same provider that wrote it \(bedrock\): not an independent check/)).toBeInTheDocument();
  });

  it("marks association findings as exploratory", () => {
    const withAssociation = {
      ...report,
      findings: [...report.findings, { id: "k2", kind: "association", text: "Vacancies and hiring tended to be higher together.", citations: [] }],
    };
    render(<ReportView report={withAssociation} />);
    expect(screen.getByText("Exploratory association")).toBeInTheDocument();
  });
});

describe("cross-platform checks", () => {
  it("never shows a refused cross-check as agreement", () => {
    const refused = {
      ...report,
      consistency_checks: [
        {
          series: ["a", "b"],
          verdict: "not comparable (blocking quality errors: mrsd_3_qtly_emp_chg_by_ind: UNIT_MISMATCH)",
          comparable: false,
          periods_compared: 0,
          mismatches: [],
          citations: [],
        },
      ],
    };
    render(<ReportView report={refused} />);
    const section = screen.getByRole("region", { name: "Cross-platform checks" });
    expect(within(section).getByText(/not comparable \(blocking quality errors/)).toBeInTheDocument();
    expect(section.textContent).not.toMatch(/✓|over 0 periods/);
  });
});

