"""The cost worksheet: rows derived from a source list, entered costs per row,
and every total and summary computed from them.

Rows are keyed by the source item's durable ``_rowId`` and anchored by its
start date: a row without a parseable start year has its cost inputs
disabled, is not counted in any total, and blocks evaluation. Blank cost
cells count as zero; negative or non-numeric cells are invalid.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from pcn_clone.content.models import (
    ROW_ID_KEY,
    Control,
    ListInput,
    NumberControl,
    SelectControl,
    SelectOption,
    TemplateField,
    WorksheetInput,
    is_worksheet_answer,
)
from pcn_clone.core.fields import Record, cell_text, coerce_string_record_array
from pcn_clone.core.jsstr import js_to_string, js_trim, trim_or_empty
from pcn_clone.core.numbers import (
    RejectedAmount,
    format_amount,
    parse_amount,
    to_amount,
)

WORKSHEET_INTRO = (
    "Estimated investment costs and expected financing, by project component."
)
"""The opening line of every serialized worksheet."""

_START_YEAR = re.compile(r"^([0-9]{4})")

WorksheetAnswer = dict[str, Any]
"""``{"componentCosts": {rowId: {controlId: str}}, "narratives": {id: str}}``."""


# --- Coercion ----------------------------------------------------------------


def empty_worksheet_answer() -> WorksheetAnswer:
    """A worksheet answer with no entered values."""
    return {"componentCosts": {}, "narratives": {}}


def coerce_worksheet_answer(value: Any) -> WorksheetAnswer:
    """The answer itself when it has the exact worksheet shape (string cells
    only, no extra keys); otherwise an empty answer."""
    if is_worksheet_answer(value):
        return cast(WorksheetAnswer, value)
    return empty_worksheet_answer()


# --- Rows --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorksheetRow:
    """One worksheet row derived from a source list item."""

    row_id: str
    label: str
    start_date: str
    has_start_date: bool
    start_year: int | None


def _parse_start_year(start_date: str) -> int | None:
    match = _START_YEAR.match(js_trim(start_date))
    return int(match.group(1)) if match else None


def derive_worksheet_rows(
    field_input: WorksheetInput, source_rows: Sequence[Mapping[str, str | None]]
) -> list[WorksheetRow]:
    """One row per source item, in source order."""
    source = field_input.row_source
    rows: list[WorksheetRow] = []
    for item in source_rows:
        start_date = js_trim(cell_text(item, source.start_date_control_id))
        start_year = _parse_start_year(start_date)
        rows.append(
            WorksheetRow(
                row_id=cell_text(item, ROW_ID_KEY),
                label=js_trim(cell_text(item, source.label_control_id)),
                start_date=start_date,
                has_start_date=start_year is not None,
                start_year=start_year,
            )
        )
    return rows


def get_row_values(answer: WorksheetAnswer, row_id: str) -> dict[str, str]:
    """The entered values for one row (empty when none were entered)."""
    values: dict[str, str] = answer["componentCosts"].get(row_id) or {}
    return values


def row_control_label(field_input: WorksheetInput, control_id: str) -> str:
    """A row control's label, falling back to its id."""
    control = next((c for c in field_input.row_controls if c.id == control_id), None)
    return control.label if control is not None else control_id


def category_options(field_input: WorksheetInput) -> list[SelectOption]:
    """The options of the group-by (category) select control."""
    control = next(
        (c for c in field_input.row_controls if c.id == field_input.summary.group_by),
        None,
    )
    return list(control.options) if isinstance(control, SelectControl) else []


def category_label(field_input: WorksheetInput, value: str) -> str:
    """The label for a stored category value, falling back to the value."""
    option = next((o for o in category_options(field_input) if o.value == value), None)
    return option.label if option is not None else value


def required_cost_control_ids(field_input: WorksheetInput) -> list[str]:
    """The summed cost controls that are not optional, in order."""
    optional = field_input.optional_row_controls or []
    return [
        control_id
        for control_id in field_input.row_total.sum
        if control_id not in optional
    ]


def year_labels(
    field_input: WorksheetInput, row: WorksheetRow
) -> list[tuple[str, str]]:
    """``(controlId, label)`` for each required cost control of a row, the
    label suffixed with its calendar year: the control at position ``i`` is
    labelled ``start_year + i``."""
    labels: list[tuple[str, str]] = []
    for offset, control_id in enumerate(required_cost_control_ids(field_input)):
        label = row_control_label(field_input, control_id)
        year = f" ({row.start_year + offset})" if row.start_year is not None else ""
        labels.append((control_id, f"{label}{year}"))
    return labels


