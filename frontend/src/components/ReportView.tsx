"use client";

import { useState } from "react";

import { DataQualityPanel } from "@/components/DataQualityPanel";
import { SeriesChart, splitChart } from "@/components/SeriesChart";
import type { Citation, Finding, Report } from "@/lib/types";
import { platformName } from "@/lib/platforms";

function CitationChip({ id }: { id: string }) {
  return (
    <a href={`#cite-${id}`} className="ml-1 rounded bg-background px-1 text-xs text-ink-2 no-underline hover:underline">
      [{id}]
    </a>
  );
}

function SourceItem({ c }: { c: Citation }) {
  return (
    <li id={`cite-${c.id}`} className="text-sm">
      <span className="font-medium">[{c.id}]</span>{" "}
      <a href={c.url_human} target="_blank" rel="noreferrer" className="underline">
        {c.title}
      </a>
      <span className="text-ink-2">
        {" "}
        · {c.dataset_id} · {c.publisher} via {platformName(c.platform)} · originating agency {c.origin_agency}
      </span>
      <div className="text-xs text-ink-3">
        Series: {c.series.join("; ")} · periods {c.periods[0]}–{c.periods[c.periods.length - 1]} · retrieved{" "}
        {new Date(c.retrieved_at).toLocaleDateString()}
        {c.source_updated_at && ` · source updated ${c.source_updated_at}`}
        {c.from_snapshot && " · served from stored snapshot"}
      </div>
    </li>
  );
}

/** Only verified findings reach this view; every number in them was rendered from a computation. */
export function ReportView({ report }: { report: Report }) {
  const v = report.verification;
  // Series behind the finding being read stay prominent in the charts. A citation can cover several
  // series of one dataset, so lineage is by series; older reports fall back to their citations.
  const [highlight, setHighlight] = useState<ReadonlySet<string>>(new Set());
  const seriesOf = (f: Finding) =>
    f.series ??
    report.charts.flatMap((c) => c.series.filter((s) => f.citations.includes(s.citation)).map((s) => s.series_key));
  const focus = (f: Finding) => () => setHighlight(new Set(seriesOf(f)));
  const clear = () => setHighlight(new Set());
  return (
    <article aria-label="Report" className="flex flex-col gap-5">
      <header>
        <h2 className="text-lg font-semibold">{report.title}</h2>
        {report.summary && <p className="mt-1 text-ink-2">{report.summary}</p>}
      </header>

      <section aria-label="Findings">
        <h3 className="mb-2 text-base font-semibold">Verified findings</h3>
        {report.findings.length === 0 ? (
          <p className="text-sm text-ink-3">No finding passed verification.</p>
        ) : (
          <ol className="flex flex-col gap-2">
            {report.findings.map((f) => (
              <li
                key={f.id}
                tabIndex={0}
                onMouseEnter={focus(f)}
                onFocus={focus(f)}
                onMouseLeave={clear}
                onBlur={clear}
                className="rounded-lg border border-border bg-surface p-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--series-1)]"
              >
                {f.kind === "association" && (
                  <span className="mr-2 rounded border border-border px-1 text-xs text-ink-2">Exploratory association</span>
                )}
                {f.text}
                {f.citations.map((c) => (
                  <CitationChip key={c} id={c} />
                ))}
              </li>
            ))}
          </ol>
        )}
        <p className="mt-2 text-xs text-ink-3">
          {v.claims_verified} of {v.claims_drafted} drafted findings passed evidence checks
          {v.claims_rejected > 0 && `; ${v.claims_rejected} were removed`}.
          {v.narrative_check &&
            (v.narrative_check.independent
              ? ` Narrative checked independently (written by ${v.narrative_check.writers.join(", ")}, checked by ${v.narrative_check.judges.join(", ")}).`
              : ` Narrative checked by the same provider that wrote it (${v.narrative_check.writers.join(", ")}): not an independent check.`)}
        </p>
      </section>

      {report.charts.length > 0 && (
        <section aria-label="Charts" className="flex flex-col gap-3">
          <h3 className="text-base font-semibold">Source data</h3>
          {report.charts.flatMap(splitChart).map((chart) => (
            <SeriesChart key={chart.id} chart={chart} highlight={highlight} />
          ))}
        </section>
      )}

      {report.consistency_checks.length > 0 && (
        <section aria-label="Cross-platform checks">
          <h3 className="mb-2 text-base font-semibold">Cross-platform consistency</h3>
          <ul className="flex flex-col gap-1 text-sm">
            {report.consistency_checks.map((c) => {
              const agreed = c.comparable !== false && c.mismatches.length === 0;
              return (
                <li key={c.series.join("|")}>
                  <span className={agreed ? "text-good" : "text-warning"} aria-hidden>
                    {agreed ? "✓ " : "! "}
                  </span>
                  {c.comparable === false ? c.verdict : `${c.verdict} over ${c.periods_compared} periods`}
                  {c.citations.map((id) => (
                    <CitationChip key={id} id={id} />
                  ))}
                  <span className="block text-xs text-ink-3">Same originating agency: this confirms publication, not independent corroboration.</span>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <DataQualityPanel datasets={report.data_quality ?? []} />

      {report.limitations.length > 0 && (
        <section aria-label="Limitations">
          <h3 className="mb-2 text-base font-semibold">Limitations</h3>
          <ul className="list-disc pl-5 text-sm text-ink-2">
            {report.limitations.map((l) => (
              <li key={l.source + l.text}>{l.text}</li>
            ))}
          </ul>
        </section>
      )}

      {v.narrative_removed && v.narrative_removed.length > 0 && (
        <details className="text-xs text-ink-3">
          <summary className="cursor-pointer">{v.narrative_removed.length} narrative sentence(s) removed by the checker</summary>
          <ul className="list-disc pl-5">
            {v.narrative_removed.map((r) => (
              <li key={r.text}>
                “{r.text}” — {r.reason}
              </li>
            ))}
          </ul>
        </details>
      )}

      <section aria-label="Sources">
        <h3 className="mb-2 text-base font-semibold">Sources</h3>
        <ol className="flex flex-col gap-2">
          {report.citations.map((c) => (
            <SourceItem key={c.id} c={c} />
          ))}
        </ol>
      </section>
    </article>
  );
}
