from __future__ import annotations

import pytest

from app.analytics.results import Interval
from app.grounding.checks import check_free_text, verify_claim
from app.grounding.contracts import Assertion, Claim, ClaimKind
from app.grounding.render import render_claim
from tests.unit.test_analytics_tools import ICT_EMPLOYMENT, TOOLS, _ok, _series

SRC, DATA = _series(ICT_EMPLOYMENT)
CHANGE = _ok(TOOLS.change_between(SRC, DATA, "2020", "2024"))
CAGR = _ok(TOOLS.cagr(SRC, DATA, "2020", "2024"))
LEVEL = _ok(TOOLS.value_at(SRC, DATA, "2024"))
COMPUTATIONS = {c.id: c for c in (CHANGE, CAGR, LEVEL)}
KEY = SRC.series_key


def _assertion(**overrides) -> Assertion:
    base = dict(
        predicate="change.increase",
        computation_id=CHANGE.id,
        field="pct_change",
        metric="employment_level",
        series_key=KEY,
        interval=Interval(start="2020", end="2024"),
    )
    return Assertion(**{**base, **overrides})


def _claim(text="{a1}.", kind=ClaimKind.COMPARISON, **assertion_overrides) -> Claim:
    return Claim(id="k1", kind=kind, text=text, assertions={"a1": _assertion(**assertion_overrides)})


def _failed(claim: Claim) -> set[str]:
    verdict = verify_claim(claim, COMPUTATIONS)
    return {c.name for c in verdict.failures}


def test_valid_claim_passes_and_is_rendered_from_the_computation():
    claim = _claim(text="Over the period, {a1}.")
    assert verify_claim(claim, COMPUTATIONS).passed
    assert render_claim(claim, COMPUTATIONS) == (
        "Over the period, employment level in Information & Communications "
        "rose by 14.4% between 2020 and 2024."
    )


def test_level_value_is_rendered_in_source_units():
    claim = Claim(
        id="k2",
        kind=ClaimKind.MEASURED,
        text="{a1}.",
        assertions={
            "a1": _assertion(
                predicate="level.at",
                computation_id=LEVEL.id,
                field="value",
                interval=Interval(start="2024", end="2024"),
            )
        },
    )
    assert verify_claim(claim, COMPUTATIONS).passed
    assert render_claim(claim, COMPUTATIONS).endswith("was 180.3 thousand persons in 2024.")


@pytest.mark.parametrize(
    ("overrides", "failing_check"),
    [
        ({"metric": "job_vacancies"}, "metric_equality"),
        ({"interval": Interval(start="2023", end="2024")}, "interval_equality"),
        ({"field": "end_value"}, "predicate_fit"),  # a level presented as a change
        ({"predicate": "change.decrease"}, "sign_rule"),
        ({"series_key": "M184071:1.2.4.2@SSIC2020"}, "identity_equality"),  # child series swapped in
        ({"computation_id": "c00000000"}, "resolution"),
        ({"predicate": "trend.upward"}, "predicate_fit"),
    ],
)
def test_each_corruption_is_caught_by_its_check(overrides, failing_check):
    assert failing_check in _failed(_claim(**overrides))


@pytest.mark.parametrize(
    "text",
    [
        "{a1}, an increase of 14.4%.",  # fabricated literal
        "{a1}, about 23 thousand more workers.",
        "{a1}, which may have been due to remote work.",  # hedged causal wording still fails
        "Digitalisation drove the change: {a1}.",
    ],
)
def test_prose_cannot_add_numbers_or_causal_claims(text):
    assert _failed(_claim(text=text)) & {"no_free_numbers", "no_causal_language"}


def test_years_in_prose_must_match_asserted_periods():
    assert verify_claim(_claim(text="From 2020 to 2024, {a1}."), COMPUTATIONS).passed
    assert "no_free_numbers" in _failed(_claim(text="Since 2019, {a1}."))


def test_the_year_of_an_asserted_quarter_may_be_written_alone():
    assert all(c.passed for c in check_free_text("in the fourth quarter of 2024", {"2024-Q4"}))
    assert not all(c.passed for c in check_free_text("in the fourth quarter of 2023", {"2024-Q4"}))


def test_period_tokens_are_scanned_whole():
    assert all(c.passed for c in check_free_text("between 2020-Q1 and 2024-Q4", {"2020-Q1", "2024-Q4"}))


def test_association_needs_association_evidence():
    assert "kind_allowed" in _failed(_claim(kind=ClaimKind.ASSOCIATION))


def test_recommendations_cannot_carry_figures_and_findings_need_evidence():
    assert "recommendation_has_no_figures" in _failed(_claim(kind=ClaimKind.RECOMMENDATION))
    no_evidence = Claim(id="k3", kind=ClaimKind.MEASURED, text="Employment grew strongly.")
    assert "finding_has_evidence" in _failed(no_evidence)
    limitation = Claim(
        id="k4", kind=ClaimKind.LIMITATION, text="Quarterly employment levels are not published."
    )
    assert verify_claim(limitation, COMPUTATIONS).passed


def test_text_slots_must_match_assertions():
    assert "slots_bound" in _failed(_claim(text="{a1} and {a2}."))


def test_citations_come_from_computation_lineage():
    from app.data.models import NormalizedDataset, Provenance
    from app.grounding.citations import CitationIndex, claim_refs

    prov = Provenance(
        platform="singstat",
        publisher="DOS",
        origin_agency="MOM",
        dataset_id="M182841",
        title="Employment",
        url_human="https://example.test/M182841",
        url_api=[],
        retrieved_at="2026-10-25T00:00:00Z",
        source_updated_at=None,
        from_snapshot=True,
        raw_sha256=[],
    )
    dataset = NormalizedDataset(
        artifact_id="a1", dataset_id="M182841", provenance=prov, series=[DATA], taxonomy_version="test"
    )
    index = CitationIndex({"a1": dataset})
    assert index.cite(claim_refs(_claim(), COMPUTATIONS)) == ["S1"]
    (citation,) = index.citations()
    assert citation.dataset_id == "M182841" and citation.periods == ["2020", "2024"]