# --- Calculations ------------------------------------------------------------


def compute_row_total(
    field_input: WorksheetInput, row_values: Mapping[str, str] | None
) -> float:
    """The sum of a row's cost controls; blank and invalid cells count as zero."""
    values = row_values or {}
    total = 0.0
    for control_id in field_input.row_total.sum:
        total += to_amount(values.get(control_id))
    return total


def counted_rows(rows: Sequence[WorksheetRow]) -> list[WorksheetRow]:
    """The rows counted in every total: those with a start date.

    A row without a start date has its cost inputs disabled, so any values
    stored against it are stale and must not inflate the totals. Category
    validity is deliberately not part of this filter: entered costs on a
    dated row always count, and invalid categories block evaluation instead.
    """
    return [row for row in rows if row.has_start_date]


def compute_grand_total(
    field_input: WorksheetInput, rows: Sequence[WorksheetRow], answer: WorksheetAnswer
) -> float:
    """The sum of every counted row's total."""
    total = 0.0
    for row in counted_rows(rows):
        total += compute_row_total(field_input, get_row_values(answer, row.row_id))
    return total


@dataclass(frozen=True, slots=True)
class SummaryColumn:
    """One displayed summary column: a summed cost control."""

    id: str
    label: str


@dataclass(frozen=True, slots=True)
class SummaryRow:
    """One category row of the summary, or the closing total row."""

    category: str
    label: str
    is_total: bool
    per_column: dict[str, float]
    total: float


@dataclass(frozen=True, slots=True)
class CategorySummary:
    """The category summary table."""

    columns: list[SummaryColumn]
    rows: list[SummaryRow]
    grand_total: float


def compute_category_summary(
    field_input: WorksheetInput, rows: Sequence[WorksheetRow], answer: WorksheetAnswer
) -> CategorySummary:
    """One row per category option (in option order) summing every counted
    row in that category per cost column, plus an optional total row.

    The columns are exactly the controls summed into the row total, optional
    ones included, so each row's cells reconcile to its total.
    """
    group_by = field_input.summary.group_by
    counted = counted_rows(rows)
    columns = [
        SummaryColumn(id=control_id, label=row_control_label(field_input, control_id))
        for control_id in field_input.row_total.sum
    ]

    summary_rows: list[SummaryRow] = []
    grand_total = 0.0
    for option in category_options(field_input):
        per_column = {column.id: 0.0 for column in columns}
        total = 0.0
        for row in counted:
            values = get_row_values(answer, row.row_id)
            if values.get(group_by, "") != option.value:
                continue
            for column in columns:
                per_column[column.id] += to_amount(values.get(column.id))
            total += compute_row_total(field_input, values)
        grand_total += total
        summary_rows.append(
            SummaryRow(
                category=option.value,
                label=option.label,
                is_total=False,
                per_column=per_column,
                total=total,
            )
        )

    if field_input.summary.include_total_row:
        column_totals: dict[str, float] = {}
        for column in columns:
            column_total = 0.0
            for summary_row in summary_rows:
                column_total += summary_row.per_column.get(column.id, 0.0)
            column_totals[column.id] = column_total
        summary_rows.append(
            SummaryRow(
                category="",
                label="Total",
                is_total=True,
                per_column=column_totals,
                total=grand_total,
            )
        )

    return CategorySummary(columns=columns, rows=summary_rows, grand_total=grand_total)


# --- Validation --------------------------------------------------------------

WorksheetIssueKind = Literal[
    "no_rows",
    "missing_row_id",
    "duplicate_row_id",
    "missing_start_date",
    "missing_category",
    "invalid_category",
    "missing_value",
    "invalid_value",
    "negative_value",
    "missing_narrative",
]


@dataclass(frozen=True, slots=True)
class WorksheetIssue:
    """One worksheet validation problem with optional locators."""

    kind: WorksheetIssueKind
    message: str
    row_id: str | None = None
    row_label: str | None = None
    control_id: str | None = None
    narrative_id: str | None = None


def _row_name(row: WorksheetRow) -> str:
    label = js_trim(row.label)
    return label if label else "this item"


