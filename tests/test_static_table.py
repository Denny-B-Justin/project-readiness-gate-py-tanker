"""Static tables: inert rows, markers, option labels and validation."""

from __future__ import annotations

from typing import Any

from pcn_clone.content import load_template
from pcn_clone.content.models import StaticTableInput
from pcn_clone.core.static_table import (
    STATIC_TABLE_INERT_VALUE,
    coerce_static_table_answer,
    is_row_inert,
    normalize_cell,
    prepare_static_table,
    serialize_static_table_answer,
    validate_static_table,
)

SECTION = "project_advancement_and_documentation"


def _field(field_id: str = "land_and_property_status") -> Any:
    field = load_template().get_field(SECTION, field_id)
    assert field is not None and isinstance(field.input, StaticTableInput)
    return field


HEADER = (
    "Item | Is it required for the project? | Status | Expected acquisition date "
    "| Comment"
)
LAND = "Land ownership or the right to use the land for construction purposes"


def test_inert_row_keeps_gate_and_comment_only() -> None:
    field = _field()
    answer = {
        "rows": {
            "land_ownership": {
                "required": STATIC_TABLE_INERT_VALUE,
                "status": "in_progress",
                "expected_acquisition_date": "2026-01",
                "comment": "Existing right-of-way.",
            }
        }
    }
    assert is_row_inert(field.input, answer, "land_ownership")
    assert serialize_static_table_answer(field.input, answer) == (
        f"{HEADER}\n{LAND} | No | n/a | n/a | Existing right-of-way."
    )


def test_active_row_uses_option_labels_and_dashes() -> None:
    field = _field()
    answer = {
        "rows": {
            "land_ownership": {"required": " yes ", "status": "ready_and_approved"}
        }
    }
    assert not is_row_inert(field.input, answer, "land_ownership")
    assert prepare_static_table(field, answer).answer_text == (
        f"{HEADER}\n{LAND} | Yes | Ready and approved | — | —"
    )


def test_padded_gate_is_not_inert() -> None:
    field = _field()
    answer = {"rows": {"land_ownership": {"required": " no", "status": "in_progress"}}}
    assert not is_row_inert(field.input, answer, "land_ownership")
    assert " | No | In progress | — | —" in serialize_static_table_answer(
        field.input, answer
    )


def test_cells_are_normalized() -> None:
    assert normalize_cell(" a |\n b\u2028c\ufeff ") == "a / b c"
    assert normalize_cell("x\u0085y") == "x\u0085y"


def test_validation() -> None:
    field = _field("documentation_and_permits")
    answer = {"rows": {"building_permit": {"required": "yes", "status": "lost"}}}
    messages = [issue.message for issue in validate_static_table(field.input, answer)]

    def missing(row: str) -> str:
        return f'Enter Is it required for the project? for "{row}".'

    assert messages == [
        missing("Preliminary feasibility study"),
        missing("Technical and economic analysis"),
        missing("Conceptual design"),
        missing("Architectural and construction project"),
        missing("EIA / Environmental assessment"),
        'Status for "Building permit" is not a valid option.',
        missing("Other required permissions / licenses / patents"),
        missing("Tender documentation"),
    ]
    assert not prepare_static_table(field, answer).ok


def test_coercion_keeps_only_exact_static_table_shapes() -> None:
    good = {"rows": {"a": {"b": "c"}}}
    assert coerce_static_table_answer(good) is good
    for bad in (
        {"rows": {"a": {"b": 1}}},
        {"rows": {}, "extra": {}},
        {"rows": []},
        None,
    ):
        assert coerce_static_table_answer(bad) == {"rows": {}}
