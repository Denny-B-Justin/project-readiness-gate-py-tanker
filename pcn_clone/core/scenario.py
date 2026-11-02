"""The scenario-comparison field: entered rows across fixed columns, derived
``left - right`` rows, an optional applicability gate and narratives.

A blank cell is absent, never zero: a derived cell exists only when both of
its source cells are present and valid. When the gate's answer is not its
active value the numeric rows are inert: not required, not validated, not
computed and left out of the serialized text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from pcn_clone.content.models import (
    ScenarioComparisonInput,
    ScenarioComputedRow,
    TemplateField,
    is_scenario_comparison_answer,
)
from pcn_clone.core.jsstr import trim_or_empty
from pcn_clone.core.numbers import (
    ParsedAmount,
    RejectedAmount,
    format_amount,
    parse_scenario_amount,
)

NOT_APPLICABLE_STATEMENT = (
    "The proposer indicated this is not applicable; no scenario figures are "
    "expected for this field."
)
"""The line that replaces the table when the gate is inactive."""

ScenarioComparisonAnswer = dict[str, Any]
"""``{"applicability"?: {id: str}, "rows": {row: {column: str}},
"narratives": {id: str}}``."""


def empty_scenario_comparison_answer() -> ScenarioComparisonAnswer:
    """A scenario-comparison answer with no entered values."""
    return {"rows": {}, "narratives": {}}


def coerce_scenario_comparison_answer(value: Any) -> ScenarioComparisonAnswer:
    """The answer itself when it has the exact scenario-comparison shape;
    otherwise an empty answer."""
    if is_scenario_comparison_answer(value):
        return cast(ScenarioComparisonAnswer, value)
    return empty_scenario_comparison_answer()


def get_cell(
    answer: ScenarioComparisonAnswer, row_id: str, column_id: str
) -> str | None:
    """The raw entered value for one cell, if any."""
    row: dict[str, str] | None = answer["rows"].get(row_id)
    return None if row is None else row.get(column_id)


def get_applicability_value(
    field_input: ScenarioComparisonInput, answer: ScenarioComparisonAnswer
) -> str | None:
    """The gate's current answer, or ``None`` when there is no gate or answer."""
    gate = field_input.applicability
    if gate is None:
        return None
    applicability: dict[str, str] | None = answer.get("applicability")
    return None if applicability is None else applicability.get(gate.id)


def is_applicable(
    field_input: ScenarioComparisonInput, answer: ScenarioComparisonAnswer
) -> bool:
    """True when there is no gate, or the gate's answer equals its active
    value exactly (no trimming, case-sensitive)."""
    gate = field_input.applicability
    if gate is None:
        return True
    return get_applicability_value(field_input, answer) == gate.active_value


def compute_computed_cell(
    answer: ScenarioComparisonAnswer, computed_row: ScenarioComputedRow, column_id: str
) -> float | None:
    """``left - right`` for one column, or ``None`` (not computable) unless
    both cells are present and valid."""
    left_id, right_id = computed_row.subtract
    left = parse_scenario_amount(get_cell(answer, left_id, column_id))
    right = parse_scenario_amount(get_cell(answer, right_id, column_id))
    if isinstance(left, ParsedAmount) and isinstance(right, ParsedAmount):
        return left.value - right.value
    return None


# --- Validation --------------------------------------------------------------

ScenarioComparisonIssueKind = Literal[
    "missing_applicability",
    "invalid_applicability",
    "missing_value",
    "invalid_value",
    "negative_value",
    "missing_narrative",
]


@dataclass(frozen=True, slots=True)
class ScenarioComparisonIssue:
    """One scenario-comparison validation problem with optional locators."""

    kind: ScenarioComparisonIssueKind
    message: str
    row_id: str | None = None
    row_label: str | None = None
    column_id: str | None = None
    narrative_id: str | None = None
    applicability_id: str | None = None


def _gate_issues(
    field_input: ScenarioComparisonInput, answer: ScenarioComparisonAnswer
) -> list[ScenarioComparisonIssue]:
    gate = field_input.applicability
    if gate is None:
        return []
    value = trim_or_empty(get_applicability_value(field_input, answer))
    if value == "":
        return [
            ScenarioComparisonIssue(
                kind="missing_applicability",
                applicability_id=gate.id,
                message=f"{gate.label} is required.",
            )
        ]
    if not any(option.value == value for option in gate.options):
        return [
            ScenarioComparisonIssue(
                kind="invalid_applicability",
                applicability_id=gate.id,
                message=f'Select a valid option for "{gate.label}".',
            )
        ]
    return []