def _row_identity_issue(
    row: WorksheetRow, seen_row_ids: set[str], source_ref: str
) -> WorksheetIssue | None:
    """The issue that stops a row's costs from being entered: no row id, a
    duplicate row id, or no start date. Records the row id as seen."""
    name = _row_name(row)
    if js_trim(row.row_id) == "":
        return WorksheetIssue(
            kind="missing_row_id",
            row_label=row.label,
            message=(
                f'"{name}" has no stable row id in {source_ref}, so its costs '
                f"cannot be recorded reliably. Re-add the item in {source_ref}."
            ),
        )
    if row.row_id in seen_row_ids:
        return WorksheetIssue(
            kind="duplicate_row_id",
            row_id=row.row_id,
            row_label=row.label,
            message=(
                f'"{name}" shares a row id with another row; row ids '
                f"must be unique. Re-add the duplicate item in {source_ref}."
            ),
        )
    seen_row_ids.add(row.row_id)
    if not row.has_start_date:
        return WorksheetIssue(
            kind="missing_start_date",
            row_id=row.row_id,
            row_label=row.label,
            message=(
                f'"{name}" has no start date in {source_ref}. Add a start '
                "date for it there before entering its costs."
            ),
        )
    return None


def _control_issue(
    control: Control,
    raw: str | None,
    *,
    name: str,
    is_optional: bool,
    is_category: bool,
) -> tuple[WorksheetIssueKind, str] | None:
    """The kind and message of the problem with one row control's value."""
    trimmed = trim_or_empty(raw)
    if isinstance(control, NumberControl):
        if trimmed == "":
            return (
                None
                if is_optional
                else (
                    "missing_value",
                    f'Enter {control.label} for "{name}".',
                )
            )
        parsed = parse_amount(raw)
        if not isinstance(parsed, RejectedAmount):
            return None
        if parsed.reason == "negative":
            return "negative_value", f'{control.label} for "{name}" cannot be negative.'
        return "invalid_value", f'{control.label} for "{name}" must be a number.'

    if isinstance(control, SelectControl):
        if trimmed == "":
            if is_optional:
                return None
            if is_category:
                return "missing_category", f'Select a cost category for "{name}".'
            return "missing_value", f'Choose {control.label} for "{name}".'
        if any(option.value == trimmed for option in control.options):
            return None
        if is_category:
            return "invalid_category", f'Select a valid cost category for "{name}".'
        return "invalid_value", f'{control.label} for "{name}" is not a valid option.'

    if trimmed == "" and not is_optional:
        return "missing_value", f'Enter {control.label} for "{name}".'
    return None


def _row_control_issues(
    field_input: WorksheetInput, row: WorksheetRow, values: Mapping[str, str]
) -> list[WorksheetIssue]:
    """Problems with a dated row's entered values, in control order."""
    optional = set(field_input.optional_row_controls or [])
    issues: list[WorksheetIssue] = []
    for control in field_input.row_controls:
        problem = _control_issue(
            control,
            values.get(control.id),
            name=_row_name(row),
            is_optional=control.id in optional,
            is_category=control.id == field_input.summary.group_by,
        )
        if problem is not None:
            kind, message = problem
            issues.append(
                WorksheetIssue(
                    kind=kind,
                    message=message,
                    row_id=row.row_id,
                    row_label=row.label,
                    control_id=control.id,
                )
            )
    return issues


def _narrative_issues(
    field_input: WorksheetInput, answer: WorksheetAnswer
) -> list[WorksheetIssue]:
    """One issue per blank narrative; every narrative is required."""
    return [
        WorksheetIssue(
            kind="missing_narrative",
            narrative_id=narrative.id,
            message=f"{narrative.label} is required.",
        )
        for narrative in field_input.narrative_fields
        if trim_or_empty(answer["narratives"].get(narrative.id)) == ""
    ]


def validate_worksheet(
    field_input: WorksheetInput,
    rows: Sequence[WorksheetRow],
    answer: WorksheetAnswer,
    source_field_number: str | None = None,
) -> list[WorksheetIssue]:
    """Validate a worksheet answer against its derived rows.

    Every source row needs a unique row id and a start date; every dated row
    needs a valid category and a non-negative number for each required cost
    control (optional controls may be blank); every narrative is required.
    A row with an identity problem reports only that.
    """
    source_ref = (
        "the source list"
        if source_field_number is None
        else f"section {source_field_number}"
    )
    if not rows:
        return [
            WorksheetIssue(
                kind="no_rows",
                message=(
                    f"Add at least one item in {source_ref} before "
                    "completing the cost worksheet."
                ),
            )
        ]

    issues: list[WorksheetIssue] = []
    seen_row_ids: set[str] = set()
    for row in rows:
        identity_issue = _row_identity_issue(row, seen_row_ids, source_ref)
        if identity_issue is not None:
            issues.append(identity_issue)
            continue
        values = get_row_values(answer, row.row_id)
        issues.extend(_row_control_issues(field_input, row, values))
    issues.extend(_narrative_issues(field_input, answer))
    return issues


