from __future__ import annotations

import math

import pytest
from scipy import stats

from app.analytics.results import Computation, Refusal, RefusalCode, SeriesInput, ValueKind
from app.analytics.tools import Toolkit
from app.data.identity import MeasureType, SeriesIdentity
from app.data.models import Observation, SeriesData
from app.data.periods import Frequency

TOOLS = Toolkit(taxonomy_version="test")

# Real SingStat M182841 'Information And Communications', thousands, year-end (snapshot of 2026-10-25).
ICT_EMPLOYMENT = {"2019": 154.8, "2020": 157.6, "2021": 172.9, "2022": 187.8, "2023": 181.9, "2024": 180.3}


def _series(
    values: dict[str, float | None],
    measure=MeasureType.STOCK,
    freq=Frequency.ANNUAL,
    unit="persons",
    scale=1000,
):
    identity = SeriesIdentity(
        scheme="SSIC2020",
        sector="info_comms",
        sector_label="Information & Communications",
        sector_code="J",
        metric="employment_level",
        measure_type=measure,
        reference_convention="year_end",
        population="total_employment",
        frequency=freq,
        unit=unit,
        scale=scale,
    )
    data = SeriesData(
        key="M182841:3.4@SSIC2020",
        label="ICT",
        source_ref="3.4",
        identity=identity,
        observations=[Observation(period=p, value=v, raw=str(v)) for p, v in values.items()],
    )
    return SeriesInput(artifact_id="a1", dataset_id="M182841", series_key=data.key, identity=identity), data


def _ok(result) -> Computation:
    assert isinstance(result, Computation), result
    return result


def _refused(result, code: RefusalCode) -> Refusal:
    assert isinstance(result, Refusal) and result.code is code, result
    return result


def test_change_between_stock_gives_absolute_and_percentage_change():
    c = _ok(TOOLS.change_between(*_series(ICT_EMPLOYMENT), "2020", "2024"))
    assert c.result["abs_change"].value == pytest.approx(180.3 - 157.6, rel=1e-12)
    assert c.result["pct_change"].value == pytest.approx((180.3 - 157.6) / 157.6 * 100, rel=1e-12)
    assert c.result["pct_change"].interval.model_dump() == {"start": "2020", "end": "2024"}
    assert c.result["start_value"].value_kind is ValueKind.LEVEL


def test_flow_series_cannot_be_differenced_between_endpoints():
    flow = _series({"2020": -800, "2021": 1500}, measure=MeasureType.FLOW)
    _refused(TOOLS.change_between(*flow, "2020", "2021"), RefusalCode.NOT_A_LEVEL)


def test_cumulative_sums_a_flow_over_every_period_and_refuses_stocks():
    flow = _series(
        {"2020-Q1": 700.0, "2020-Q2": -800.0, "2020-Q3": 1500.0},
        measure=MeasureType.FLOW,
        freq=Frequency.QUARTERLY,
        scale=1,
    )
    c = _ok(TOOLS.cumulative(*flow, "2020-Q1", "2020-Q3"))
    assert c.result["total"].value == 1400 and c.result["total"].value_kind is ValueKind.TOTAL
    _refused(TOOLS.cumulative(*_series(ICT_EMPLOYMENT), "2020", "2024"), RefusalCode.NOT_A_FLOW)
    gap = _series({"2020-Q1": 700.0, "2020-Q3": 1500.0}, measure=MeasureType.FLOW, freq=Frequency.QUARTERLY)
    _refused(TOOLS.cumulative(*gap, "2020-Q1", "2020-Q3"), RefusalCode.MISSING_PERIODS)


def test_rate_series_change_is_in_percentage_points():
    c = _ok(
        TOOLS.change_between(
            *_series({"2020": 2.4, "2021": 3.1}, measure=MeasureType.RATE, unit="percent", scale=1),
            "2020",
            "2021",
        )
    )
    assert c.result["pp_change"].unit == "percentage_points"
    assert c.result["pp_change"].value == pytest.approx(0.7, rel=1e-12)
    assert "pct_change" not in c.result


def test_zero_base_omits_percentage_change():
    c = _ok(TOOLS.change_between(*_series({"2020": 0.0, "2021": 5.0}), "2020", "2021"))
    assert "pct_change" not in c.result and c.result["abs_change"].value == 5


def test_endpoint_tools_need_only_endpoints_but_refuse_a_missing_endpoint():
    gap_inside = {**ICT_EMPLOYMENT, "2022": None}
    assert _ok(TOOLS.change_between(*_series(gap_inside), "2020", "2024")).inputs[0].periods_used == [
        "2020",
        "2024",
    ]
    assert _ok(TOOLS.cagr(*_series(gap_inside), "2020", "2024"))
    gap_at_end = {**ICT_EMPLOYMENT, "2024": None}
    r = _refused(TOOLS.change_between(*_series(gap_at_end), "2020", "2024"), RefusalCode.MISSING_PERIODS)
    assert "2024" in r.detail


def test_window_tools_refuse_any_missing_value_rather_than_skip_it():
    gap_inside = {**ICT_EMPLOYMENT, "2022": None}
    r = _refused(TOOLS.trend(*_series(gap_inside), "2020", "2024"), RefusalCode.MISSING_PERIODS)
    assert "2022" in r.detail


