import type { DatasetQuality, QualityCheck } from "@/lib/types";

// Severity is never shown by colour alone: every check has an icon and a word.
const SEVERITY: Record<QualityCheck["severity"], { icon: string; label: string; className: string; order: number }> = {
  error: { icon: "✕", label: "Blocks use", className: "text-critical", order: 0 },
  warning: { icon: "!", label: "Warning", className: "text-warning", order: 1 },
  info: { icon: "i", label: "Note", className: "text-ink-3", order: 2 },
};

function counts(checks: QualityCheck[]): string {
  const errors = checks.filter((c) => c.severity === "error").length;
  const warnings = checks.filter((c) => c.severity === "warning").length;
  if (!errors && !warnings) return "no problems found";
  return [errors && `${errors} blocking`, warnings && `${warnings} warning${warnings > 1 ? "s" : ""}`]
    .filter(Boolean)
    .join(", ");
}

/** What was checked on every dataset the report relies on, and what was found. */
export function DataQualityPanel({ datasets }: { datasets: DatasetQuality[] }) {
  if (datasets.length === 0) return null;
  return (
    <section aria-label="Data quality" className="flex flex-col gap-2">
      <h3 className="text-base font-semibold">Data quality</h3>
      {datasets.map((d) => {
        const checks = [...d.checks].sort((a, b) => SEVERITY[a.severity].order - SEVERITY[b.severity].order);
        return (
          <details key={d.dataset_id} className="rounded-lg border border-border bg-surface p-3 text-sm">
            <summary className="cursor-pointer">
              <span className="font-medium">{d.dataset_id}</span>{" "}
              <span className="text-ink-2">
                · {d.platform} · {d.role === "evidence" ? "used as evidence" : "used to cross-check"} · {counts(d.checks)}
                {d.from_snapshot && " · served from stored snapshot"}
              </span>
            </summary>
            <p className="mt-2 text-xs text-ink-3">{d.title}</p>
            {checks.length > 0 ? (
              <ul className="mt-2 flex flex-col gap-1">
                {checks.map((c) => {
                  const s = SEVERITY[c.severity];
                  return (
                    <li key={c.code + c.message} className="flex gap-2">
                      <span className={`shrink-0 font-medium ${s.className}`}>
                        <span aria-hidden>{s.icon} </span>
                        {s.label}
                      </span>
                      <span>
                        <code className="text-xs">{c.code}</code> {c.message}
                        {c.count > 1 && <span className="text-ink-3"> ({c.count})</span>}
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="mt-2 text-ink-3">All checks passed.</p>
            )}
            {d.markers.length > 0 && (
              <table className="mt-3 w-full text-left text-xs">
                <caption className="mb-1 text-left text-ink-3">Source markers in the series used</caption>
                <thead>
                  <tr className="text-ink-3">
                    <th className="pr-2 font-medium">Marker</th>
                    <th className="pr-2 font-medium">Source meaning</th>
                    <th className="pr-2 font-medium">Values</th>
                    <th className="font-medium">Treatment</th>
                  </tr>
                </thead>
                <tbody>
                  {d.markers.map((m) => (
                    <tr key={m.marker}>
                      <td className="pr-2 font-mono">{m.marker}</td>
                      <td className="pr-2">{m.meaning}</td>
                      <td className="pr-2">{m.count}</td>
                      <td>{m.treatment}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </details>
        );
      })}
    </section>
  );
}