def _row_issues(
    field_input: ScenarioComparisonInput, answer: ScenarioComparisonAnswer
) -> list[ScenarioComparisonIssue]:
    required = set(field_input.required_rows or [])
    issues: list[ScenarioComparisonIssue] = []
    for row in field_input.entered_rows:
        for column in field_input.columns:
            parsed = parse_scenario_amount(get_cell(answer, row.id, column.id))
            locators = {
                "row_id": row.id,
                "row_label": row.label,
                "column_id": column.id,
            }
            if parsed is None:
                if row.id in required:
                    issues.append(
                        ScenarioComparisonIssue(
                            kind="missing_value",
                            message=f"Enter {row.label} for {column.label}.",
                            **locators,
                        )
                    )
            elif isinstance(parsed, RejectedAmount):
                negative = parsed.reason == "negative"
                issues.append(
                    ScenarioComparisonIssue(
                        kind="negative_value" if negative else "invalid_value",
                        message=(
                            f"{row.label} for {column.label} cannot be negative."
                            if negative
                            else f"{row.label} for {column.label} must be a number."
                        ),
                        **locators,
                    )
                )
    return issues


def validate_scenario_comparison(
    field_input: ScenarioComparisonInput, answer: ScenarioComparisonAnswer
) -> list[ScenarioComparisonIssue]:
    """Validate a scenario-comparison answer.

    The gate, when present, must hold one of its options (compared after
    trimming). When applicable, required rows need a value in every column
    and every entered value must be a non-negative number. Narratives are
    always required.
    """
    issues = _gate_issues(field_input, answer)
    if is_applicable(field_input, answer):
        issues.extend(_row_issues(field_input, answer))
    for narrative in field_input.narrative_fields:
        if trim_or_empty(answer["narratives"].get(narrative.id)) == "":
            issues.append(
                ScenarioComparisonIssue(
                    kind="missing_narrative",
                    narrative_id=narrative.id,
                    message=f"{narrative.label} is required.",
                )
            )
    return issues


# --- Serialization -----------------------------------------------------------


def _narrative_block(label: str, value: str | None) -> str:
    return f"{label}\n{trim_or_empty(value) or '(no answer provided)'}"


def _entered_cell(raw: str | None) -> str:
    parsed = parse_scenario_amount(raw)
    if parsed is None:
        return "(not provided)"
    if isinstance(parsed, RejectedAmount):
        return "(invalid)"
    return format_amount(parsed.value)


def serialize_scenario_comparison_answer(
    field_input: ScenarioComparisonInput, answer: ScenarioComparisonAnswer
) -> str:
    """The evaluator text: the gate answer (by option label), then either the
    non-applicability statement or a pipe-delimited table of entered and
    derived rows, then the narratives."""
    blocks: list[str] = []

    gate = field_input.applicability
    if gate is not None:
        value = trim_or_empty(get_applicability_value(field_input, answer))
        option = next((o for o in gate.options if o.value == value), None)
        blocks.append(f"{gate.label}\n{option.label if option is not None else value}")

    narratives = [
        _narrative_block(narrative.label, answer["narratives"].get(narrative.id))
        for narrative in field_input.narrative_fields
    ]
    if not is_applicable(field_input, answer):
        return "\n\n".join([*blocks, NOT_APPLICABLE_STATEMENT, *narratives])

    lines = [
        " | ".join(["Scenario", *(column.label for column in field_input.columns)])
    ]
    for row in field_input.entered_rows:
        cells = [
            _entered_cell(get_cell(answer, row.id, column.id))
            for column in field_input.columns
        ]
        lines.append(" | ".join([row.label, *cells]))
    for computed in field_input.computed_rows:
        derived = [
            compute_computed_cell(answer, computed, column.id)
            for column in field_input.columns
        ]
        cells = [
            "(not computable)" if cell is None else format_amount(cell)
            for cell in derived
        ]
        lines.append(" | ".join([computed.label, *cells]))

    return "\n\n".join([*blocks, "\n".join(lines), *narratives])


# --- Preparation -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PreparedScenarioComparison:
    """A scenario-comparison answer prepared for evaluation."""

    ok: bool
    answer_text: str | None = None
    issues: tuple[ScenarioComparisonIssue, ...] = ()


def prepare_scenario_comparison(
    field: TemplateField, answer: Any
) -> PreparedScenarioComparison:
    """Coerce, validate and (when valid) serialize a scenario-comparison answer."""
    field_input = field.input
    if not isinstance(field_input, ScenarioComparisonInput):
        raise TypeError(
            "prepare_scenario_comparison called for non-scenario-comparison "
            f'field "{field.id}".'
        )
    coerced = coerce_scenario_comparison_answer(answer)
    issues = validate_scenario_comparison(field_input, coerced)
    if issues:
        return PreparedScenarioComparison(ok=False, issues=tuple(issues))
    return PreparedScenarioComparison(
        ok=True,
        answer_text=serialize_scenario_comparison_answer(field_input, coerced),
    )