def test_yoy_uses_the_actual_prior_period():
    c = _ok(TOOLS.yoy_change(*_series(ICT_EMPLOYMENT), "2024"))
    assert c.tool == "yoy_change" and c.params == {"start": "2023", "end": "2024"}
    q = _series({"2023-Q2": 100.0, "2024-Q1": 90.0, "2024-Q2": 110.0}, freq=Frequency.QUARTERLY)
    assert _ok(TOOLS.yoy_change(*q, "2024-Q2")).result["abs_change"].value == 10
    _refused(TOOLS.yoy_change(*_series(ICT_EMPLOYMENT), "2019"), RefusalCode.MISSING_PRIOR_PERIOD)


def test_cagr_uses_elapsed_years():
    c = _ok(TOOLS.cagr(*_series(ICT_EMPLOYMENT), "2020", "2024"))
    assert c.result["cagr_pct"].value == pytest.approx(((180.3 / 157.6) ** 0.25 - 1) * 100, rel=1e-12)


@pytest.mark.parametrize(
    ("values", "measure", "start", "end", "code"),
    [
        (ICT_EMPLOYMENT, MeasureType.FLOW, "2020", "2024", RefusalCode.NOT_A_LEVEL),
        (ICT_EMPLOYMENT, MeasureType.STOCK, "2023", "2024", RefusalCode.INSUFFICIENT_SPAN),
        (
            {"2020": -1.0, "2021": 1.0, "2022": 2.0},
            MeasureType.STOCK,
            "2020",
            "2022",
            RefusalCode.NON_POSITIVE_ENDPOINT,
        ),
    ],
)
def test_cagr_eligibility(values, measure, start, end, code):
    _refused(TOOLS.cagr(*_series(values, measure=measure), start, end), code)


def test_annual_trend_matches_independent_regression_and_has_no_interval_below_8_points():
    c = _ok(TOOLS.trend(*_series(ICT_EMPLOYMENT), "2020", "2024"))
    years = [2020, 2021, 2022, 2023, 2024]
    reference = stats.linregress(years, [ICT_EMPLOYMENT[str(y)] for y in years]).slope
    assert c.result["slope"].value == pytest.approx(reference, rel=1e-9)
    assert set(c.result) == {"slope"} and c.result["slope"].unit == "persons_per_year"


def test_quarterly_trend_has_hac_interval_containing_the_slope():
    values = {f"{2020 + i // 4}-Q{i % 4 + 1}": 4000 + 150 * i + (300 if i % 3 else -200) for i in range(16)}
    c = _ok(TOOLS.trend(*_series(values, freq=Frequency.QUARTERLY, scale=1), "2020-Q1", "2023-Q4"))
    low, slope, high = (c.result[k].value for k in ("slope_ci_low", "slope", "slope_ci_high"))
    assert low < slope < high
    assert any("HAC" in n for n in c.notes)


def test_trend_eligibility():
    short = {"2022": 1.0, "2023": 2.0, "2024": 3.0}
    _refused(TOOLS.trend(*_series(short), "2022", "2024"), RefusalCode.INSUFFICIENT_POINTS)
    flat = {str(y): 5.0 for y in range(2018, 2025)}
    _refused(TOOLS.trend(*_series(flat), "2018", "2024"), RefusalCode.CONSTANT_SERIES)


def test_compare_periods_requires_disjoint_ordered_windows():
    c = _ok(TOOLS.compare_periods(*_series(ICT_EMPLOYMENT), "2019", "2020", "2023", "2024"))
    expected = (ICT_EMPLOYMENT["2023"] + ICT_EMPLOYMENT["2024"]) / 2 - (
        ICT_EMPLOYMENT["2019"] + ICT_EMPLOYMENT["2020"]
    ) / 2
    assert c.result["difference"].value == pytest.approx(expected, rel=1e-12)
    _refused(
        TOOLS.compare_periods(*_series(ICT_EMPLOYMENT), "2019", "2022", "2021", "2024"),
        RefusalCode.INVALID_WINDOW,
    )


def test_wrong_frequency_or_reversed_window_is_invalid():
    _refused(TOOLS.change_between(*_series(ICT_EMPLOYMENT), "2020-Q1", "2024-Q1"), RefusalCode.INVALID_WINDOW)
    _refused(TOOLS.change_between(*_series(ICT_EMPLOYMENT), "2024", "2020"), RefusalCode.INVALID_WINDOW)


def test_fingerprint_is_stable_for_same_evidence_and_changes_with_it():
    src, data = _series(ICT_EMPLOYMENT)
    a = _ok(TOOLS.cagr(src, data, "2020", "2024"))
    assert _ok(TOOLS.cagr(src, data, "2020", "2024")).id == a.id
    assert _ok(TOOLS.cagr(src, data, "2021", "2024")).id != a.id
    other_artifact = src.model_copy(update={"artifact_id": "a2"})
    assert _ok(TOOLS.cagr(other_artifact, data, "2020", "2024")).id != a.id
    assert _ok(Toolkit("other-taxonomy").cagr(src, data, "2020", "2024")).id != a.id
    assert not math.isnan(a.result["cagr_pct"].value)
