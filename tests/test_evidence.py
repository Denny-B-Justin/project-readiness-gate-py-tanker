"""Quote normalisation and verification."""

from __future__ import annotations

from typing import Any

import pytest

from pcn_clone.core.evidence import normalize_for_quote_match, verify_quote
from pcn_clone.core.jsstr import utf16_contains
from tests.helpers import fixture_params


@pytest.mark.parametrize(
    "case", fixture_params("quote_cases.json", "normalize", "normalize")
)
def test_normalize_matches_golden(case: dict[str, Any]) -> None:
    assert normalize_for_quote_match(case["input"]) == case["output"]


@pytest.mark.parametrize("case", fixture_params("quote_cases.json", "verify", "verify"))
def test_verify_matches_golden(case: dict[str, Any]) -> None:
    assert verify_quote(case["quote"], case["fieldText"]) is case["verified"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("  a \t\n b  ", "a b"),
        ("\ufeffa\u00a0\u3000b\u2028", "a b"),
        ("a\u0085b", "a\u0085b"),
        ("a\x1cb\x1f", "a\x1cb\x1f"),
        ("a\u200bb\u180e", "a\u200bb\u180e"),
        ("e\u0301", "\u00e9"),
        ("\u212b", "\u00c5"),
        ("\ufb01\u2460", "\ufb01\u2460"),
    ],
)
def test_normalization_uses_javascript_whitespace(text: str, expected: str) -> None:
    assert normalize_for_quote_match(text) == expected


def test_verification_rules() -> None:
    text = "The road is\n  18 km long and serves 12,400 residents."
    assert verify_quote("18 km long", text)
    assert verify_quote("road is 18 km", text)
    assert not verify_quote("Road is 18 km", text)
    assert not verify_quote("19 km", text)
    assert not verify_quote("", text)
    assert not verify_quote(" \n\ufeff", text)
    assert verify_quote("cafe\u0301", "a caf\u00e9 nearby")
    assert verify_quote("\U0001f600", "emoji \U0001f600 here")


def test_containment_is_by_utf16_code_unit() -> None:
    assert verify_quote("\ud83d", "emoji \U0001f600 here")
    assert verify_quote("\ude00 here", "emoji \U0001f600 here")
    assert not verify_quote("\ude00\ud83d", "emoji \U0001f600 here")


def test_utf16_containment_rejects_odd_offset_matches() -> None:
    # UTF-16LE stores U+4100 as bytes 00 41, so its second byte and the next
    # unit's first byte read as "A" (41 00) at an odd offset: not a match.
    assert not utf16_contains("\u4100\u0000", "A")
    assert utf16_contains("\u4100\u0000A", "A")
