"""Worksheet rows, totals, category summary, validation and serialization."""

from __future__ import annotations

from typing import Any

import pytest

from pcn_clone.content import load_default_project, load_template
from pcn_clone.content.models import WorksheetInput
from pcn_clone.core.fields import coerce_string_record_array
from pcn_clone.core.worksheet import (
    WORKSHEET_INTRO,
    coerce_worksheet_answer,
    compute_category_summary,
    compute_grand_total,
    compute_row_total,
    counted_rows,
    derive_worksheet_rows,
    get_row_values,
    prepare_worksheet,
    required_cost_control_ids,
    validate_worksheet,
    year_labels,
)
from tests.helpers import as_json, fixture_params, load_fixture

SCOPE = ("project_description_and_impact", "scope_of_the_project")
WORKSHEET = ("estimated_investment_costs_and_financing", "investment_cost_estimate")


def _input() -> WorksheetInput:
    field = load_template().get_field(*WORKSHEET)
    assert field is not None and isinstance(field.input, WorksheetInput)
    return field.input


def _default_answers() -> tuple[Any, Any]:
    answers = {
        (entry.section_id, entry.field_id): entry.answer
        for entry in load_default_project().submission.answers
    }
    return answers[SCOPE], answers[WORKSHEET]


def _derived_json(rows: Any) -> list[dict[str, Any]]:
    return as_json(rows, keep_none=True)


# --- Golden fixture ----------------------------------------------------------


def test_default_worksheet_matches_golden_calculations() -> None:
    golden = load_fixture("worksheet_calc.json")
    field_input = _input()
    source_answer, answer = _default_answers()
    rows = derive_worksheet_rows(field_input, coerce_string_record_array(source_answer))

    assert _derived_json(rows) == golden["derivedRows"]
    assert required_cost_control_ids(field_input) == golden["requiredCostControlIds"]
    assert [row.row_id for row in counted_rows(rows)] == golden["countedRowIds"]
    assert compute_grand_total(field_input, rows, answer) == golden["grandTotal"]
    assert (
        as_json(compute_category_summary(field_input, rows, answer))
        == golden["categorySummary"]
    )

    by_id = {row.row_id: row for row in rows}
    for expected in golden["rows"]:
        row = by_id[expected["rowId"]]
        values = get_row_values(answer, row.row_id)
        assert row.label == expected["component"]
        assert values.get("cost_category") == expected["cost_category"]
        assert compute_row_total(field_input, values) == expected["rowTotal"]
        assert row.start_year == expected["startYear"]
        assert row.has_start_date == expected["hasStartDate"]


def test_default_year_labels_match_the_golden_worksheet_text() -> None:
    serialized = load_fixture("serialized_default.json")
    text = next(
        field["serializedText"]
        for field in serialized["fields"]
        if field["fieldId"] == WORKSHEET[1]
    )
    field_input = _input()
    source_answer, _ = _default_answers()
    rows = derive_worksheet_rows(field_input, coerce_string_record_array(source_answer))
    for row in counted_rows(rows):
        block = text.split(f"{row.label} — category:", 1)[1].split("\n\n", 1)[0]
        labels = [line.split(":", 1)[0].strip() for line in block.splitlines()[1:6]]
        assert labels == [label for _, label in year_labels(field_input, row)]


@pytest.mark.parametrize(
    "variant", fixture_params("worksheet_calc.json", "variants", "variant")
)
def test_worksheet_variant_matches_golden(variant: dict[str, Any]) -> None:
    field_input = _input()
    answer = variant["worksheetAnswer"]
    rows = derive_worksheet_rows(
        field_input, coerce_string_record_array(variant["sourceAnswer"])
    )
    assert _derived_json(rows) == variant["derivedRows"]
    assert {
        row.row_id: compute_row_total(field_input, get_row_values(answer, row.row_id))
        for row in rows
    } == variant["rowTotals"]
    assert [row.row_id for row in counted_rows(rows)] == variant["countedRowIds"]
    assert compute_grand_total(field_input, rows, answer) == variant["grandTotal"]
    assert (
        as_json(compute_category_summary(field_input, rows, answer))
        == variant["categorySummary"]
    )


# --- Unit checks without fixtures --------------------------------------------


def _source(*items: tuple[str, str, str]) -> list[dict[str, str]]:
    return [
        {
            "_rowId": row_id,
            "component": label,
            "expected_start_date": start,
            "expected_end_date": "",
        }
        for row_id, label, start in items
    ]


def _costs(category: str = "construction", **years: str) -> dict[str, str]:
    values = {
        "cost_category": category,
        "year_1": "0",
        "year_2": "0",
        "year_3": "0",
        "year_4": "0",
        "year_5": "0",
    }
    values.update(years)
    return values


def test_rows_are_anchored_by_start_date() -> None:
    rows = derive_worksheet_rows(
        _input(),
        _source(
            ("a", " Works ", " 2027-04"), ("b", "Design", ""), ("c", "Other", "27-04")
        ),
    )
    assert [(row.label, row.start_year, row.has_start_date) for row in rows] == [
        ("Works", 2027, True),
        ("Design", None, False),
        ("Other", None, False),
    ]
    assert [row.row_id for row in counted_rows(rows)] == ["a"]
    assert year_labels(_input(), rows[0])[0] == ("year_1", "Year 1 (2027)")
    assert year_labels(_input(), rows[0])[-1] == ("year_5", "Year 5 (2031)")
    assert year_labels(_input(), rows[1])[0] == ("year_1", "Year 1")


