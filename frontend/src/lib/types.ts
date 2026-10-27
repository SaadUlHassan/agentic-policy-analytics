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
  // Set when the researcher asked for annual or quarterly figures; absent in older plans.
  frequency?: "annual" | "quarterly" | null;
  // First period of the later part when the question compares before and after a point in time.
  comparison_start?: string | null;
  sub_questions: string[];
  assumptions: string[];
  rationale: string;
};

export type Finding = {
  id: string;
  kind: string;
  text: string;
  citations: string[];
  series?: string[]; // series keys the finding rests on (absent in reports stored before it existed)
};

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
  comparable?: boolean;
  periods_compared: number;
  mismatches: Record<string, unknown>[];
  citations: string[];
};

export type QualityCheck = { code: string; severity: "error" | "warning" | "info"; message: string; count: number };

export type DatasetQuality = {
  dataset_id: string;
  title: string;
  platform: string;
  role: "evidence" | "cross-check";
  series: string[];
  from_snapshot: boolean;
  retrieved_at: string;
  checks: QualityCheck[];
  markers: { marker: string; count: number; meaning: string; treatment: string }[];
};

export type Report = {
  title: string;
  summary: string;
  plan: Plan;
  findings: Finding[];
  charts: Chart[];
  consistency_checks: ConsistencyCheck[];
  data_quality?: DatasetQuality[];
  limitations: { source: string; text: string }[];
  citations: Citation[];
  verification: {
    claims_drafted: number;
    claims_verified: number;
    claims_rejected: number;
    narrative_removed?: { text: string; reason: string }[];
    narrative_check?: { writers: string[]; judges: string[]; independent: boolean };
  };
};

export type AnalysisSummary = {
  id: string;
  query: string;
  status: AnalysisStatus;
  created_at: string;
  finished_at: string | null;
};

export type ClarificationQuestion = { question: string; options: string[]; version: number };

export type AnalysisDetail = AnalysisSummary & {
  plan: Plan | null;
  report: Report | null;
  error: { code: string; detail?: string } | null;
  clarification: ClarificationQuestion | null;
  cancel_requested: boolean;
  usage?: Usage;
  last_event_seq: number;
};

export type Usage = {
  llm_calls: number;
  failed_calls: number;
  input_tokens: number;
  output_tokens: number;
  llm_latency_ms: number;
  providers: Record<string, number>;
  cost_usd: number | null;
  unpriced_models: string[];
  active_ms: number;
};
