"""Amount parsing and formatting with JavaScript number semantics.

Amounts arrive as strings and are read the way JavaScript's ``Number()``
reads them: surrounding JavaScript whitespace is ignored, decimal literals
with an optional sign and exponent are accepted, as are ``Infinity`` and
unsigned ``0x`` / ``0o`` / ``0b`` integer literals; anything else (``1_000``,
``1,000``, ``inf``, ``nan``) is not a number. Formatting reproduces
``Math.round``, ``Number.prototype.toFixed`` and ``String(number)`` exactly,
so serialized figures match byte for byte.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from pcn_clone.core.jsstr import as_double, js_trim, number_to_string

AmountReason = Literal["not_a_number", "negative"]

_DECIMAL_LITERAL = re.compile(
    r"[+-]?(?:Infinity|(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)"
)
_RADIX_LITERALS = (
    (re.compile(r"0[xX][0-9a-fA-F]+"), 16),
    (re.compile(r"0[oO][0-7]+"), 8),
    (re.compile(r"0[bB][01]+"), 2),
)
_THOUSANDS = re.compile(r"\B(?=(\d{3})+(?!\d))", re.ASCII)


def js_number(text: str) -> float:
    """Convert a string to a number exactly as JavaScript's ``Number(text)``.

    Returns ``nan`` for anything that is not a numeric literal; a blank or
    whitespace-only string is ``0``.
    """
    trimmed = js_trim(text)
    if trimmed == "":
        return 0.0
    if _DECIMAL_LITERAL.fullmatch(trimmed):
        if trimmed.endswith("Infinity"):
            return -math.inf if trimmed.startswith("-") else math.inf
        return float(trimmed)
    for pattern, radix in _RADIX_LITERALS:
        if pattern.fullmatch(trimmed):
            return as_double(int(trimmed[2:], radix))
    return math.nan


def js_round(value: float) -> float:
    """``Math.round``: nearest integer, ties toward positive infinity."""
    if not math.isfinite(value) or value == 0:
        return value
    rounded = math.floor(Fraction(value) + Fraction(1, 2))
    if rounded == 0 and value < 0:
        return -0.0
    return float(rounded)


def is_integer(value: float) -> bool:
    """``Number.isInteger``."""
    return math.isfinite(value) and value == math.floor(value)


def to_fixed(value: float, digits: int) -> str:
    """``Number.prototype.toFixed``: exact decimal rounding, ties away from zero."""
    if not math.isfinite(value) or abs(value) >= 1e21:
        return number_to_string(value)
    sign = "-" if value < 0 else ""
    scaled = math.floor(abs(Fraction(value)) * 10**digits + Fraction(1, 2))
    text = str(scaled)
    if digits == 0:
        return sign + text
    if len(text) <= digits:
        text = "0" * (digits + 1 - len(text)) + text
    return f"{sign}{text[:-digits]}.{text[-digits:]}"


# --- Parsing entered amounts -------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParsedAmount:
    """A valid entered amount: finite and not negative."""

    value: float


@dataclass(frozen=True, slots=True)
class RejectedAmount:
    """An entered amount that is not a number, or is negative."""

    reason: AmountReason


AmountParse = ParsedAmount | RejectedAmount
"""The outcome of parsing a non-blank entered amount."""


def _entered_text(raw: str | None) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise TypeError(
            f"An entered amount must be a string, not {type(raw).__name__}."
        )
    return js_trim(raw)


def _parse_non_blank(text: str) -> AmountParse:
    value = js_number(text)
    if not math.isfinite(value):
        return RejectedAmount("not_a_number")
    if value < 0:
        return RejectedAmount("negative")
    return ParsedAmount(value)


def parse_amount(raw: str | None) -> AmountParse:
    """Parse an entered amount where blank is a valid zero; negatives and
    non-numbers are rejected with a distinguishing reason. Raises
    ``TypeError`` for a non-string."""
    text = _entered_text(raw)
    return ParsedAmount(0.0) if text == "" else _parse_non_blank(text)


def parse_scenario_amount(raw: str | None) -> AmountParse | None:
    """Parse an entered amount where blank is absent (``None``), not zero;
    negatives and non-numbers are rejected with a distinguishing reason.
    Raises ``TypeError`` for a non-string."""
    text = _entered_text(raw)
    return None if text == "" else _parse_non_blank(text)


def to_amount(raw: str | None) -> float:
    """An entered amount for summation; blank or invalid entries count as zero."""
    parsed = parse_amount(raw)
    return parsed.value if isinstance(parsed, ParsedAmount) else 0.0


# --- Formatting --------------------------------------------------------------


def format_amount(value: float) -> str:
    """Format an amount with thousands separators: integers bare, everything
    else to two decimals after rounding half up at the cent."""
    rounded = js_round(as_double(value) * 100) / 100
    fixed = number_to_string(rounded) if is_integer(rounded) else to_fixed(rounded, 2)
    negative = fixed.startswith("-")
    unsigned = fixed[1:] if negative else fixed
    parts = unsigned.split(".")
    int_part = parts[0]
    dec_part = parts[1] if len(parts) > 1 else ""
    grouped = _THOUSANDS.sub(",", int_part)
    return f"{'-' if negative else ''}{grouped}{'.' + dec_part if dec_part else ''}"
