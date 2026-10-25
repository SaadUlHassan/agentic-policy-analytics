"""Deterministic rendering of numbers and claims. The only place report numbers are written."""

from __future__ import annotations

from app.analytics.results import Computation, ResultField, ValueKind
from app.grounding.contracts import Assertion, Claim
from app.grounding.predicates import PREDICATES

DISPLAY_ROUNDING_VERSION = "1"

_SCALE_WORDS = {1000: "thousand"}
_PER_YEAR = "_per_year"


def format_field(field: ResultField, *, magnitude: bool = False) -> str:
    """Render a value in its source unit. `magnitude` drops the sign (predicates say rose/fell)."""
    value = abs(field.value) if magnitude else field.value
    unit, per_year = field.unit, ""
    if unit.endswith(_PER_YEAR):
        unit, per_year = unit.removesuffix(_PER_YEAR), " a year"
    if unit == "percent":
        return f"{value:.1f}%{per_year}"
    if unit == "percentage_points":
        return f"{value:.1f} percentage points{per_year}"
    signed = field.value_kind in (ValueKind.FLOW, ValueKind.TOTAL) and not magnitude
    if field.scale in _SCALE_WORDS:
        number = f"{value:+,.1f}" if signed else f"{value:,.1f}"
        return f"{number} {_SCALE_WORDS[field.scale]} {unit}{per_year}"
    number = f"{value:+,.0f}" if signed else f"{value:,.0f}"
    return f"{number} {unit}{per_year}"


def render_assertion(assertion: Assertion, computation: Computation) -> str:
    predicate = PREDICATES[assertion.predicate]
    field = computation.result[assertion.field]
    subject = computation.inputs[0].identity.subject()
    values = {
        # Lower-case so the assertion reads naturally mid-sentence; render_claim capitalises the start.
        "subject": subject[:1].lower() + subject[1:],
        "value": format_field(field, magnitude=predicate.sign is not None),
        "t0": field.interval.start,
        "t1": field.interval.end,
        **{
            k: computation.params.get(f"{w}_{e}", "")
            for k, w, e in (
                ("a0", "a", "start"),
                ("a1", "a", "end"),
                ("b0", "b", "start"),
                ("b1", "b", "end"),
            )
        },
    }
    return predicate.template.format(**values)


def render_claim(claim: Claim, computations: dict[str, Computation]) -> str:
    slots = {
        slot: render_assertion(a, computations[a.computation_id]) for slot, a in claim.assertions.items()
    }
    text = claim.text.format(**slots) if slots else claim.text
    return text[:1].upper() + text[1:]
