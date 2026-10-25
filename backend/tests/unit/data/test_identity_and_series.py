from __future__ import annotations

from app.connectors.catalog import get_catalog
from app.data.identity import Incompatibility, same_measure_incompatibility
from app.data.models import MarkerCode
from app.data.series import build_series, flag_ambiguous_sectors
from app.data.taxonomy import get_taxonomy, normalise_label

CATALOG = get_catalog()
TAXONOMY = get_taxonomy()
M182841 = CATALOG.get("M182841")
VACANCIES_Q = CATALOG.get("M184071")
SINGSTAT = CATALOG.platforms["singstat"]
MOM = CATALOG.platforms["mom"]


def _one(entry, label, points, platform=SINGSTAT, ref="x"):
    series, issues = build_series(entry, platform, TAXONOMY, source_ref=ref, label=label, points=points)
    return series, {i.code: i for i in issues}


def test_label_variants_across_sources_resolve_to_one_sector():
    labels = [
        "Information And Communications",
        "Information & Communications",
        "information and communications",
    ]
    assert {TAXONOMY.resolve("SSIC2020", lab).key for lab in labels} == {"info_comms"}
    assert normalise_label("Paper Products & Publishing^") == "paper products and publishing"


def test_parent_and_child_sectors_stay_distinct():
    parent = TAXONOMY.resolve("SSIC2020", "Information And Communications")
    child = TAXONOMY.resolve("SSIC2020", "IT & Other Information Services")
    assert parent.key != child.key and child.parent == parent.key
    (p,), _ = _one(VACANCIES_Q, "Information And Communications", [("2024 1Q", "7300")])
    (c,), _ = _one(VACANCIES_Q, "IT & Other Information Services", [("2024 1Q", "6000")])
    assert same_measure_incompatibility(p.identity, c.identity) is Incompatibility.INCOMPATIBLE_IDENTITY


def test_same_letter_under_another_scheme_is_a_different_classification():
    (s2020,), _ = _one(VACANCIES_Q, "Information And Communications", [("2024 1Q", "7300")])
    other = s2020.identity.model_copy(update={"scheme": "SSIC2025"})
    assert same_measure_incompatibility(s2020.identity, other) is Incompatibility.CLASSIFICATION_MISMATCH


def test_scale_difference_alone_is_compatible():
    (s,), _ = _one(VACANCIES_Q, "Information And Communications", [("2024 1Q", "7300")])
    assert same_measure_incompatibility(s.identity, s.identity.model_copy(update={"scale": 1000})) is None


def test_series_splits_by_classification_regime():
    series, _ = _one(
        M182841, "Information And Communications", [("2006", "100"), ("2007", "101"), ("2008", "102")]
    )
    by_scheme = {s.identity.scheme if s.identity else s.key.split("@")[1]: s for s in series}
    assert [o.period for o in by_scheme["SSIC2020"].observations] == ["2008"]
    assert by_scheme["SSIC2005"].identity is None  # no SSIC 2005 taxonomy: unidentified, not guessed
    assert "SSIC2005" in by_scheme["SSIC2005"].unidentified_reason


def test_markers_are_nulled_with_source_meaning_and_never_zero():
    (s,), issues = _one(M182841, "Information And Communications", [("2020", "-"), ("2021", "n.a.")])
    assert [o.value for o in s.observations] == [None, None]
    assert {o.marker for o in s.observations} == {MarkerCode.UNKNOWN}
    assert issues["UNLISTED_MARKER"].count == 1  # "n.a." is not in SingStat's legend
    (m,), _ = _one(M182841, "Information And Communications", [("2020", "-")], platform=MOM)
    assert m.observations[0].marker is MarkerCode.NIL_OR_NEGLIGIBLE


def test_conflicting_duplicate_periods_are_errors_and_first_value_kept():
    (s,), issues = _one(M182841, "Information And Communications", [("2020", "157.6"), ("2020", "999")])
    assert [o.value for o in s.observations] == [157.6]
    assert issues["CONFLICTING_DUPLICATE"].severity == "error"


def test_skipped_observations_are_aggregated_per_series():
    _, issues = _one(
        VACANCIES_Q, "Information And Communications", [("1985 1Q", "1"), ("1985 2Q", "2"), ("2024", "3")]
    )
    assert issues["OUTSIDE_CLASSIFICATION_COVERAGE"].count == 2
    assert issues["FREQUENCY_MISMATCH"].count == 1


def test_two_rows_mapping_to_one_identity_are_both_refused():
    a, _ = _one(VACANCIES_Q, "Information And Communications", [("2024 1Q", "1")], ref="1.2.4")
    b, _ = _one(VACANCIES_Q, "Information & Communications", [("2024 1Q", "2")], ref="9.9")
    series = a + b
    issues = flag_ambiguous_sectors(series)
    assert [i.code for i in issues] == ["AMBIGUOUS_SECTOR"]
    assert all(s.identity is None for s in series)
