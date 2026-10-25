"""Canonical reporting periods: annual "2024" and quarterly "2024-Q1"."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from functools import total_ordering


class Frequency(StrEnum):
    ANNUAL = "annual"
    QUARTERLY = "quarterly"


# SingStat writes quarters as "2024 1Q", data.gov.sg as "2024-Q1".
_QUARTER_PATTERNS = (re.compile(r"^(\d{4})\s*(\d)Q$"), re.compile(r"^(\d{4})-?Q(\d)$"))
_YEAR = re.compile(r"^(\d{4})$")


@total_ordering
@dataclass(frozen=True)
class Period:
    year: int
    quarter: int | None = None

    @classmethod
    def parse(cls, text: str) -> Period:
        text = text.strip().upper()
        if m := _YEAR.match(text):
            return cls(int(m.group(1)))
        for pattern in _QUARTER_PATTERNS:
            if (m := pattern.match(text)) and 1 <= int(m.group(2)) <= 4:
                return cls(int(m.group(1)), int(m.group(2)))
        raise ValueError(f"unrecognised period: {text!r}")

    @property
    def frequency(self) -> Frequency:
        return Frequency.ANNUAL if self.quarter is None else Frequency.QUARTERLY

    @property
    def start(self) -> date:
        return date(self.year, 1 if self.quarter is None else 3 * self.quarter - 2, 1)

    @property
    def ordinal(self) -> int:
        """Consecutive periods of the same frequency differ by exactly 1."""
        return self.year if self.quarter is None else self.year * 4 + self.quarter - 1

    def shift(self, steps: int) -> Period:
        if self.quarter is None:
            return Period(self.year + steps)
        index = self.ordinal + steps
        return Period(index // 4, index % 4 + 1)

    def same_period_prior_year(self) -> Period:
        return self.shift(-1 if self.quarter is None else -4)

    def __str__(self) -> str:
        return str(self.year) if self.quarter is None else f"{self.year}-Q{self.quarter}"

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Period):
            return NotImplemented
        if self.frequency != other.frequency:
            raise ValueError(f"cannot order {self} against {other}: different frequencies")
        return self.ordinal < other.ordinal


def years_between(start: Period, end: Period) -> float:
    """Elapsed time in years between period starts (2020 -> 2024 is 4.0, 2020-Q1 -> 2021-Q1 is 1.0)."""
    if start.frequency != end.frequency:
        raise ValueError("periods must share a frequency")
    per_year = 1 if start.quarter is None else 4
    return (end.ordinal - start.ordinal) / per_year
