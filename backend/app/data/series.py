"""Turn raw (period, value) points from any connector into identified series with quality issues."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable

from app.connectors.catalog import DatasetEntry, PlatformInfo
from app.data.identity import SeriesIdentity
from app.data.models import MarkerCode, Observation, QualityIssue, SeriesData, Severity
from app.data.periods import Period
from app.data.taxonomy import Taxonomy

_SKIP_SEVERITY = {
    "UNPARSEABLE_PERIOD": Severity.WARNING,
    "FREQUENCY_MISMATCH": Severity.WARNING,
    "OUTSIDE_CLASSIFICATION_COVERAGE": Severity.INFO,
}
_SKIP_MESSAGES = {
    "UNPARSEABLE_PERIOD": "observations skipped: period text could not be parsed",
    "FREQUENCY_MISMATCH": "observations skipped: period frequency differs from the dataset's",
    "OUTSIDE_CLASSIFICATION_COVERAGE": "observations skipped: no documented industry classification",
}


def parse_value(raw: str, platform: PlatformInfo) -> tuple[float | None, MarkerCode | None, bool]:
    """Returns (value, marker, listed). `listed` is False for a non-numeric string the source
    legend does not define; it is still nulled, never guessed."""
    text = raw.strip().replace(",", "")
    try:
        return float(text), None, True
    except ValueError:
        pass
    spec = platform.markers.get(text)
    if spec is not None:
        return None, spec.code, True
    return None, MarkerCode.UNKNOWN, False


def build_series(
    entry: DatasetEntry,
    platform: PlatformInfo,
    taxonomy: Taxonomy,
    *,
    source_ref: str,
    label: str,
    points: Iterable[tuple[str, str]],
) -> tuple[list[SeriesData], list[QualityIssue]]:
    """Build one SeriesData per classification regime the points span.

    Splitting by regime keeps every series' identity constant: e.g. M182841 is SSIC 2005 before
    2008 and SSIC 2020 afterwards, and those are different classifications.
    """
    ref = f"{entry.id}:{source_ref}"
    by_regime: dict[str, list[Observation]] = defaultdict(list)
    seen: dict[str, str] = {}
    skipped: Counter[str] = Counter()
    conflicts: list[str] = []
    unlisted = 0

    for period_text, raw in points:
        try:
            period = Period.parse(period_text)
        except ValueError:
            skipped["UNPARSEABLE_PERIOD"] += 1
            continue
        if entry.frequency and period.frequency != entry.frequency:
            skipped["FREQUENCY_MISMATCH"] += 1
            continue
        key = str(period)
        if key in seen:
            if seen[key] != raw:
                conflicts.append(f"{key} ({seen[key]!r} vs {raw!r})")
            continue
        seen[key] = raw
        regime = entry.regime_for(period)
        if regime is None:
            skipped["OUTSIDE_CLASSIFICATION_COVERAGE"] += 1
            continue
        value, marker, listed = parse_value(raw, platform)
        unlisted += not listed
        by_regime[regime.scheme].append(Observation(period=key, value=value, marker=marker, raw=raw))

    issues = [
        QualityIssue(
            code=code, severity=_SKIP_SEVERITY[code], series_key=ref, count=n, message=_SKIP_MESSAGES[code]
        )
        for code, n in skipped.items()
    ]
    if conflicts:
        issues.append(
            QualityIssue(
                code="CONFLICTING_DUPLICATE",
                severity=Severity.ERROR,
                series_key=ref,
                count=len(conflicts),
                message="periods repeated with different values: " + ", ".join(conflicts[:5]),
            )
        )
    if unlisted:
        issues.append(
            QualityIssue(
                code="UNLISTED_MARKER",
                severity=Severity.WARNING,
                series_key=ref,
                count=unlisted,
                message="non-numeric values not defined by the source legend",
            )
        )

    series = []
    for scheme, observations in by_regime.items():
        observations.sort(key=lambda o: o.parsed_period.ordinal)
        key = f"{ref}@{scheme}"
        markers = sum(o.marker is not None for o in observations)
        if markers:
            issues.append(
                QualityIssue(
                    code="MISSING_OR_MARKED_VALUES",
                    severity=Severity.INFO,
                    series_key=key,
                    count=markers,
                    message="values carried a marker and were set to null",
                )
            )
        sector = taxonomy.resolve(scheme, label)
        identity, reason = None, None
        if sector is None:
            reason = f"label {label!r} has no {scheme} sector in the taxonomy"
        else:
            identity = _identity(entry, scheme, sector.key, sector.label, sector.code)
        series.append(
            SeriesData(
                key=key,
                label=label,
                source_ref=source_ref,
                identity=identity,
                unidentified_reason=reason,
                observations=observations,
            )
        )
    return series, issues


def _identity(
    entry: DatasetEntry, scheme: str, sector: str, sector_label: str, code: str | None
) -> SeriesIdentity:
    assert entry.metric and entry.measure_type and entry.reference_convention
    assert entry.population and entry.frequency and entry.unit
    return SeriesIdentity(
        scheme=scheme,
        sector=sector,
        sector_label=sector_label,
        sector_code=code,
        metric=entry.metric,
        measure_type=entry.measure_type,
        reference_convention=entry.reference_convention,
        population=entry.population,
        frequency=entry.frequency,
        unit=entry.unit,
        scale=entry.scale,
    )


def flag_ambiguous_sectors(series: list[SeriesData]) -> list[QualityIssue]:
    """Two source rows resolving to the same identity would be indistinguishable evidence;
    unidentify both rather than pick one silently."""
    groups: dict[SeriesIdentity, list[SeriesData]] = defaultdict(list)
    for s in series:
        if s.identity is not None:
            groups[s.identity].append(s)
    issues = []
    for identity, members in groups.items():
        if len(members) > 1:
            refs = ", ".join(m.source_ref for m in members)
            for m in members:
                m.identity, m.unidentified_reason = None, f"ambiguous: rows {refs} map to {identity.sector}"
            issues.append(
                QualityIssue(
                    code="AMBIGUOUS_SECTOR",
                    severity=Severity.WARNING,
                    message=f"rows {refs} all map to {identity.sector}; none used",
                )
            )
    return issues
