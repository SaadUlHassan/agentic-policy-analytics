import type { AnalysisStatus } from "@/lib/types";

// Status is never conveyed by colour alone: every badge has an icon and a label.
const STYLES: Record<AnalysisStatus, { label: string; icon: string; className: string }> = {
  queued: { label: "Queued", icon: "○", className: "text-ink-2 border-border" },
  running: { label: "Running", icon: "◔", className: "text-ink-2 border-border" },
  awaiting_input: { label: "Needs input", icon: "?", className: "text-warning border-warning" },
  completed: { label: "Completed", icon: "✓", className: "text-good border-good" },
  completed_with_limitations: { label: "Completed with limitations", icon: "!", className: "text-warning border-warning" },
  failed: { label: "Failed", icon: "✕", className: "text-critical border-critical" },
  cancelled: { label: "Cancelled", icon: "–", className: "text-ink-3 border-border" },
};

export function StatusBadge({ status }: { status: AnalysisStatus }) {
  const style = STYLES[status];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${style.className}`}>
      <span aria-hidden>{style.icon}</span>
      {style.label}
    </span>
  );
}
