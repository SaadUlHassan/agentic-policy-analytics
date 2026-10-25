import { API_URL } from "@/lib/config";
import type { AnalysisDetail, AnalysisSummary } from "@/lib/types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // Only requests with a body declare JSON, so plain GETs need no CORS preflight.
  const headers = init?.body ? { "content-type": "application/json", ...init.headers } : init?.headers;
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    // Errors are RFC 7807 problem+json with a stable `code`.
    const problem = await res.json().catch(() => ({}));
    throw new ApiError(res.status, problem.code ?? `HTTP_${res.status}`, problem.title ?? res.statusText);
  }
  return (await res.json()) as T;
}

export const createAnalysis = (query: string) =>
  request<{ id: string; status: string }>("/api/analyses", { method: "POST", body: JSON.stringify({ query }) });

export const getAnalysis = (id: string) => request<AnalysisDetail>(`/api/analyses/${encodeURIComponent(id)}`);

export const listAnalyses = (limit = 20) =>
  request<{ items: AnalysisSummary[]; next_cursor: string | null }>(`/api/analyses?limit=${limit}`);

export function eventStreamUrl(id: string, afterSeq: number): string {
  const base = API_URL.replace(/^http/, "ws");
  return `${base}/ws/analyses/${encodeURIComponent(id)}?after_seq=${afterSeq}`;
}
