"""Amount parsing and formatting with JavaScript number semantics.

Golden-fixture mapping: a result of ``{"error": ...}`` records a throw (a
non-string amount), and these functions raise ``TypeError`` for the same
inputs. Parse results are shaped as ``{ok, value | reason}`` (worksheet) or
``{present, ...}`` (scenario) before comparing; ``-0`` is recorded as ``0``
because JSON has no negative zero. The ``formatScenarioAmount`` cases run
against ``format_amount``, the one formatter both tables use.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import pytest

from pcn_clone.core.jsstr import number_to_string
from pcn_clone.core.numbers import (
    ParsedAmount,
    format_amount,
    js_number,
    js_round,
    parse_amount,
    parse_scenario_amount,
    to_amount,
    to_fixed,
)
from tests.helpers import amount_json, fixture_params, scenario_amount_json

NUMBERS = "number_cases.json"


def _expect(function: Callable[[Any], Any], case: dict[str, Any]) -> None:
    expected = case["result"]
    if isinstance(expected, dict) and "error" in expected:
        with pytest.raises(TypeError, match="must be a string"):
            function(case["input"])
        return
    assert function(case["input"]) == expected


@pytest.mark.parametrize("case", fixture_params(NUMBERS, "parseAmount", "parseAmount"))
def test_parse_amount_golden(case: dict[str, Any]) -> None:
    _expect(lambda raw: amount_json(parse_amount(raw)), case)


@pytest.mark.parametrize(
    "case", fixture_params(NUMBERS, "parseScenarioAmount", "parseScenarioAmount")
)
def test_parse_scenario_amount_golden(case: dict[str, Any]) -> None:
    _expect(lambda raw: scenario_amount_json(parse_scenario_amount(raw)), case)


@pytest.mark.parametrize("case", fixture_params(NUMBERS, "toAmount", "toAmount"))
def test_to_amount_golden(case: dict[str, Any]) -> None:
    _expect(to_amount, case)


@pytest.mark.parametrize(
    "case", fixture_params(NUMBERS, "formatAmount", "formatAmount")
)
def test_format_amount_golden(case: dict[str, Any]) -> None:
    _expect(format_amount, case)


@pytest.mark.parametrize(
    "case", fixture_params(NUMBERS, "formatScenarioAmount", "formatScenarioAmount")
)
def test_format_scenario_amount_golden(case: dict[str, Any]) -> None:
    _expect(format_amount, case)


# --- Number() ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", 0.0),
        (" \t\n", 0.0),
        ("1e3", 1000.0),
        ("1E+3", 1000.0),
        ("0x10", 16.0),
        ("0XfF", 255.0),
        ("0o17", 15.0),
        ("0b101", 5.0),
        ("+5", 5.0),
        (".5", 0.5),
        ("5.", 5.0),
        ("00012", 12.0),
        ("\u00a012\ufeff", 12.0),
        ("\u300012\u2028", 12.0),
        ("Infinity", math.inf),
        ("-Infinity", -math.inf),
        ("1e400", math.inf),
    ],
)
def test_js_number_accepts(text: str, expected: float) -> None:
    assert js_number(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "1_000",
        "1,000",
        "1 000",
        "-0x10",
        "+0x10",
        "0x",
        "inf",
        "infinity",
        "nan",
        "NaN",
        ".",
        "e5",
        "1e",
        "\u008512",
        "\x1c12",
        "\u180e12",
        "\u200b12",
        "\u0661\u0662",
        "12abc",
    ],
)
def test_js_number_rejects(text: str) -> None:
    assert math.isnan(js_number(text))


def test_negative_zero_parses_as_a_valid_amount() -> None:
    parsed = parse_amount("-0")
    assert isinstance(parsed, ParsedAmount)
    assert parsed.value == 0 and math.copysign(1, parsed.value) == -1


def test_blank_means_zero_for_worksheets_and_absent_for_scenarios() -> None:
    assert parse_amount(None) == ParsedAmount(0.0)
    assert parse_amount(" \ufeff ") == ParsedAmount(0.0)
    assert parse_scenario_amount("") is None
    assert parse_scenario_amount(None) is None


def test_negative_and_non_numeric_amounts_are_distinguished() -> None:
    assert amount_json(parse_amount("-3")) == {"ok": False, "reason": "negative"}
    assert amount_json(parse_amount("abc")) == {"ok": False, "reason": "not_a_number"}
    assert amount_json(parse_amount("Infinity")) == {
        "ok": False,
        "reason": "not_a_number",
    }
    assert scenario_amount_json(parse_scenario_amount("-1")) == {
        "present": True,
        "ok": False,
        "reason": "negative",
    }
    assert to_amount("abc") == 0 and to_amount("-5") == 0 and to_amount("12.5") == 12.5


@pytest.mark.parametrize("value", [5, 1.5, 0])
def test_non_string_amounts_raise(value: Any) -> None:
    with pytest.raises(TypeError, match="must be a string"):
        parse_amount(value)


# --- Formatting --------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0"),
        (-0.0, "0"),
        (5, "5"),
        (1234567, "1,234,567"),
        (1234.5, "1,234.50"),
        (-2.5, "-2.50"),
        (12.345, "12.35"),
        (12.355, "12.36"),
        (1.005, "1"),
        (2.675, "2.68"),
        (8.345, "8.35"),
        (0.125, "0.13"),
        (-0.125, "-0.12"),
        (-0.005, "0"),
        (-0.006, "-0.01"),
        (999.995, "1,000"),
        (0.1 + 0.2, "0.30"),
        (1e20, "100,000,000,000,000,000,000"),
        (1e21, "999,999,999,999,999,900,000"),
        (1e22, "1e+22"),
        (math.inf, "Infinity"),
        (-math.inf, "-Infinity"),
        (math.nan, "NaN"),
    ],
)
def test_format_amount_rounds_half_up_with_separators(
    value: float, expected: str
) -> None:
    assert format_amount(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.5, 1.0),
        (1.5, 2.0),
        (2.5, 3.0),
        (-0.5, -0.0),
        (-1.5, -1.0),
        (-2.5, -2.0),
        (0.49999999999999994, 0.0),
        (-0.4, -0.0),
        (4503599627370497.0, 4503599627370497.0),
    ],
)
def test_js_round_is_half_toward_positive_infinity(
    value: float, expected: float
) -> None:
    result = js_round(value)
    assert result == expected
    assert math.copysign(1, result) == math.copysign(1, expected)


@pytest.mark.parametrize(
    ("value", "digits", "expected"),
    [
        (1.005, 2, "1.00"),
        (-1.005, 2, "-1.00"),
        (0.125, 2, "0.13"),
        (1e-7, 2, "0.00"),
        (-0.001, 2, "-0.00"),
        (123.456, 0, "123"),
        (1e21, 2, "1e+21"),
    ],
)
def test_to_fixed(value: float, digits: int, expected: str) -> None:
    assert to_fixed(value, digits) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (2.0**60, "1152921504606847000"),
        (0.1 + 0.2, "0.30000000000000004"),
        (1e-7, "1e-7"),
        (1.23e-18, "1.23e-18"),
        (5e-324, "5e-324"),
        (1.7976931348623157e308, "1.7976931348623157e+308"),
        (1e16, "10000000000000000"),
        (1e21, "1e+21"),
        (123456.789, "123456.789"),
        (0.000001, "0.000001"),
        (12345678901234567890, "12345678901234567000"),
        (-0.0, "0"),
    ],
)
def test_number_to_string_matches_javascript(value: float, expected: str) -> None:
    assert number_to_string(value) == expected