def test_undated_rows_do_not_count_toward_totals() -> None:
    field_input = _input()
    rows = derive_worksheet_rows(
        field_input, _source(("a", "Works", "2026-01"), ("b", "Stale", ""))
    )
    answer = {
        "componentCosts": {"a": _costs(year_1="100"), "b": _costs(year_1="999")},
        "narratives": {},
    }
    assert compute_grand_total(field_input, rows, answer) == 100
    summary = compute_category_summary(field_input, rows, answer)
    assert summary.grand_total == 100
    assert (
        summary.rows[-1].label == "Total"
        and summary.rows[-1].per_column["year_1"] == 100
    )


def test_blank_and_invalid_amounts_sum_as_zero() -> None:
    values = _costs(
        year_1="1,000", year_2="-5", year_3=" 2.5 ", year_4="", subsequent_years="1e3"
    )
    assert compute_row_total(_input(), values) == 1002.5


def test_coercion_keeps_only_exact_worksheet_shapes() -> None:
    good = {"componentCosts": {"a": {"year_1": "1"}}, "narratives": {"x": "y"}}
    assert coerce_worksheet_answer(good) is good
    for bad in (
        None,
        [],
        {"componentCosts": {}},
        {"componentCosts": {}, "narratives": {}, "extra": 1},
        {"componentCosts": {"a": {"year_1": 1}}, "narratives": {}},
        {"componentCosts": {"a": []}, "narratives": {}},
    ):
        assert coerce_worksheet_answer(bad) == {"componentCosts": {}, "narratives": {}}


def test_validation_messages_and_order() -> None:
    field_input = _input()
    rows = derive_worksheet_rows(
        field_input,
        _source(
            ("a", "Works", "2026-01"),
            ("", "Nameless", "2026-01"),
            ("a", "Dup", "2026-01"),
            ("d", "", ""),
        ),
    )
    answer = {
        "componentCosts": {
            "a": _costs(category="bogus", year_1="-1", year_2="abc", year_3="")
        },
        "narratives": {"estimation_basis": "Unit rates."},
    }
    messages = [
        issue.message for issue in validate_worksheet(field_input, rows, answer, "3.2")
    ]
    assert messages == [
        'Select a valid cost category for "Works".',
        'Year 1 for "Works" cannot be negative.',
        'Year 2 for "Works" must be a number.',
        'Enter Year 3 for "Works".',
        (
            '"Nameless" has no stable row id in section 3.2, so its costs cannot be '
            "recorded reliably. Re-add the item in section 3.2."
        ),
        (
            '"Dup" shares a row id with another row; row ids must be unique. '
            "Re-add the duplicate item in section 3.2."
        ),
        (
            '"this item" has no start date in section 3.2. Add a start date for '
            "it there before entering its costs."
        ),
        "Please provide expected sources of financing for the project is required.",
    ]
    assert [issue.message for issue in validate_worksheet(field_input, [], answer)] == [
        "Add at least one item in the source list before completing the cost worksheet."
    ]


def test_serialization_layout() -> None:
    template = load_template()
    field = template.get_field(*WORKSHEET)
    source_field = template.get_field(*SCOPE)
    source = _source(("a", "Works", "2026-05"))
    answer = {
        "componentCosts": {
            "a": _costs(year_1="1234.5", year_2="1000000", subsequent_years="")
        },
        "narratives": {
            "estimation_basis": " Unit rates. ",
            "financing_sources": "Budget.",
        },
    }
    prepared = prepare_worksheet(field, source_field, source, answer)
    assert prepared.ok and prepared.grand_total == 1001234.5
    zero_row = (
        "Year 1: 0  Year 2: 0  Year 3: 0  Year 4: 0  Year 5: 0  "
        "Subsequent years: 0  Total investment cost: 0"
    )
    filled_row = (
        "Year 1: 1,234.50  Year 2: 1,000,000  Year 3: 0  Year 4: 0  Year 5: 0  "
        "Subsequent years: 0  Total investment cost: 1,001,234.50"
    )
    assert prepared.answer_text == (
        f"{WORKSHEET_INTRO}\n\n"
        "Section 3.2 components (project scope context):\n"
        "  1. Component: Works | Expected start date: 2026-05 | Expected end date: \n\n"
        "Cost estimate by component:\n\n"
        "Works — category: Construction\n"
        "  Year 1 (2026): 1,234.50\n  Year 2 (2027): 1,000,000\n  Year 3 (2028): 0\n"
        "  Year 4 (2029): 0\n  Year 5 (2030): 0\n  Subsequent years: 0\n"
        "  Total investment cost: 1,001,234.50\n\n"
        "Summary by expenditure category:\n"
        f"  Preparatory documentation: {zero_row}\n"
        f"  Purchase of land: {zero_row}\n"
        f"  Construction: {filled_row}\n"
        f"  Equipment, vehicles, machinery, furniture etc.: {zero_row}\n"
        f"  Software: {zero_row}\n"
        f"  Other costs: {zero_row}\n"
        f"  Reserve, up to 10%: {zero_row}\n"
        f"  Total: {filled_row}\n\n"
        "Grand total: 1,001,234.50\n\n"
        "Specify on what basis the investment costs were estimated. "
        "Do the costs include VAT?\n"
        "Unit rates.\n\n"
        "Please provide expected sources of financing for the project\nBudget."
    )
