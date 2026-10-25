// Shapes returned by the FastAPI backend (app/api/analyses.py, app/agents/report.py).

export type AnalysisStatus =
  | "queued"
  | "running"
  | "awaiting_input"
  | "completed"
  | "completed_with_limitations"
  | "failed"
  | "cancelled";

export const TERMINAL_STATUSES: ReadonlySet<AnalysisStatus> = new Set([
  "completed",
  "completed_with_limitations",
  "failed",
  "cancelled",
]);

export type AgentEvent = {
  seq: number;
  ts: string;
  agent: string;
  type: string;
  title: string;
  detail: Record<string, unknown>;
};

export type Plan = {
  intent: string;
  in_scope: boolean;
  scope_note: string;
  sectors: string[];
  metrics: string[];
  start_year: number | null;
  end_year: number | null;
  sub_questions: string[];
  assumptions: string[];
  rationale: string;
};

export type Finding = { id: string; kind: string; text: string; citations: string[] };

export type ChartSeries = {
  series_key: string;
  label: string;
  dataset_id: string;
  citation: string;
  points: { period: string; value: number | null }[];
};

export type Chart = {
  id: string;
  title: string;
  metric: string;
  frequency: string;
  unit: string;
  scale: number;
  series: ChartSeries[];
};

export type Citation = {
  id: string;
  dataset_id: string;
  title: string;
  publisher: string;
  origin_agency: string;
  platform: string;
  series: string[];
  periods: string[];
  url_human: string;
  retrieved_at: string;
  source_updated_at: string | null;
  from_snapshot: boolean;
};

export type ConsistencyCheck = {
  series: string[];
  verdict: string;
  periods_compared: number;
  mismatches: Record<string, unknown>[];
  citations: string[];
};

export type Report = {
  title: string;
  summary: string;
  plan: Plan;
  findings: Finding[];
  charts: Chart[];
  consistency_checks: ConsistencyCheck[];
  limitations: { source: string; text: string }[];
  citations: Citation[];
  verification: {
    claims_drafted: number;
    claims_verified: number;
    claims_rejected: number;
    narrative_removed?: { text: string; reason: string }[];
  };
};

export type AnalysisSummary = {
  id: string;
  query: string;
  status: AnalysisStatus;
  created_at: string;
  finished_at: string | null;
};

export type AnalysisDetail = AnalysisSummary & {
  plan: Plan | null;
  report: Report | null;
  error: { code: string; detail?: string } | null;
  last_event_seq: number;
};
