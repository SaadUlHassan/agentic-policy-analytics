"""Exploratory correlation (plan §4.5, F5): pairing rules, refusal codes and the named demo pair."""

from __future__ import annotations

import math

import pytest

from app.analytics.results import Interpretation, RefusalCode, SeriesInput
from app.connectors.catalog import get_catalog
from app.connectors.http import Fetcher, get_snapshot_store
from app.connectors.registry import fetch
from app.data.identity import MeasureType, SeriesIdentity
from app.data.models import Observation, SeriesData
from app.data.periods import Frequency
from app.data.taxonomy import get_taxonomy
from app.grounding.checks import verify_claim
from app.grounding.contracts import Assertion, Claim, ClaimKind
from app.grounding.render import render_claim
from tests.unit.test_analytics_tools import TOOLS, _ok, _refused

WINDOW = ("2020-Q1", "2024-Q4")
QUARTERS = [f"{y}-Q{q}" for y in range(2020, 2025) for q in range(1, 5)]


async def _ict(dataset_id: str) -> tuple[SeriesInput, SeriesData]:
    fetcher = Fetcher(mode="snapshot", snapshots=get_snapshot_store())
    dataset = await fetch(dataset_id, get_catalog(), get_taxonomy(), fetcher)
    (series,) = dataset.find("info_comms")
    assert series.identity is not None
    source = SeriesInput(
        artifact_id=dataset.artifact_id,
        dataset_id=dataset_id,
        series_key=series.key,
        identity=series.identity,
    )
    return source, series


@pytest.fixture
async def pair():
    """The named pair: ICT vacancies at quarter end (M184071) x ICT employment change (M183891)."""
    return await _ict("M184071"), await _ict("M183891")


# -- an independent implementation for the golden values ------------------------------------------


def _pearson(x: list[float], y: list[float]) -> float:
    mx, my = sum(x) / len(x), sum(y) / len(y)
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    return cov / math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))


