"""Industry taxonomy: maps source labels to sectors without ever merging parent and child."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.core.config import get_settings

_WS = re.compile(r"\s+")
_FOOTNOTE_MARKS = re.compile(r"[\^*#]+$")


def normalise_label(label: str) -> str:
    """Lower-case, strip footnote marks, '&' -> 'and', collapse whitespace."""
    text = _FOOTNOTE_MARKS.sub("", label.strip()).lower().replace("&", " and ")
    return _WS.sub(" ", text).strip()


def normalise_code(code: str) -> str:
    return re.sub(r"\s+", "", code).upper()


@dataclass(frozen=True)
class Sector:
    scheme: str
    key: str
    label: str
    code: str | None
    parent: str | None
    # SSIC code ranges sources state for this sector (e.g. MOM's "J58-63"); empty if none recorded.
    source_codes: tuple[str, ...] = ()

    def contradicts(self, stated_code: str | None) -> bool:
        """True when a source states a code for this label that belongs to another sector, e.g.
        a row labelled with the parent's name but coded as one of its children."""
        if not stated_code or not self.source_codes:
            return False
        return normalise_code(stated_code) not in self.source_codes


class Taxonomy:
    def __init__(self, raw: dict, version: str) -> None:
        self.version = version
        self._sectors: dict[tuple[str, str], Sector] = {}
        self._by_alias: dict[tuple[str, str], Sector] = {}
        for scheme, sectors in raw["schemes"].items():
            for key, spec in sectors.items():
                codes = tuple(normalise_code(c) for c in spec.get("source_codes", []))
                sector = Sector(scheme, key, spec["label"], spec.get("code"), spec.get("parent"), codes)
                self._sectors[(scheme, key)] = sector
                for alias in [spec["label"], *spec.get("aliases", [])]:
                    self._by_alias[(scheme, normalise_label(alias))] = sector

    @classmethod
    def load(cls, path: Path) -> Taxonomy:
        text = path.read_bytes()
        return cls(yaml.safe_load(text), version=hashlib.sha256(text).hexdigest()[:12])

    def resolve(self, scheme: str, label: str) -> Sector | None:
        return self._by_alias.get((scheme, normalise_label(label)))

    def sector(self, scheme: str, key: str) -> Sector | None:
        return self._sectors.get((scheme, key))

    def sectors(self, scheme: str) -> list[Sector]:
        return [s for (sch, _), s in self._sectors.items() if sch == scheme]


@lru_cache
def get_taxonomy() -> Taxonomy:
    return Taxonomy.load(get_settings().data_dir / "taxonomy.yaml")
