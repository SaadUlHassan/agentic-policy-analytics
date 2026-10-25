import type { Plan } from "@/lib/types";

const humanise = (key: string) => key.replaceAll("_", " ");

export function PlanCard({ plan }: { plan: Plan }) {
  return (
    <section aria-label="Research plan" className="rounded-lg border border-border bg-surface p-4 text-sm">
      <h2 className="mb-2 text-base font-semibold">Research plan</h2>
      <p>{plan.intent}</p>
      {plan.in_scope ? (
        <dl className="mt-3 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-ink-2">
          <dt className="text-ink-3">Sectors</dt>
          <dd>{plan.sectors.map(humanise).join(", ")}</dd>
          <dt className="text-ink-3">Metrics</dt>
          <dd>{plan.metrics.map(humanise).join(", ")}</dd>
          <dt className="text-ink-3">Period</dt>
          <dd>
            {plan.start_year}–{plan.end_year}
          </dd>
        </dl>
      ) : (
        <p className="mt-2 text-warning">Out of scope: {plan.scope_note}</p>
      )}
      {plan.assumptions.length > 0 && (
        <div className="mt-3">
          <h3 className="text-xs font-medium text-ink-3">Assumptions</h3>
          <ul className="list-disc pl-5 text-ink-2">
            {plan.assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </div>
      )}
      {plan.sub_questions.length > 0 && (
        <div className="mt-3">
          <h3 className="text-xs font-medium text-ink-3">Questions to answer</h3>
          <ul className="list-disc pl-5 text-ink-2">
            {plan.sub_questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
