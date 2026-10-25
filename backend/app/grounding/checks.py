"""Deterministic claim checks (plan §3.6). Every retained claim passes all of them, whatever the
analysis status; a claim that fails is removed, never shown."""

from __future__ import annotations

import re
import string

from app.analytics.results import Computation, Interpretation
from app.grounding.contracts import Assertion, CheckResult, Claim, ClaimKind, ClaimVerdict
from app.grounding.predicates import PREDICATES

CAUSAL_TERMS = (
    "caused",
    "causes",
    "cause of",
    "led to",
    "leads to",
    "drove",
    "driven by",
    "due to",
    "because of",
    "resulted in",
    "result of",
    "impact of",
    "impacted",
    "attributable to",
)
_CAUSAL = re.compile(r"\b(" + "|".join(re.escape(t) for t in CAUSAL_TERMS) + r")\b", re.IGNORECASE)
# Periods first, so "2020-Q1" is one token rather than "2020" plus a stray "1".
_NUMBER = re.compile(r"\d{4}-Q[1-4]|\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|\d+(?:\.\d+)?%?")
_PERIOD = re.compile(r"^\d{4}(?:-Q[1-4])?$")
_KIND_NEEDS = {
    ClaimKind.ASSOCIATION: Interpretation.EXPLORATORY_ASSOCIATION,
    ClaimKind.PROJECTION: Interpretation.PROJECTION,
}


def _slots(text: str) -> list[str]:
    return [name for _, name, _, _ in string.Formatter().parse(text) if name]


def _check_assertion(
    slot: str, a: Assertion, claim: Claim, computations: dict[str, Computation]
) -> list[CheckResult]:
    label = f"[{slot}]"
    computation = computations.get(a.computation_id)
    if computation is None or a.field not in computation.result:
        return [
            CheckResult(
                name="resolution",
                passed=False,
                detail=f"{label} {a.computation_id}.{a.field} does not exist"
                + (f"; its fields are {sorted(computation.result)}" if computation else ""),
            )
        ]
    predicate = PREDICATES.get(a.predicate)
    if predicate is None:
        return [
            CheckResult(name="predicate_fit", passed=False, detail=f"{label} unknown predicate {a.predicate}")
        ]
    field = computation.result[a.field]
    value = field.value
    sign_ok = predicate.sign is None or (value > 0 if predicate.sign == "positive" else value < 0)
    needed = _KIND_NEEDS.get(claim.kind)
    return [
        CheckResult(name="resolution", passed=True),
        CheckResult(
            name="predicate_fit",
            passed=computation.tool in predicate.tools and field.value_kind in predicate.value_kinds,
            detail=f"{label} {a.predicate} cannot state {computation.tool}.{a.field} ({field.value_kind})",
        ),
        CheckResult(
            name="metric_equality",
            passed=a.metric == field.metric,
            detail=f"{label} claims metric {a.metric!r} but the value measures {field.metric!r}",
        ),
        CheckResult(
            name="identity_equality",
            passed=a.series_key == computation.inputs[0].series_key,
            detail=f"{label} claims {a.series_key!r}, value is from {computation.inputs[0].series_key!r}",
        ),
        CheckResult(
            name="interval_equality",
            passed=a.interval == field.interval,
            detail=f"{label} claims {a.interval.start}..{a.interval.end} but the value covers "
            f"{field.interval.start}..{field.interval.end}",
        ),
        CheckResult(
            name="sign_rule",
            passed=sign_ok,
            detail=f"{label} {a.predicate} needs a {predicate.sign} value, got {value:g}",
        ),
        CheckResult(
            name="kind_allowed",
            passed=claim.kind in predicate.claim_kinds
            and (needed is None or computation.interpretation_allowed is needed),
            detail=f"{label} a {claim.kind} claim cannot use {a.predicate} on a "
            f"{computation.interpretation_allowed} computation",
        ),
    ]


def check_free_text(text: str, allowed_periods: set[str]) -> list[CheckResult]:
    """Checks that apply to any prose shown to users: claims, narrative and caveats."""
    bare = string.Formatter().vformat(text, (), _BlankSlots())
    # A year may also be written on its own when it is the year of an asserted quarter
    # ("the fourth quarter of 2024" for 2024-Q4).
    allowed = allowed_periods | {p[:4] for p in allowed_periods}
    stray = [n for n in _NUMBER.findall(bare) if not (_PERIOD.match(n) and n in allowed)]
    causal = _CAUSAL.findall(bare)
    return [
        CheckResult(
            name="no_free_numbers", passed=not stray, detail=f"numbers not bound to evidence: {stray}"
        ),
        CheckResult(name="no_causal_language", passed=not causal, detail=f"causal wording: {causal}"),
    ]


class _BlankSlots(dict):
    def __missing__(self, key: str) -> str:
        return ""


def verify_claim(claim: Claim, computations: dict[str, Computation]) -> ClaimVerdict:
    checks: list[CheckResult] = []
    slots = _slots(claim.text)
    checks.append(
        CheckResult(
            name="slots_bound",
            passed=set(slots) == set(claim.assertions),
            detail=f"text slots {sorted(slots)} vs assertions {sorted(claim.assertions)}",
        )
    )
    if claim.kind is ClaimKind.RECOMMENDATION:
        checks.append(
            CheckResult(
                name="recommendation_has_no_figures",
                passed=not claim.assertions,
                detail="recommendations may not state measured values",
            )
        )
    elif claim.kind is not ClaimKind.LIMITATION and not claim.assertions:
        checks.append(
            CheckResult(
                name="finding_has_evidence",
                passed=False,
                detail=f"a {claim.kind} claim must bind at least one computed value",
            )
        )
    allowed_periods: set[str] = set()
    for slot, assertion in claim.assertions.items():
        checks.extend(_check_assertion(slot, assertion, claim, computations))
        allowed_periods |= {assertion.interval.start, assertion.interval.end}
    checks.extend(check_free_text(claim.text, allowed_periods))
    checks = [c if not c.passed else c.model_copy(update={"detail": ""}) for c in checks]
    return ClaimVerdict(claim_id=claim.id, passed=all(c.passed for c in checks), checks=checks)