def _ranks(values: list[float]) -> list[float]:
    """Average ranks for ties (vacancies are rounded to 100, so ties occur)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def _expected(x: SeriesData, y: SeriesData, lag: int) -> tuple[int, float, float]:
    xs, ys = x.value_map(), y.value_map()
    pairs = [(xs[QUARTERS[i]].value, ys[QUARTERS[i + lag]].value) for i in range(len(QUARTERS) - lag)]
    a, b = [p[0] for p in pairs], [p[1] for p in pairs]
    return len(pairs), _pearson(a, b), _pearson(_ranks(a), _ranks(b))


# -- the named pair ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("lag", "n"), [(0, 20), (1, 19)])
async def test_named_pair_matches_independently_computed_values(pair, lag, n):
    (vac_src, vac), (emp_src, emp) = pair
    result = _ok(TOOLS.correlate(vac_src, vac, emp_src, emp, *WINDOW, lag))

    expected_n, pearson, spearman = _expected(vac, emp, lag)
    assert expected_n == n and result.result["pairs"].value == n
    assert result.result["pearson_r"].value == pytest.approx(pearson, rel=1e-6)
    assert result.result["spearman_rho"].value == pytest.approx(spearman, rel=1e-6)
    assert result.interpretation_allowed is Interpretation.EXPLORATORY_ASSOCIATION
    assert set(result.result) == {"pearson_r", "spearman_rho", "pairs"}, "no p-values"
    assert "not causal" in result.notes[0]
    assert any("establishments vs total_employment" in note for note in result.notes)


async def test_lag_one_pairs_each_quarter_end_with_the_following_quarter_inside_the_window(pair):
    (vac_src, vac), (emp_src, emp) = pair
    result = _ok(TOOLS.correlate(vac_src, vac, emp_src, emp, *WINDOW, 1))
    x_ref, y_ref = result.inputs
    assert (x_ref.periods_used[0], y_ref.periods_used[0]) == ("2020-Q1", "2020-Q2")
    assert (x_ref.periods_used[-1], y_ref.periods_used[-1]) == ("2024-Q3", "2024-Q4")


async def test_argument_order_does_not_change_which_series_leads(pair):
    (vac_src, vac), (emp_src, emp) = pair
    forward = _ok(TOOLS.correlate(vac_src, vac, emp_src, emp, *WINDOW, 1))
    reversed_ = _ok(TOOLS.correlate(emp_src, emp, vac_src, vac, *WINDOW, 1))
    assert forward.id == reversed_.id and reversed_.inputs[0].dataset_id == "M184071"


# -- refusals ---------------------------------------------------------------------------------------


async def test_annual_year_end_employment_vs_annual_average_vacancies_is_a_reference_mismatch():
    emp_src, emp = await _ict("M182841")  # stock at year end
    vac_src, vac = await _ict("d_01966fdb498fa7fa2863635e25539693")  # mean of the four quarter ends
    refusal = _refused(
        TOOLS.correlate(emp_src, emp, vac_src, vac, "2020", "2024", 0), RefusalCode.REFERENCE_MISMATCH
    )
    assert "year_end vs average_of_quarter_ends" in refusal.detail


async def test_quarterly_against_annual_is_never_resampled(pair):
    (vac_src, vac), _ = pair
    emp_src, emp = await _ict("M182841")
    _refused(TOOLS.correlate(vac_src, vac, emp_src, emp, *WINDOW, 0), RefusalCode.FREQ_MISMATCH)


async def test_a_parent_and_its_subsector_are_different_code_sets(pair):
    (vac_src, vac), (emp_src, emp) = pair
    child = emp_src.identity.model_copy(update={"sector": "it_info_services"})
    _refused(
        TOOLS.correlate(vac_src, vac, emp_src.model_copy(update={"identity": child}), emp, *WINDOW, 0),
        RefusalCode.CLASSIFICATION_MISMATCH,
    )


async def test_undeclared_lags_and_pairs_have_no_pairing_rule(pair):
    (vac_src, vac), (emp_src, emp) = pair
    _refused(TOOLS.correlate(vac_src, vac, emp_src, emp, *WINDOW, 2), RefusalCode.NO_PAIRING_RULE)
    mom_src, mom = await _ict("mrsd_3_qtly_emp_chg_by_ind")
    # Two flows (here the same statistic on two platforms): no rule says how they align.
    _refused(TOOLS.correlate(emp_src, emp, mom_src, mom, *WINDOW, 0), RefusalCode.NO_PAIRING_RULE)


async def test_fewer_than_twelve_aligned_pairs_is_refused(pair):
    (vac_src, vac), (emp_src, emp) = pair
    refusal = _refused(
        TOOLS.correlate(vac_src, vac, emp_src, emp, "2022-Q1", "2024-Q4", 1), RefusalCode.INSUFFICIENT_PAIRS
    )
    assert "11 aligned complete pairs" in refusal.detail


def _quarterly(
    values: list[float | None], measure: MeasureType, convention: str
) -> tuple[SeriesInput, SeriesData]:
    identity = SeriesIdentity(
        scheme="SSIC2020",
        sector="info_comms",
        sector_label="Information & Communications",
        sector_code="J",
        metric="job_vacancies" if measure is MeasureType.STOCK else "employment_change",
        measure_type=measure,
        reference_convention=convention,
        population="establishments",
        frequency=Frequency.QUARTERLY,
        unit="persons",
        scale=1,
    )
    observations = [Observation(period=p, value=v, raw=str(v)) for p, v in zip(QUARTERS, values, strict=True)]
    data = SeriesData(
        key=f"s:{measure}", label="ICT", source_ref="1", identity=identity, observations=observations
    )
    return SeriesInput(artifact_id="a", dataset_id="d", series_key=data.key, identity=identity), data


def test_missing_values_shrink_n_and_are_listed_never_filled():
    stock = [float(i) for i in range(20)]
    flow: list[float | None] = [float((i * 7) % 5) for i in range(20)]
    flow[3] = None
    x = _quarterly(stock, MeasureType.STOCK, "quarter_end")
    y = _quarterly(flow, MeasureType.FLOW, "quarter_end_difference")
    result = _ok(TOOLS.correlate(*x, *y, *WINDOW, 0))
    assert result.result["pairs"].value == 19
    assert "pairs skipped for missing values: 2020-Q4" in result.notes


def test_a_constant_series_has_no_correlation():
    x = _quarterly([5.0] * 20, MeasureType.STOCK, "quarter_end")
    y = _quarterly([float(i) for i in range(20)], MeasureType.FLOW, "quarter_end_difference")
    _refused(TOOLS.correlate(*x, *y, *WINDOW, 0), RefusalCode.CONSTANT_SERIES)


# -- claims about a correlation ---------------------------------------------------------------------


def _association(
    computation, predicate="assoc.positive", field="pearson_r", kind=ClaimKind.ASSOCIATION, **kw
):
    a = Assertion(
        predicate=predicate,
        computation_id=computation.id,
        field=field,
        metric=computation.result[field].metric,
        series_key=computation.inputs[0].series_key,
        interval=computation.result[field].interval,
    ).model_copy(update=kw)
    return Claim(id="k1", kind=kind, text="{a1}.", assertions={"a1": a})


async def test_a_verified_association_names_both_series_the_lag_and_the_caveat(pair):
    (vac_src, vac), (emp_src, emp) = pair
    lag0 = _ok(TOOLS.correlate(vac_src, vac, emp_src, emp, *WINDOW, 0))
    claim = _association(lag0)
    assert verify_claim(claim, {lag0.id: lag0}).passed
    assert render_claim(claim, {lag0.id: lag0}) == (
        "Job vacancies in Information & Communications and employment change in Information & "
        "Communications in the same quarter tended to be higher together between 2020-Q1 and 2024-Q4 "
        "(Pearson r 0.47 over 20 quarters; exploratory, not evidence of cause)."
    )


@pytest.mark.parametrize(
    ("overrides", "failing"),
    [
        ({"predicate": "assoc.weak"}, "strength_rule"),  # r = 0.47 is not weak
        ({"predicate": "assoc.negative"}, "sign_rule"),
        ({"field": "pairs"}, "predicate_fit"),  # a count is not an association
        ({"predicate": "change.increase"}, "predicate_fit"),
        ({"kind": ClaimKind.COMPARISON}, "kind_allowed"),
    ],
)
async def test_association_claims_are_held_to_strength_sign_and_kind(pair, overrides, failing):
    (vac_src, vac), (emp_src, emp) = pair
    lag0 = _ok(TOOLS.correlate(vac_src, vac, emp_src, emp, *WINDOW, 0))
    claim = _association(lag0, **overrides)
    verdict = verify_claim(claim, {lag0.id: lag0})
    assert not verdict.passed and failing in {f.name for f in verdict.failures}


async def test_a_weak_correlation_can_only_be_described_as_little_association():
    x = _quarterly([float(i) for i in range(20)], MeasureType.STOCK, "quarter_end")
    y = _quarterly([1.0, -1.0] * 10, MeasureType.FLOW, "quarter_end_difference")
    weak = _ok(TOOLS.correlate(*x, *y, *WINDOW, 0))
    assert abs(weak.result["pearson_r"].value) < 0.3
    assert not verify_claim(_association(weak, predicate="assoc.negative"), {weak.id: weak}).passed
    assert verify_claim(_association(weak, predicate="assoc.weak"), {weak.id: weak}).passed
