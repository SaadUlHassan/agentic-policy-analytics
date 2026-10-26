"""Adversarial verifier suite (plan §8.3, G3).

Valid controls and deliberately corrupted claims, all bound to real computations on the golden
series. Every corruption breaks one rule a fabricated or careless finding could break (wrong number,
wrong metric, shorter interval, wrong direction, causal wording, swapped identity...). The gate is
100% recall per deterministic category, with at most 5% of valid controls wrongly rejected.

Unsupported narrative additions without numbers or causal words are a qualitative category: they
need the LLM judge and are measured in the live evaluation, not here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.analytics.results import Computation, Interval
from app.analytics.tools import Toolkit
from app.data.taxonomy import get_taxonomy
from app.evaluation.accuracy import Series, run_spec
from app.evaluation.golden import golden
from app.grounding.checks import check_free_text, verify_claim
from app.grounding.contracts import Assertion, Claim, ClaimKind
from app.grounding.prose import compose_text

CONTROL = "valid_control"
NARRATIVE_CONTROL = "valid_narrative"
MAX_FALSE_POSITIVE_RATE = 0.05

# The rule each corruption breaks. A case counts as detected only when that rule rejected it: a
# rejection for some other reason would hide a broken check behind a green gate.
EXPECTED_CHECK = {
    "wrong_computation_ref": "resolution",
    "wrong_metric": "metric_equality",
    "shorter_interval": "interval_equality",
    "longer_interval": "interval_equality",
    "level_as_change": "predicate_fit",
    "wrong_unit_or_field": "predicate_fit",
    "wrong_direction": "sign_rule",
    "association_strength": "strength_rule",
    "association_from_descriptive": "kind_allowed",
    "fabricated_literal": "no_free_numbers",
    "causal_unhedged": "no_causal_language",
    "causal_hedged": "no_causal_language",
    "tampered_lineage": "identity_equality",
    "parent_child_swap": "identity_equality",
    "recommendation_with_figures": "recommendation_has_no_figures",
    "narrative_fabricated_number": "no_free_numbers",
    "narrative_causal": "no_causal_language",
}


@dataclass(frozen=True)
class Case:
    category: str
    description: str
    claim: Claim | None = None
    narrative: str | None = None
    allowed_periods: frozenset[str] = frozenset()

    @property
    def valid(self) -> bool:
        return self.category in (CONTROL, NARRATIVE_CONTROL)


@dataclass
class Outcome:
    case: Case
    rejected: bool
    failed_checks: list[str] = field(default_factory=list)


def _computations(series: Series) -> dict[str, Computation]:
    toolkit = Toolkit(get_taxonomy().version)
    out = {}
    for cid, spec in golden()["computations"].items():
        result = run_spec(toolkit, spec, series)
        assert isinstance(result, Computation), f"golden computation {cid} was refused: {result}"
        out[cid] = result
    for cid, name, period in (
        ("V_EMP_2024", "ict_employment_level", "2024"),
        ("V_FLOW", "ict_employment_change", "2024-Q4"),
    ):
        result = toolkit.value_at(*series[name], period)
        assert isinstance(result, Computation)
        out[cid] = result
    return out


def _assertion(c: Computation, name: str, predicate: str, **override: Any) -> Assertion:
    """An assertion bound exactly as a correct draft would bind `name`; `override` corrupts it."""
    f = c.result[name]
    base: dict[str, Any] = {
        "predicate": predicate,
        "computation_id": c.id,
        "field": name,
        "metric": f.metric,
        "series_key": c.inputs[0].series_key,
        "interval": f.interval,
    }
    return Assertion(**{**base, **override})


def _claim(
    *assertions: Assertion, kind: ClaimKind = ClaimKind.COMPARISON, lead_in: str = "", text: str | None = None
) -> Claim:
    slots = [f"a{i}" for i in range(1, len(assertions) + 1)]
    return Claim(
        id="k",
        kind=kind,
        text=text if text is not None else compose_text(lead_in, slots),
        assertions=dict(zip(slots, assertions, strict=True)),
    )


def build_cases(series: Series) -> tuple[list[Case], dict[str, Computation]]:
    c = _computations(series)
    a = _assertion
    measured, assoc = ClaimKind.MEASURED, ClaimKind.ASSOCIATION
    ict, it_services = (
        golden()["series"]["ict_vacancies"]["key"],
        golden()["series"]["it_services_vacancies"]["key"],
    )
    mirror = "d_3f17bbf67d31d4d402caa8755eb74afc:information and communications@SSIC2020"
    cases: list[Case] = []

    def add(category: str, description: str, claim: Claim) -> None:
        cases.append(Case(category, description, claim=claim))

    # -- valid controls: what a correct analysis drafts ----------------------------------------
    for description, claim in [
        ("employment rose by %, 2020-2024", _claim(a(c["C01"], "pct_change", "change.increase"))),
        ("employment rose by persons, 2020-2024", _claim(a(c["C01"], "abs_change", "change.increase"))),
        ("employment compound growth", _claim(a(c["C02"], "cagr_pct", "cagr.growth"))),
        ("employment trend upward", _claim(a(c["C03"], "slope", "trend.upward"))),
        ("employment level in 2024", _claim(a(c["V_EMP_2024"], "value", "level.at"), kind=measured)),
        ("employment fell 2022 to 2023 (persons)", _claim(a(c["C04"], "abs_change", "change.decrease"))),
        ("employment fell 2022 to 2023 (%)", _claim(a(c["C04"], "pct_change", "change.decrease"))),
        ("net employment change total", _claim(a(c["C05"], "total", "flow.total"))),
        ("later window averaged less", _claim(a(c["C06"], "difference", "period.lower"))),
        ("vacancies rose (count)", _claim(a(c["C07"], "abs_change", "change.increase"))),
        ("vacancies rose (%)", _claim(a(c["C07"], "pct_change", "change.increase"))),
        ("IT subsector vacancies rose (%)", _claim(a(c["C08"], "pct_change", "change.increase"))),
        ("vacancies trend upward", _claim(a(c["C09"], "slope", "trend.upward"))),
        ("vacancies x hiring, lag 0", _claim(a(c["C10"], "pearson_r", "assoc.positive"), kind=assoc)),
        ("vacancies x hiring, lag 1", _claim(a(c["C11"], "pearson_r", "assoc.positive"), kind=assoc)),
        (
            "vacancies x hiring, lag 1, rank",
            _claim(a(c["C11"], "spearman_rho", "assoc.positive"), kind=assoc),
        ),
        ("vacancies compound growth", _claim(a(c["C12"], "cagr_pct", "cagr.growth"))),
        (
            "two statements with a lead-in",
            _claim(
                a(c["C01"], "abs_change", "change.increase"),
                a(c["C02"], "cagr_pct", "cagr.growth"),
                lead_in="Over the same period,",
            ),
        ),
        (
            "lead-in and a level",
            _claim(a(c["V_EMP_2024"], "value", "level.at"), kind=measured, lead_in="Meanwhile,"),
        ),
        ("one quarter's net change", _claim(a(c["V_FLOW"], "value", "flow.at"), kind=measured)),
    ]:
        add(CONTROL, description, claim)
    for text, periods in [
        ("Employment in information and communications grew over the period reviewed.", set()),
        ("The findings cover 2020 to 2024.", {"2020", "2024"}),
        (
            "Vacancies and net hiring tended to move together, which is an association rather than a cause.",
            set(),
        ),
        ("Gains were stronger in the earlier part of the period.", set()),
        ("The fourth quarter of 2024 is the last period covered.", {"2024-Q4"}),
    ]:
        cases.append(Case(NARRATIVE_CONTROL, text, narrative=text, allowed_periods=frozenset(periods)))

    # -- corruptions ------------------------------------------------------------------------------
    corrupt = [
        (
            "wrong_computation_ref",
            "unknown computation",
            _claim(a(c["C01"], "pct_change", "change.increase", computation_id="cdeadbeef")),
        ),
        (
            "wrong_computation_ref",
            "field the computation does not have",
            _claim(a(c["C01"], "pct_change", "change.increase", field="cagr_pct")),
        ),
        (
            "wrong_computation_ref",
            "another computation's field",
            _claim(a(c["C02"], "cagr_pct", "cagr.growth", computation_id=c["C01"].id)),
        ),
        (
            "wrong_metric",
            "vacancies claimed for employment",
            _claim(a(c["C01"], "pct_change", "change.increase", metric="job_vacancies")),
        ),
        (
            "wrong_metric",
            "change claimed for a level",
            _claim(a(c["C02"], "cagr_pct", "cagr.growth", metric="employment_change")),
        ),
        (
            "wrong_metric",
            "association metric swapped",
            _claim(a(c["C10"], "pearson_r", "assoc.positive", metric="job_vacancies"), kind=assoc),
        ),
        (
            "shorter_interval",
            "5-year change restated for 2021-2024",
            _claim(a(c["C01"], "pct_change", "change.increase", interval=Interval(start="2021", end="2024"))),
        ),
        (
            "shorter_interval",
            "vacancy change restated from 2021-Q1",
            _claim(
                a(
                    c["C07"],
                    "pct_change",
                    "change.increase",
                    interval=Interval(start="2021-Q1", end="2024-Q4"),
                )
            ),
        ),
        (
            "shorter_interval",
            "correlation restated for a shorter window",
            _claim(
                a(c["C10"], "pearson_r", "assoc.positive", interval=Interval(start="2021-Q1", end="2024-Q4")),
                kind=assoc,
            ),
        ),
        (
            "longer_interval",
            "change extended back to 2019",
            _claim(a(c["C01"], "abs_change", "change.increase", interval=Interval(start="2019", end="2024"))),
        ),
        (
            "longer_interval",
            "total extended back to 2019-Q1",
            _claim(a(c["C05"], "total", "flow.total", interval=Interval(start="2019-Q1", end="2024-Q4"))),
        ),
        (
            "longer_interval",
            "growth rate claimed for a decade",
            _claim(a(c["C02"], "cagr_pct", "cagr.growth", interval=Interval(start="2014", end="2024"))),
        ),
        (
            "level_as_change",
            "a level stated as a rise",
            _claim(a(c["V_EMP_2024"], "value", "change.increase")),
        ),
        (
            "level_as_change",
            "an endpoint level stated as a rise",
            _claim(a(c["C01"], "end_value", "change.increase")),
        ),
        (
            "level_as_change",
            "a quarter's flow stated as a total",
            _claim(a(c["V_FLOW"], "value", "flow.total")),
        ),
        (
            "wrong_unit_or_field",
            "a % change stated as compound growth",
            _claim(a(c["C01"], "pct_change", "cagr.growth")),
        ),
        (
            "wrong_unit_or_field",
            "a growth rate stated as a rise",
            _claim(a(c["C02"], "cagr_pct", "change.increase")),
        ),
        (
            "wrong_unit_or_field",
            "an absolute change stated as a trend",
            _claim(a(c["C01"], "abs_change", "trend.upward")),
        ),
        (
            "wrong_unit_or_field",
            "a pair count stated as an association",
            _claim(a(c["C10"], "pairs", "assoc.positive"), kind=assoc),
        ),
        ("wrong_direction", "a rise stated as a fall", _claim(a(c["C01"], "pct_change", "change.decrease"))),
        (
            "wrong_direction",
            "an upward trend stated as downward",
            _claim(a(c["C03"], "slope", "trend.downward")),
        ),
        (
            "wrong_direction",
            "a lower average stated as higher",
            _claim(a(c["C06"], "difference", "period.higher")),
        ),
        (
            "wrong_direction",
            "a positive correlation stated as negative",
            _claim(a(c["C10"], "pearson_r", "assoc.negative"), kind=assoc),
        ),
        ("wrong_direction", "growth stated as decline", _claim(a(c["C02"], "cagr_pct", "cagr.decline"))),
        (
            "association_strength",
            "a moderate correlation called weak",
            _claim(a(c["C10"], "pearson_r", "assoc.weak"), kind=assoc),
        ),
        (
            "association_strength",
            "a lag-1 correlation called weak",
            _claim(a(c["C11"], "pearson_r", "assoc.weak"), kind=assoc),
        ),
        (
            "association_from_descriptive",
            "an association drawn from a change",
            _claim(a(c["C01"], "pct_change", "change.increase"), kind=assoc),
        ),
        (
            "association_from_descriptive",
            "an association labelled a comparison",
            _claim(a(c["C10"], "pearson_r", "assoc.positive")),
        ),
        (
            "fabricated_literal",
            "a number in the lead-in",
            _claim(
                a(c["C01"], "abs_change", "change.increase"),
                text="In 2023 about 25,000 more people worked in tech, and {a1}.",
            ),
        ),
        (
            "fabricated_literal",
            "a percentage appended",
            _claim(a(c["C07"], "pct_change", "change.increase"), text="{a1} (about 15%)."),
        ),
        (
            "fabricated_literal",
            "an unbound year",
            _claim(a(c["C02"], "cagr_pct", "cagr.growth"), text="Since 2015, {a1}."),
        ),
        (
            "causal_unhedged",
            "due to",
            _claim(
                a(c["C07"], "pct_change", "change.increase"), text="{a1} due to rising demand for software."
            ),
        ),
        (
            "causal_unhedged",
            "led to",
            _claim(a(c["C05"], "total", "flow.total"), text="Strong hiring led to the result that {a1}."),
        ),
        (
            "causal_hedged",
            "possibly because of",
            _claim(
                a(c["C01"], "pct_change", "change.increase"), text="{a1}, possibly because of digitalisation."
            ),
        ),
        (
            "causal_hedged",
            "likely driven by",
            _claim(a(c["C09"], "slope", "trend.upward"), text="{a1}, likely driven by investment in AI."),
        ),
        (
            "tampered_lineage",
            "the Data.gov.sg mirror's key on a SingStat result",
            _claim(a(c["C07"], "pct_change", "change.increase", series_key=mirror)),
        ),
        (
            "tampered_lineage",
            "another series' key",
            _claim(
                a(
                    c["C01"],
                    "pct_change",
                    "change.increase",
                    series_key=golden()["series"]["ict_employment_change"]["key"],
                )
            ),
        ),
        (
            "parent_child_swap",
            "subsector result claimed for the whole sector",
            _claim(a(c["C08"], "pct_change", "change.increase", series_key=ict)),
        ),
        (
            "parent_child_swap",
            "sector result claimed for the subsector",
            _claim(a(c["C07"], "pct_change", "change.increase", series_key=it_services)),
        ),
        (
            "recommendation_with_figures",
            "a recommendation carrying a value",
            _claim(a(c["C07"], "pct_change", "change.increase"), kind=ClaimKind.RECOMMENDATION),
        ),
    ]
    for category, description, claim in corrupt:
        add(category, description, claim)
    for category, text, periods in [
        ("narrative_fabricated_number", "Employment rose by about 23,000 jobs.", set()),
        ("narrative_fabricated_number", "Vacancies peaked in 2022.", {"2020", "2024"}),
        ("narrative_causal", "Hiring rose because of strong demand for software.", set()),
        ("narrative_causal", "The decline was likely due to layoffs in technology firms.", set()),
    ]:
        cases.append(Case(category, text, narrative=text, allowed_periods=frozenset(periods)))
    # Claims resolve by computation id, as in an analysis.
    return cases, {comp.id: comp for comp in c.values()}


def evaluate(cases: list[Case], computations: dict[str, Computation]) -> list[Outcome]:
    out = []
    for case in cases:
        if case.claim is not None:
            verdict = verify_claim(case.claim, computations)
            out.append(Outcome(case, not verdict.passed, [f.name for f in verdict.failures]))
        else:
            assert case.narrative is not None
            failed = [
                r.name for r in check_free_text(case.narrative, set(case.allowed_periods)) if not r.passed
            ]
            out.append(Outcome(case, bool(failed), failed))
    return out


def _detected(outcome: Outcome) -> bool:
    return EXPECTED_CHECK[outcome.case.category] in outcome.failed_checks


def summarise(outcomes: list[Outcome]) -> dict[str, Any]:
    by_category: dict[str, list[Outcome]] = defaultdict(list)
    for o in outcomes:
        by_category[o.case.category].append(o)
    categories = {}
    for category, items in sorted(by_category.items()):
        if items[0].case.valid:
            continue
        rule = EXPECTED_CHECK[category]
        detected = sum(_detected(o) for o in items)
        categories[category] = {
            "cases": len(items),
            "detected": detected,
            "recall": detected / len(items),
            "expected_check": rule,
            "checks_fired": sorted({check for o in items for check in o.failed_checks}),
            "misattributed": [
                {"case": o.case.description, "failed_checks": o.failed_checks}
                for o in items
                if o.rejected and not _detected(o)
            ],
        }
    controls = [o for o in outcomes if o.case.valid]
    false_positives = [o for o in controls if o.rejected]
    corrupted = [o for o in outcomes if not o.case.valid]
    return {
        "controls": len(controls),
        "corrupted": len(corrupted),
        "categories": categories,
        "recall": sum(_detected(o) for o in corrupted) / len(corrupted),
        "precision": sum(_detected(o) for o in corrupted) / max(1, sum(o.rejected for o in outcomes)),
        "false_positive_rate": len(false_positives) / len(controls),
        "false_positives": [
            {"case": o.case.description, "failed_checks": o.failed_checks} for o in false_positives
        ],
        "gate_passed": all(v["recall"] == 1.0 for v in categories.values())
        and len(false_positives) / len(controls) <= MAX_FALSE_POSITIVE_RATE,
    }
