import type { Usage } from "@/lib/types";

const seconds = (ms: number) => `${(ms / 1000).toFixed(1)} s`;

/** What the analysis cost to run, from the LLM call ledger. Cost appears only when every model used
 *  has a configured price: a partial total would look complete. */
export function UsageSummary({ usage }: { usage: Usage }) {
  const providers = Object.entries(usage.providers)
    .map(([p, n]) => `${p} ${n}`)
    .join(", ");
  const cost = usage.cost_usd === null ? "cost not configured" : `$${usage.cost_usd.toFixed(4)}`;
  return (
    <p aria-label="Usage" className="text-xs text-ink-3">
      {usage.llm_calls} LLM calls{usage.failed_calls > 0 && ` (${usage.failed_calls} failed)`}
      {providers && ` · ${providers}`} · {(usage.input_tokens + usage.output_tokens).toLocaleString()} tokens · LLM time{" "}
      {seconds(usage.llm_latency_ms)} · active {seconds(usage.active_ms)} · {cost}
    </p>
  );
}