# --- Serialization -----------------------------------------------------------


def _source_context(
    source_field: TemplateField, source_rows: Sequence[Mapping[str, str | None]]
) -> list[str]:
    controls = (
        source_field.input.fields if isinstance(source_field.input, ListInput) else []
    )
    lines = [f"Section {source_field.number} components (project scope context):"]
    if not source_rows:
        lines.append("  (no components listed)")
        return lines
    for index, item in enumerate(source_rows):
        parts = [
            f"{control.label}: {js_to_string(item.get(control.id))}"
            for control in controls
            if control.id != ROW_ID_KEY
        ]
        lines.append(f"  {index + 1}. {' | '.join(parts)}")
    return lines


def serialize_worksheet_answer(
    field_input: WorksheetInput,
    source_field: TemplateField,
    source_rows: Sequence[Mapping[str, str | None]],
    rows: Sequence[WorksheetRow],
    answer: WorksheetAnswer,
) -> str:
    """The evaluator text: intro, source components, per-component costs with
    calendar-year labels, category summary, grand total and narratives."""
    blocks: list[str] = [
        WORKSHEET_INTRO,
        "\n".join(_source_context(source_field, source_rows)),
    ]

    component_lines = ["Cost estimate by component:"]
    for row in rows:
        values = get_row_values(answer, row.row_id)
        category = category_label(
            field_input, values.get(field_input.summary.group_by, "")
        )
        component_lines.append("")
        component_lines.append(
            f"{row.label or '(unnamed component)'} — category: "
            f"{category or '(none selected)'}"
        )
        if not row.has_start_date:
            component_lines.append(
                f"  (no start date in section {source_field.number} — "
                "costs not entered)"
            )
            continue
        for control_id, label in year_labels(field_input, row):
            amount = format_amount(to_amount(values.get(control_id)))
            component_lines.append(f"  {label}: {amount}")
        for control_id in field_input.optional_row_controls or []:
            amount = format_amount(to_amount(values.get(control_id)))
            component_lines.append(
                f"  {row_control_label(field_input, control_id)}: {amount}"
            )
        row_total = format_amount(compute_row_total(field_input, values))
        component_lines.append(f"  {field_input.row_total.label}: {row_total}")
    blocks.append("\n".join(component_lines))

    summary = compute_category_summary(field_input, rows, answer)
    summary_lines = ["Summary by expenditure category:"]
    for summary_row in summary.rows:
        cells = "  ".join(
            f"{column.label}: "
            f"{format_amount(summary_row.per_column.get(column.id, 0.0))}"
            for column in summary.columns
        )
        summary_lines.append(
            f"  {summary_row.label}: {cells}  {field_input.row_total.label}: "
            f"{format_amount(summary_row.total)}"
        )
    blocks.append("\n".join(summary_lines))

    grand_total = format_amount(compute_grand_total(field_input, rows, answer))
    blocks.append(f"Grand total: {grand_total}")

    for narrative in field_input.narrative_fields:
        value = trim_or_empty(answer["narratives"].get(narrative.id))
        blocks.append(f"{narrative.label}\n{value or '(no answer provided)'}")

    return "\n\n".join(blocks)


# --- Preparation -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PreparedWorksheet:
    """A worksheet answer prepared for evaluation: text, rows and grand total
    when valid; issues otherwise."""

    ok: bool
    answer_text: str | None = None
    rows: tuple[WorksheetRow, ...] = ()
    grand_total: float | None = None
    issues: tuple[WorksheetIssue, ...] = ()


def prepare_worksheet(
    worksheet_field: TemplateField,
    source_field: TemplateField,
    source_answer: Any,
    worksheet_answer: Any,
) -> PreparedWorksheet:
    """Derive rows, validate and (when valid) serialize a worksheet answer."""
    field_input = worksheet_field.input
    if not isinstance(field_input, WorksheetInput):
        raise TypeError(
            f'prepare_worksheet called for non-worksheet field "{worksheet_field.id}".'
        )
    source_rows: list[Record] = coerce_string_record_array(source_answer)
    answer = coerce_worksheet_answer(worksheet_answer)
    rows = derive_worksheet_rows(field_input, source_rows)

    issues = validate_worksheet(field_input, rows, answer, source_field.number)
    if issues:
        return PreparedWorksheet(ok=False, issues=tuple(issues))

    return PreparedWorksheet(
        ok=True,
        answer_text=serialize_worksheet_answer(
            field_input, source_field, source_rows, rows, answer
        ),
        rows=tuple(rows),
        grand_total=compute_grand_total(field_input, rows, answer),
    )
