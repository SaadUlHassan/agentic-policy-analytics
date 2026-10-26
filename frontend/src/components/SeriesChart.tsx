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

/** One unit per chart (never a dual axis). Values are the source observations, unmodified; the
 *  series toggles and period range only change what is shown, never the stored data.
 *  `highlight` holds series keys: the series behind the finding in focus stay prominent. */
export function SeriesChart({ chart, highlight }: { chart: Chart; highlight?: ReadonlySet<string> }) {
  const [asTable, setAsTable] = useState(false);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const allPeriods = [...new Set(chart.series.flatMap((s) => s.points.map((p) => p.period)))].sort();
  const [range, setRange] = useState<[number, number]>([0, allPeriods.length - 1]);
  const periods = allPeriods.slice(range[0], range[1] + 1);
  const shown = chart.series.filter((s) => !hidden.has(s.series_key));
  const dimmed = (seriesKey: string) => Boolean(highlight?.size) && !highlight?.has(seriesKey);
  const toggle = (key: string) =>
    setHidden((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else if (shown.length > 1) next.add(key); // at least one series stays visible
      return next;
    });
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
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        {multi &&
          chart.series.map((s, i) => (
            <button
              key={s.series_key}
              type="button"
              aria-pressed={!hidden.has(s.series_key)}
              onClick={() => toggle(s.series_key)}
              className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-ink-2 aria-pressed:text-ink-1 aria-[pressed=false]:line-through aria-[pressed=false]:opacity-60"
            >
              <span aria-hidden className="inline-block h-2 w-2 rounded-full" style={{ background: SERIES_COLORS[i] }} />
              {s.label}
            </button>
          ))}
        {allPeriods.length > 2 && (
          <span className="ml-auto inline-flex items-center gap-1 text-ink-3">
            <label htmlFor={`${chart.id}-from`}>From</label>
            <select
              id={`${chart.id}-from`}
              value={range[0]}
              onChange={(e) => setRange([Number(e.target.value), Math.max(Number(e.target.value), range[1])])}
              className="rounded border border-border bg-surface px-1"
            >
              {allPeriods.map((p, i) => (
                <option key={p} value={i}>
                  {p}
                </option>
              ))}
            </select>
            <label htmlFor={`${chart.id}-to`}>to</label>
            <select
              id={`${chart.id}-to`}
              value={range[1]}
              onChange={(e) => setRange([Math.min(range[0], Number(e.target.value)), Number(e.target.value)])}
              className="rounded border border-border bg-surface px-1"
            >
              {allPeriods.map((p, i) => (
                <option key={p} value={i}>
                  {p}
                </option>
              ))}
            </select>
          </span>
        )}
      </div>
      {asTable ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="text-ink-3">
                <th className="py-1 font-medium">Period</th>
                {shown.map((s) => (
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
                  {shown.map((s) => {
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
        </div>
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
              {chart.series.map((s, i) =>
                hidden.has(s.series_key) ? null : (
                  <Line
                    key={s.series_key}
                    type="linear"
                    dataKey={s.series_key}
                    name={`${s.label} [${s.citation}]`}
                    stroke={SERIES_COLORS[i]}
                    strokeOpacity={dimmed(s.series_key) ? 0.25 : 1}
                    strokeWidth={dimmed(s.series_key) ? 2 : highlight?.size ? 3 : 2}
                    dot={{ r: 4, strokeWidth: 2, fill: "var(--surface)" }}
                    activeDot={{ r: 5 }}
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                ),
              )}
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
