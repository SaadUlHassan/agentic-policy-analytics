"""The only prose a finding may contain besides its rendered statements.

Free connective text can negate or reframe a correctly rendered statement ("It is false that ...").
So a finding is exactly: an allow-listed neutral lead-in, then its statements joined by "and".
"""

from __future__ import annotations

from typing import Literal, get_args

LeadIn = Literal[
    "",
    "Over the same period,",
    "Meanwhile,",
    "By comparison,",
    "In contrast,",
    "Separately,",
    "In addition,",
    "Overall,",
]
LEAD_INS: tuple[str, ...] = get_args(LeadIn)


def compose_text(lead_in: str, slots: list[str]) -> str:
    """Claim template: the lead-in, then the rendered statements joined into one sentence."""
    statements = " and ".join("{" + s + "}" for s in slots)
    return " ".join(part for part in (lead_in, statements) if part) + "."


def is_composed(text: str, slots: list[str]) -> bool:
    """True when `text` is exactly an allow-listed lead-in followed by the statements, in order."""
    return any(text == compose_text(lead_in, slots) for lead_in in LEAD_INS)
