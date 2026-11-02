"""Scenario comparison: gate, computed cells, validation and serialization."""

from __future__ import annotations

from typing import Any

import pytest

from pcn_clone.content import load_template
from pcn_clone.content.models import ScenarioComparisonInput
from pcn_clone.core.scenario import (
    NOT_APPLICABLE_STATEMENT,
    coerce_scenario_comparison_answer,
    compute_computed_cell,
    is_applicable,
    prepare_scenario_comparison,
    serialize_scenario_comparison_answer,
    validate_scenario_comparison,
)
from tests.helpers import computed_cell_json, fixture_params, load_fixture

SECTION = "estimated_investment_costs_and_financing"


def _field(field_id: str) -> Any:
    field = load_template().get_field(SECTION, field_id)
    assert field is not None and isinstance(field.input, ScenarioComparisonInput)
    return field


def test_default_scenarios_match_golden() -> None:
    golden = load_fixture("scenario_calc.json")
    for field_id, expected in golden["defaults"].items():
        field_input = _field(field_id).input
        answer = expected["answer"]
        assert is_applicable(field_input, answer) is expected["applicable"]
        computed = [
            {
                "rowId": row.id,
                "label": row.label,
                "subtract": list(row.subtract),
                "cells": {
                    column.id: computed_cell_json(
                        compute_computed_cell(answer, row, column.id)
                    )
                    for column in field_input.columns
                },
            }
            for row in field_input.computed_rows
        ]
        assert computed == expected["computedRows"]


@pytest.mark.parametrize(
    "case", fixture_params("scenario_calc.json", "computedCellCases", "computedCell")
)
def test_computed_cell_matches_golden(case: dict[str, Any]) -> None:
    field_input = _field(case["fieldId"]).input
    row = next(r for r in field_input.computed_rows if r.id == case["computedRowId"])
    assert (
        computed_cell_json(compute_computed_cell(case["answer"], row, case["columnId"]))
        == case["result"]
    )


@pytest.mark.parametrize(
    "case", fixture_params("scenario_calc.json", "isApplicableCases", "isApplicable")
)
def test_is_applicable_matches_golden(case: dict[str, Any]) -> None:
    assert (
        is_applicable(_field(case["fieldId"]).input, case["answer"]) is case["result"]
    )


# --- Unit checks without fixtures --------------------------------------------


def _answer(
    gate: str | None = None,
    narratives: dict[str, str] | None = None,
    **rows: dict[str, str],
) -> dict[str, Any]:
    answer: dict[str, Any] = {"rows": rows, "narratives": narratives or {}}
    if gate is not None:
        answer["applicability"] = {"revenue_expected": gate}
    return answer


def test_derived_cells_need_both_sides_present_and_valid() -> None:
    row = _field("operating_costs").input.computed_rows[0]
    answer = _answer(
        with_project={"year_1": "100", "year_2": "100", "year_3": "0.3"},
        without_project={"year_1": "250", "year_2": "", "year_3": "0.1"},
    )
    assert computed_cell_json(compute_computed_cell(answer, row, "year_1")) == {
        "present": True,
        "value": -150,
    }
    assert computed_cell_json(compute_computed_cell(answer, row, "year_2")) == {
        "present": False,
        "value": None,
    }
    assert compute_computed_cell(answer, row, "year_3") == 0.19999999999999998


def test_inactive_gate_makes_rows_inert() -> None:
    field = _field("revenues")
    answer = _answer(
        gate="no",
        narratives={"justification": " No user fees. "},
        with_project={"year_1": "-5"},
    )
    assert validate_scenario_comparison(field.input, answer) == []
    assert prepare_scenario_comparison(field, answer).answer_text == (
        "Is the project expected to generate revenue?\nNo\n\n"
        f"{NOT_APPLICABLE_STATEMENT}\n\nJustification\nNo user fees."
    )


def test_padded_gate_validates_but_is_not_applicable() -> None:
    field = _field("revenues")
    answer = _answer(gate=" yes ", narratives={"justification": "x"})
    assert validate_scenario_comparison(field.input, answer) == []
    assert not is_applicable(field.input, answer)
    assert prepare_scenario_comparison(field, answer).answer_text.startswith(
        "Is the project expected to generate revenue?\nYes\n\nThe proposer indicated"
    )


def test_validation_messages() -> None:
    field = _field("revenues")
    answer = _answer(
        gate="yes",
        with_project={"year_1": "-1", "year_2": "abc"},
        without_project={"year_1": "1,000"},
    )
    assert [
        issue.message for issue in validate_scenario_comparison(field.input, answer)
    ] == [
        "Expected revenue with project for 1st operating year cannot be negative.",
        "Expected revenue with project for 2nd operating year must be a number.",
        "Enter Expected revenue with project for 3rd operating year.",
        "Expected revenue without project for 1st operating year must be a number.",
        "Justification is required.",
    ]
    assert [
        issue.message
        for issue in validate_scenario_comparison(field.input, _answer(gate="maybe"))
    ] == [
        'Select a valid option for "Is the project expected to generate revenue?".',
        "Justification is required.",
    ]
    first = next(iter(validate_scenario_comparison(field.input, _answer())))
    assert first.kind == "missing_applicability"


def test_table_serialization() -> None:
    field = _field("operating_costs")
    answer = _answer(
        narratives={"justification": "J", "financing_approach": ""},
        with_project={"year_1": "120000", "year_2": "1234.5", "year_3": "x"},
        without_project={"year_1": "130000"},
    )
    assert not prepare_scenario_comparison(field, answer).ok
    assert serialize_scenario_comparison_answer(field.input, answer) == (
        "Scenario | 1st operating year | 2nd operating year | 3rd operating year\n"
        "With project | 120,000 | 1,234.50 | (invalid)\n"
        "Without project | 130,000 | (not provided) | (not provided)\n"
        "Difference | -10,000 | (not computable) | (not computable)\n\n"
        "Justification\nJ\n\n"
        "If increased operating costs are foreseen, describe the approach to their "
        "financing. Has any preliminary assessment regarding the capacity to cover "
        "these costs been made?"
        "\n(no answer provided)"
    )


def test_coercion_keeps_only_exact_scenario_shapes() -> None:
    good = {"applicability": {"revenue_expected": "yes"}, "rows": {}, "narratives": {}}
    assert coerce_scenario_comparison_answer(good) is good
    for bad in (
        {"rows": {}, "narratives": {}, "applicability": None},
        {"rows": {"with_project": {"year_1": 5}}, "narratives": {}},
        {"rows": {}},
        "text",
    ):
        assert coerce_scenario_comparison_answer(bad) == {"rows": {}, "narratives": {}}
