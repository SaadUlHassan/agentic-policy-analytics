"""Series identity and the rules for when two series may be compared or combined (plan §4.3)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.data.periods import Frequency


class MeasureType(StrEnum):
    STOCK = "stock"
    FLOW = "flow"
    RATE = "rate"


class SeriesIdentity(BaseModel):
    """What one series measures. Two series are the same evidence only if every field matches."""

    model_config = ConfigDict(frozen=True)

    scheme: str
    sector: str
    sector_label: str
    sector_code: str | None
    metric: str
    measure_type: MeasureType
    reference_convention: str
    population: str
    frequency: Frequency
    unit: str
    scale: int

    def subject(self) -> str:
        """Human-readable subject for rendered claims, e.g. 'Employment level in Information & ...'."""
        metric = self.metric.replace("_", " ")
        return f"{metric[0].upper()}{metric[1:]} in {self.sector_label}"


class Incompatibility(StrEnum):
    CLASSIFICATION_MISMATCH = "CLASSIFICATION_MISMATCH"
    INCOMPATIBLE_IDENTITY = "INCOMPATIBLE_IDENTITY"
    METRIC_MISMATCH = "METRIC_MISMATCH"
    FREQ_MISMATCH = "FREQ_MISMATCH"
    REFERENCE_MISMATCH = "REFERENCE_MISMATCH"
    POPULATION_MISMATCH = "POPULATION_MISMATCH"
    UNIT_MISMATCH = "UNIT_MISMATCH"


def same_measure_incompatibility(a: SeriesIdentity, b: SeriesIdentity) -> Incompatibility | None:
    """Reason two series cannot be treated as the same measurement, or None if they can.

    Sectors must match exactly: a parent and its child (e.g. Information & Communications vs
    IT & Other Information Services) are different sectors, and the same code letter under a
    different classification scheme is a different classification, not the same sector.
    Scale may differ (thousands vs persons) because it is a pure unit multiplier.
    """
    checks = (
        (a.scheme == b.scheme, Incompatibility.CLASSIFICATION_MISMATCH),
        (a.sector == b.sector, Incompatibility.INCOMPATIBLE_IDENTITY),
        (a.metric == b.metric and a.measure_type == b.measure_type, Incompatibility.METRIC_MISMATCH),
        (a.frequency == b.frequency, Incompatibility.FREQ_MISMATCH),
        (a.reference_convention == b.reference_convention, Incompatibility.REFERENCE_MISMATCH),
        (a.population == b.population, Incompatibility.POPULATION_MISMATCH),
        (a.unit == b.unit, Incompatibility.UNIT_MISMATCH),
    )
    return next((reason for ok, reason in checks if not ok), None)
