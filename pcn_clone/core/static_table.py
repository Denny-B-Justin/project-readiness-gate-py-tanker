"""The static-table field: authored rows filled across typed columns.

Only ``required_columns`` must be answered; any non-blank select cell must
hold one of its options. A row whose gate column (the first required column)
reads ``"no"`` is inert: its other non-comment cells serialize as ``n/a``.
Blank cells serialize as an em dash, select cells by option label.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from pcn_clone.content.models import (
    SelectControl,
    StaticTableInput,
    TemplateField,
    TextareaControl,
    is_static_table_answer,
)
from pcn_clone.core.jsstr import collapse_whitespace, js_trim

STATIC_TABLE_INERT_VALUE = "no"
"""The gate-column value that marks a row as not relevant to the project."""

NOT_APPLICABLE_CELL = "n/a"
"""The marker for a data cell on an inert row."""

BLANK_CELL = "—"
"""The marker for a blank cell."""

StaticTableAnswer = dict[str, Any]
"""``{"rows": {rowId: {columnId: str}}}``."""


def empty_static_table_answer() -> StaticTableAnswer:
    """A static-table answer with no entered values."""
    return {"rows": {}}


def coerce_static_table_answer(value: Any) -> StaticTableAnswer:
    """The answer itself when it has the exact static-table shape; otherwise
    an empty answer."""
    if is_static_table_answer(value):
        return cast(StaticTableAnswer, value)
    return empty_static_table_answer()


def _row_values(answer: StaticTableAnswer, row_id: str) -> dict[str, str]:
    values: dict[str, str] = answer["rows"].get(row_id) or {}
    return values


def _gate_column_id(field_input: StaticTableInput) -> str | None:
    required = field_input.required_columns
    return required[0] if required else None


def is_row_inert(
    field_input: StaticTableInput, answer: StaticTableAnswer, row_id: str
) -> bool:
    """True when the row's gate column (the first required column) holds
    exactly ``"no"``; a table without required columns has no inert rows."""
    gate_column_id = _gate_column_id(field_input)
    if gate_column_id is None:
        return False
    value = _row_values(answer, row_id).get(gate_column_id, "")
    return value == STATIC_TABLE_INERT_VALUE


# --- Validation --------------------------------------------------------------

StaticTableIssueKind = Literal["missing_value", "invalid_value"]


@dataclass(frozen=True, slots=True)
class StaticTableIssue:
    """One static-table validation problem located by row and column."""

    kind: StaticTableIssueKind
    message: str
    row_id: str | None = None
    row_label: str | None = None
    column_id: str | None = None


def validate_static_table(
    field_input: StaticTableInput, answer: StaticTableAnswer
) -> list[StaticTableIssue]:
    """Required columns must be answered on every row; a non-blank select
    cell must hold one of its options."""
    issues: list[StaticTableIssue] = []
    required = set(field_input.required_columns or [])
    for row in field_input.rows:
        values = _row_values(answer, row.id)
        for column in field_input.columns:
            trimmed = js_trim(values.get(column.id, ""))
            if trimmed == "":
                if column.id in required:
                    issues.append(
                        StaticTableIssue(
                            kind="missing_value",
                            row_id=row.id,
                            row_label=row.label,
                            column_id=column.id,
                            message=f'Enter {column.label} for "{row.label}".',
                        )
                    )
                continue
            if isinstance(column, SelectControl) and not any(
                option.value == trimmed for option in column.options
            ):
                issues.append(
                    StaticTableIssue(
                        kind="invalid_value",
                        row_id=row.id,
                        row_label=row.label,
                        column_id=column.id,
                        message=(
                            f'{column.label} for "{row.label}" is not a valid option.'
                        ),
                    )
                )
    return issues


# --- Serialization -----------------------------------------------------------


def normalize_cell(text: str) -> str:
    """Keep a cell on one line and inside its column: collapse whitespace
    runs to one space, replace ``|`` with ``/`` and trim."""
    return js_trim(collapse_whitespace(text).replace("|", "/"))


def serialize_static_table_answer(
    field_input: StaticTableInput, answer: StaticTableAnswer
) -> str:
    """A pipe-delimited table: a header of column labels, then one line per
    authored row."""
    header = ["Item", *(normalize_cell(column.label) for column in field_input.columns)]
    lines = [" | ".join(header)]
    gate_column_id = _gate_column_id(field_input)

    for row in field_input.rows:
        values = _row_values(answer, row.id)
        inert = is_row_inert(field_input, answer, row.id)
        cells: list[str] = []
        for column in field_input.columns:
            keeps_value = column.id == gate_column_id or isinstance(
                column, TextareaControl
            )
            if inert and not keeps_value:
                cells.append(NOT_APPLICABLE_CELL)
                continue
            raw = js_trim(values.get(column.id, ""))
            if raw == "":
                cells.append(BLANK_CELL)
            elif isinstance(column, SelectControl):
                option = next((o for o in column.options if o.value == raw), None)
                cells.append(option.label if option is not None else raw)
            else:
                cells.append(raw)
        lines.append(" | ".join(normalize_cell(cell) for cell in [row.label, *cells]))

    return "\n".join(lines)


# --- Preparation -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PreparedStaticTable:
    """A static-table answer prepared for evaluation."""

    ok: bool
    answer_text: str | None = None
    issues: tuple[StaticTableIssue, ...] = ()


def prepare_static_table(field: TemplateField, answer: Any) -> PreparedStaticTable:
    """Coerce, validate and (when valid) serialize a static-table answer."""
    field_input = field.input
    if not isinstance(field_input, StaticTableInput):
        raise TypeError(
            f'prepare_static_table called for non-static-table field "{field.id}".'
        )
    coerced = coerce_static_table_answer(answer)
    issues = validate_static_table(field_input, coerced)
    if issues:
        return PreparedStaticTable(ok=False, issues=tuple(issues))
    return PreparedStaticTable(
        ok=True, answer_text=serialize_static_table_answer(field_input, coerced)
    )
