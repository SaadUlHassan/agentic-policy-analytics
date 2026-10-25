from __future__ import annotations

import pytest

from app.data.periods import Frequency, Period, years_between


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2024", "2024"),
        ("2024 1Q", "2024-Q1"),
        ("2024-Q3", "2024-Q3"),
        ("2024Q4", "2024-Q4"),
        (" 2020 2q ", "2020-Q2"),
    ],
)
def test_source_formats_normalise_to_one_canonical_form(text, expected):
    assert str(Period.parse(text)) == expected


@pytest.mark.parametrize("text", ["2024-Q5", "24", "2024-13", "Q1 2024", ""])
def test_invalid_periods_are_rejected(text):
    with pytest.raises(ValueError):
        Period.parse(text)


def test_quarter_shift_crosses_year_boundary():
    assert Period.parse("2024-Q1").shift(-1) == Period.parse("2023-Q4")
    assert Period.parse("2023-Q4").shift(1) == Period.parse("2024-Q1")


def test_same_period_prior_year():
    assert Period.parse("2024-Q2").same_period_prior_year() == Period.parse("2023-Q2")
    assert Period.parse("2024").same_period_prior_year() == Period.parse("2023")


def test_years_between_uses_elapsed_time_not_point_count():
    assert years_between(Period.parse("2020"), Period.parse("2024")) == 4.0
    assert years_between(Period.parse("2020-Q1"), Period.parse("2021-Q1")) == 1.0


def test_mixed_frequencies_cannot_be_ordered():
    with pytest.raises(ValueError):
        _ = Period.parse("2024") < Period.parse("2024-Q1")
    assert Period.parse("2024-Q1").frequency is Frequency.QUARTERLY
