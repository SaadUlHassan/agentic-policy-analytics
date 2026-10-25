"use client";

import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { Chart } from "@/lib/types";

// Validated categorical slots, assigned in fixed order. Never cycled: a chart holds at most three
// series (see splitChart), so a colour always means one series.
export const SERIES_COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];

/** Charts with more series than colours become small multiples rather than reusing a colour. */
export function splitChart(chart: Chart): Chart[] {
  if (chart.series.length <= SERIES_COLORS.length) return [chart];
  const parts: Chart[] = [];
  for (let i = 0; i < chart.series.length; i += SERIES_COLORS.length) {
    parts.push({ ...chart, id: `${chart.id}-${i}`, series: chart.series.slice(i, i + SERIES_COLORS.length) });
  }
  return parts;
}

export function unitLabel(unit: string, scale: number): string {
  const name = unit.replaceAll("_", " ");
  return scale === 1000 ? `thousand ${name}` : name;
}

const formatValue = (value: number) => value.toLocaleString(undefined, { maximumFractionDigits: 1 });

/** One unit per chart (never a dual axis). Values are the source observations, unmodified. */
export function SeriesChart({ chart }: { chart: Chart }) {
  const [asTable, setAsTable] = useState(false);
  const periods = [...new Set(chart.series.flatMap((s) => s.points.map((p) => p.period)))].sort();
  const rows = periods.map((period) => ({
    period,
    ...Object.fromEntries(chart.series.map((s) => [s.series_key, s.points.find((p) => p.period === period)?.value ?? null])),
  }));
  const unit = unitLabel(chart.unit, chart.scale);
  const multi = chart.series.length > 1;

  return (
    <figure className="rounded-lg border border-border bg-surface p-3">
      <figcaption className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-medium">
          {chart.title} <span className="font-normal text-ink-3">· {unit}</span>
        </span>
        <button type="button" onClick={() => setAsTable((v) => !v)} className="text-xs text-ink-2 underline">
          {asTable ? "Show chart" : "Show table"}
        </button>
      </figcaption>
      {asTable ? (
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="text-ink-3">
              <th className="py-1 font-medium">Period</th>
              {chart.series.map((s) => (
                <th key={s.series_key} className="py-1 font-medium">
                  {s.label} [{s.citation}]
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.period} className="border-t border-border">
                <td className="py-1">{row.period}</td>
                {chart.series.map((s) => {
                  const v = s.points.find((p) => p.period === row.period)?.value ?? null;
                  return (
                    <td key={s.series_key} className="py-1 tabular-nums">
                      {v === null ? "—" : formatValue(v)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="h-64 w-full">
          <ResponsiveContainer>
            <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="period" tick={{ fill: "var(--text-muted)", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "var(--border)" }} minTickGap={16} />
              <YAxis tick={{ fill: "var(--text-muted)", fontSize: 11 }} tickLine={false} axisLine={false} tickFormatter={formatValue} width={56} />
              <Tooltip
                formatter={(value) => [`${formatValue(Number(value))} ${unit}`]}
                contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text-primary)", fontSize: 12 }}
                cursor={{ stroke: "var(--text-muted)", strokeDasharray: "3 3" }}
              />
              {multi && <Legend wrapperStyle={{ fontSize: 12, color: "var(--text-secondary)" }} />}
              {chart.series.map((s, i) => (
                <Line
                  key={s.series_key}
                  type="linear"
                  dataKey={s.series_key}
                  name={`${s.label} [${s.citation}]`}
                  stroke={SERIES_COLORS[i]}
                  strokeWidth={2}
                  dot={{ r: 4, strokeWidth: 2, fill: "var(--surface)" }}
                  activeDot={{ r: 5 }}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      {!multi && chart.series[0] && (
        <p className="mt-1 text-xs text-ink-3">
          {chart.series[0].label} · source [{chart.series[0].citation}]
        </p>
      )}
    </figure>
  );
}
