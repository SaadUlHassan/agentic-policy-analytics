"""Deterministic statistical tools with explicit eligibility rules (plan §4.5).

Every tool returns a Computation or a Refusal with a reason code. Missing values inside a
requested window are refused rather than skipped or imputed.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import statsmodels.api as sm

from app.analytics import correlation
from app.analytics.results import (
    Computation,
    Interpretation,
    Interval,
    Refusal,
    RefusalCode,
    ResultField,
    SeriesInput,
    SeriesRef,
    ValueKind,
    fingerprint,
)
from app.data.identity import MeasureType
from app.data.models import SeriesData
from app.data.periods import Frequency, Period, years_between

MIN_TREND_POINTS = {Frequency.ANNUAL: 5, Frequency.QUARTERLY: 12}
MIN_ANNUAL_POINTS_FOR_INTERVAL = 8

_LEVEL_KIND = {
    MeasureType.STOCK: ValueKind.LEVEL,
    MeasureType.FLOW: ValueKind.FLOW,
    MeasureType.RATE: ValueKind.RATE,
}


class _Window:
    """Values for [start, end]. Endpoint tools need only the two ends; window tools need every
    period in between, so `missing` is computed for whichever the tool asks for."""

    def __init__(self, series: SeriesData, start: Period, end: Period, endpoints_only: bool) -> None:
        self.start, self.end = start, end
        values = series.value_map()
        span = [str(start.shift(i)) for i in range(end.ordinal - start.ordinal + 1)]
        self.periods = [span[0], span[-1]] if endpoints_only and len(span) > 1 else span
        present = {p: v for p in self.periods if p in values and (v := values[p].value) is not None}
        self.missing = [p for p in self.periods if p not in present]
        self.values: list[float] = [present[p] for p in self.periods if p in present]


class Toolkit:
    def __init__(self, taxonomy_version: str) -> None:
        self.taxonomy_version = taxonomy_version

    # -- helpers -----------------------------------------------------------------------------

    def _computation(
        self,
        tool: str,
        params: dict[str, Any],
        source: SeriesInput,
        periods: list[str],
        result: dict[str, ResultField],
        notes: list[str] | None = None,
    ) -> Computation:
        fp = fingerprint(tool, params, [source], self.taxonomy_version)
        ref = SeriesRef(**source.model_dump(), periods_used=periods)
        return Computation(
            id=f"c{fp[:8]}",
            fingerprint=fp,
            tool=tool,
            params=params,
            inputs=[ref],
            result=result,
            notes=notes or [],
        )

    @staticmethod
    def _refuse(
        tool: str, code: RefusalCode, detail: str, params: dict[str, Any], source: SeriesInput
    ) -> Refusal:
        return Refusal(tool=tool, code=code, detail=detail, params=params, series_key=source.series_key)

    @staticmethod
    def _field(
        source: SeriesInput,
        value: float,
        kind: ValueKind,
        start: str,
        end: str,
        unit: str | None = None,
        scale: int | None = None,
    ) -> ResultField:
        identity = source.identity
        return ResultField(
            value=float(value),
            metric=identity.metric,
            value_kind=kind,
            unit=unit or identity.unit,
            scale=identity.scale if scale is None else scale,
            interval=Interval(start=start, end=end),
        )

    @staticmethod
    def _window(
        tool: str,
        params: dict[str, Any],
        source: SeriesInput,
        series: SeriesData,
        start: str,
        end: str,
        *,
        endpoints_only: bool = False,
    ) -> _Window | Refusal:
        try:
            s, e = Period.parse(start), Period.parse(end)
            if s.frequency != source.identity.frequency or e.frequency != source.identity.frequency:
                raise ValueError(f"periods must be {source.identity.frequency}")
            if e.ordinal < s.ordinal:
                raise ValueError("end precedes start")
        except ValueError as exc:
            return Toolkit._refuse(tool, RefusalCode.INVALID_WINDOW, str(exc), params, source)
        window = _Window(series, s, e, endpoints_only)
        if window.missing:
            return Toolkit._refuse(
                tool, RefusalCode.MISSING_PERIODS, f"no value for {', '.join(window.missing)}", params, source
            )
        return window

    # -- tools -------------------------------------------------------------------------------

    def value_at(self, source: SeriesInput, series: SeriesData, period: str) -> Computation | Refusal:
        params = {"period": period}
        window = self._window("value_at", params, source, series, period, period)
        if isinstance(window, Refusal):
            return window
        kind = _LEVEL_KIND[source.identity.measure_type]
        field = self._field(source, window.values[0], kind, window.periods[0], window.periods[0])
        return self._computation("value_at", params, source, window.periods, {"value": field})

    def change_between(
        self, source: SeriesInput, series: SeriesData, start: str, end: str, tool: str = "change_between"
    ) -> Computation | Refusal:
        params = {"start": start, "end": end}
        if source.identity.measure_type is MeasureType.FLOW:
            return self._refuse(
                tool,
                RefusalCode.NOT_A_LEVEL,
                "the difference between two net-change values is "
                "not meaningful; use cumulative or compare_periods for a flow series",
                params,
                source,
            )
        window = self._window(tool, params, source, series, start, end, endpoints_only=True)
        if isinstance(window, Refusal):
            return window
        if window.start == window.end:
            return self._refuse(
                tool, RefusalCode.INVALID_WINDOW, "start and end are the same period", params, source
            )
        first, last = window.values[0], window.values[-1]
        s, e = window.periods[0], window.periods[-1]
        measure = source.identity.measure_type
        level_kind = _LEVEL_KIND[measure]
        result = {
            "start_value": self._field(source, first, level_kind, s, s),
            "end_value": self._field(source, last, level_kind, e, e),
        }
        if measure is MeasureType.RATE:
            result["pp_change"] = self._field(
                source, last - first, ValueKind.PP_CHANGE, s, e, unit="percentage_points"
            )
        else:
            result["abs_change"] = self._field(source, last - first, ValueKind.ABS_CHANGE, s, e)
        notes = []
        if measure is MeasureType.STOCK:
            if first == 0:
                notes.append("percentage change omitted: zero base")
            else:
                pct = (last - first) / abs(first) * 100
                result["pct_change"] = self._field(
                    source, pct, ValueKind.PCT_CHANGE, s, e, unit="percent", scale=1
                )
        return self._computation(tool, params, source, [s, e], result, notes)

    def cumulative(
        self, source: SeriesInput, series: SeriesData, start: str, end: str
    ) -> Computation | Refusal:
        """Sum of a flow over every period in a window: e.g. quarterly net employment changes add up to
        the change in employment over the window."""
        params = {"start": start, "end": end}
        if source.identity.measure_type is not MeasureType.FLOW:
            return self._refuse(
                "cumulative",
                RefusalCode.NOT_A_FLOW,
                f"only a flow series can be summed, not a {source.identity.measure_type}",
                params,
                source,
            )
        window = self._window("cumulative", params, source, series, start, end)
        if isinstance(window, Refusal):
            return window
        s, e = window.periods[0], window.periods[-1]
        field = self._field(source, float(np.sum(window.values)), ValueKind.TOTAL, s, e)
        return self._computation(
            "cumulative",
            params,
            source,
            window.periods,
            {"total": field},
            [f"sum of {len(window.values)} {source.identity.frequency} values"],
        )

    def yoy_change(self, source: SeriesInput, series: SeriesData, period: str) -> Computation | Refusal:
        try:
            prior = str(Period.parse(period).same_period_prior_year())
        except ValueError as exc:
            return self._refuse(
                "yoy_change", RefusalCode.INVALID_WINDOW, str(exc), {"period": period}, source
            )
        values = series.value_map()
        if prior not in values or values[prior].value is None:
            return self._refuse(
                "yoy_change",
                RefusalCode.MISSING_PRIOR_PERIOD,
                f"no value for {prior}",
                {"period": period},
                source,
            )
        return self.change_between(source, series, prior, period, tool="yoy_change")

    def cagr(self, source: SeriesInput, series: SeriesData, start: str, end: str) -> Computation | Refusal:
        params = {"start": start, "end": end}
        if source.identity.measure_type is not MeasureType.STOCK:
            return self._refuse(
                "cagr",
                RefusalCode.NOT_A_LEVEL,
                f"CAGR needs a stock/level series, not a {source.identity.measure_type}",
                params,
                source,
            )
        window = self._window("cagr", params, source, series, start, end, endpoints_only=True)
        if isinstance(window, Refusal):
            return window
        years = years_between(window.start, window.end)
        if years < 2:
            return self._refuse(
                "cagr", RefusalCode.INSUFFICIENT_SPAN, f"{years:g} years elapsed; need >= 2", params, source
            )
        first, last = window.values[0], window.values[-1]
        if first <= 0 or last <= 0:
            return self._refuse(
                "cagr", RefusalCode.NON_POSITIVE_ENDPOINT, "endpoints must be positive", params, source
            )
        rate = ((last / first) ** (1 / years) - 1) * 100
        s, e = window.periods[0], window.periods[-1]
        field = self._field(source, rate, ValueKind.CAGR_PCT, s, e, unit="percent_per_year", scale=1)
        return self._computation(
            "cagr", params, source, [s, e], {"cagr_pct": field}, [f"compounded over {years:g} elapsed years"]
        )

    def trend(self, source: SeriesInput, series: SeriesData, start: str, end: str) -> Computation | Refusal:
        params = {"start": start, "end": end}
        window = self._window("trend", params, source, series, start, end)
        if isinstance(window, Refusal):
            return window
        freq = source.identity.frequency
        n = len(window.values)
        if n < MIN_TREND_POINTS[freq]:
            return self._refuse(
                "trend",
                RefusalCode.INSUFFICIENT_POINTS,
                f"{n} points; need >= {MIN_TREND_POINTS[freq]} for a {freq} trend",
                params,
                source,
            )
        y = np.asarray(window.values, dtype=float)
        if np.ptp(y) == 0:
            return self._refuse("trend", RefusalCode.CONSTANT_SERIES, "series is constant", params, source)
        per_year = 1 if freq is Frequency.ANNUAL else 4
        t = np.arange(n) / per_year
        s, e = window.periods[0], window.periods[-1]
        unit = f"{source.identity.unit}_per_year"
        notes = ["ordinary least squares on time in years"]
        if freq is Frequency.ANNUAL and n < MIN_ANNUAL_POINTS_FOR_INTERVAL:
            slope = float(np.polyfit(t, y, 1)[0])
            notes.append(f"descriptive slope only: {n} annual points is too few for an interval")
            result = {"slope": self._field(source, slope, ValueKind.SLOPE, s, e, unit=unit)}
        else:
            # Newey-West (HAC) errors because consecutive observations are serially dependent.
            fit = sm.OLS(y, sm.add_constant(t)).fit(cov_type="HAC", cov_kwds={"maxlags": per_year})
            low, high = fit.conf_int(alpha=0.05)[1]
            notes.append(f"95% parameter confidence interval with HAC errors (maxlags={per_year})")
            result = {
                "slope": self._field(source, fit.params[1], ValueKind.SLOPE, s, e, unit=unit),
                "slope_ci_low": self._field(source, low, ValueKind.SLOPE_BOUND, s, e, unit=unit),
                "slope_ci_high": self._field(source, high, ValueKind.SLOPE_BOUND, s, e, unit=unit),
            }
        return self._computation("trend", params, source, window.periods, result, notes)

    def compare_periods(
        self, source: SeriesInput, series: SeriesData, a_start: str, a_end: str, b_start: str, b_end: str
    ) -> Computation | Refusal:
        params = {"a_start": a_start, "a_end": a_end, "b_start": b_start, "b_end": b_end}
        a = self._window("compare_periods", params, source, series, a_start, a_end)
        if isinstance(a, Refusal):
            return a
        b = self._window("compare_periods", params, source, series, b_start, b_end)
        if isinstance(b, Refusal):
            return b
        if b.start.ordinal <= a.end.ordinal:
            return self._refuse(
                "compare_periods",
                RefusalCode.INVALID_WINDOW,
                "window B must start after window A",
                params,
                source,
            )
        mean_a, mean_b = float(np.mean(a.values)), float(np.mean(b.values))
        diff_unit = "percentage_points" if source.identity.measure_type is MeasureType.RATE else None
        result = {
            "mean_a": self._field(source, mean_a, ValueKind.MEAN, a.periods[0], a.periods[-1]),
            "mean_b": self._field(source, mean_b, ValueKind.MEAN, b.periods[0], b.periods[-1]),
            "difference": self._field(
                source, mean_b - mean_a, ValueKind.DIFFERENCE, a.periods[0], b.periods[-1], unit=diff_unit
            ),
        }
        return self._computation("compare_periods", params, source, a.periods + b.periods, result)

    def correlate(
        self,
        x_source: SeriesInput,
        x_series: SeriesData,
        y_source: SeriesInput,
        y_series: SeriesData,
        start: str,
        end: str,
        lag: str | int = 0,
    ) -> Computation | Refusal:
        """Exploratory association between two series over [start, end] under a declared pairing
        rule (app.analytics.correlation). The series are ordered so the rule's leading series is
        first; `lag` is how many periods the second series trails it."""
        params: dict[str, Any] = {"start": start, "end": end, "lag": str(lag)}

        def refuse(code: str, detail: str) -> Refusal:
            return Refusal(
                tool="correlate",
                code=RefusalCode(code),
                detail=detail,
                params=params,
                series_key=x_source.series_key,
                other_series_key=y_source.series_key,
            )

        try:
            lag_n = int(lag)
            s, e = Period.parse(start), Period.parse(end)
            if lag_n < 0 or e.ordinal - s.ordinal < lag_n or s.frequency != e.frequency:
                raise ValueError("lag must be 0 or more and fit inside the window")
        except ValueError as exc:
            return refuse("INVALID_WINDOW", str(exc))
        # Canonical spellings ("01" is lag 1, "2020 1Q" is 2020-Q1): one request, one identity.
        start, end = str(s), str(e)
        params.update(start=start, end=end, lag=str(lag_n))
        if correlation.find_rule(x_source.identity, y_source.identity) is None and correlation.find_rule(
            y_source.identity, x_source.identity
        ):
            x_source, x_series, y_source, y_series = y_source, y_series, x_source, x_series
        try:
            rule = correlation.eligibility(x_source.identity, y_source.identity, lag_n)
            if s.frequency != x_source.identity.frequency:
                return refuse("INVALID_WINDOW", f"periods must be {x_source.identity.frequency}")
            aligned = correlation.align(x_series, y_series, rule, lag_n, s, e)
            pearson, spearman = correlation.coefficients(aligned)
        except correlation.Ineligible as exc:
            return refuse(exc.code, exc.detail)

        def field(value: float, kind: ValueKind, unit: str) -> ResultField:
            return ResultField(
                value=value,
                metric=f"{x_source.identity.metric}~{y_source.identity.metric}",
                value_kind=kind,
                unit=unit,
                scale=1,
                interval=Interval(start=start, end=end),
            )

        notes = [
            correlation.EXPLORATORY_NOTE,
            f"{rule.name}, lag {lag_n}: {rule.lag_meaning[lag_n]}",
            f"{len(aligned.pairs)} aligned pairs",
        ]
        caveats = [
            "consecutive quarters are serially dependent, so the coefficient overstates how much "
            "independent evidence there is; it shows co-movement, not cause",
            *rule.caveats,
        ]
        if x_source.identity.population != y_source.identity.population:
            caveats.append(
                "the two series count different populations ("
                f"{x_source.identity.population.replace('_', ' ')} vs "
                f"{y_source.identity.population.replace('_', ' ')})"
            )
        if aligned.skipped:
            caveats.append(f"quarters left out for missing values: {', '.join(aligned.skipped)}")
        sources = [x_source, y_source]
        fp = fingerprint("correlate", params, sources, self.taxonomy_version)
        refs = [
            SeriesRef(**x_source.model_dump(), periods_used=[px for px, _ in aligned.pairs]),
            SeriesRef(**y_source.model_dump(), periods_used=[py for _, py in aligned.pairs]),
        ]
        return Computation(
            id=f"c{fp[:8]}",
            fingerprint=fp,
            tool="correlate",
            params=params,
            inputs=refs,
            result={
                "pearson_r": field(pearson, ValueKind.COEFFICIENT, "correlation"),
                "spearman_rho": field(spearman, ValueKind.COEFFICIENT, "correlation"),
                "pairs": field(float(len(aligned.pairs)), ValueKind.COUNT, "pairs"),
            },
            interpretation_allowed=Interpretation.EXPLORATORY_ASSOCIATION,
            notes=notes,
            caveats=caveats,
        )
