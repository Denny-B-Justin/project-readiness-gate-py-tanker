"""Answers for plain, ``group`` and ``list`` fields.

A plain field's answer is a string; a group's is a control-id → value
record; a list's is an array of such records, each optionally carrying a
durable ``_rowId``. This module coerces untrusted row-shaped answers,
validates lists (required controls, authored select options, conditional
requirements) and serializes all three kinds to evaluator text.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, assert_never

from pcn_clone.content.models import (
    Control,
    GroupInput,
    ListConditionalRequirement,
    ListInput,
    ProductGteCondition,
    SelectControl,
    TemplateField,
)
from pcn_clone.core.jsstr import (
    as_double,
    js_to_string,
    js_trim,
    number_to_string,
    trim_or_empty,
)
from pcn_clone.core.numbers import js_number

Record = dict[str, str | None]
"""A coerced record: control id → string, or ``None`` for an absent value."""

PLAIN_KINDS = frozenset({"text", "textarea", "group", "list"})
"""Field kinds serialized by :func:`serialize_field_answer`."""


# --- Coercion ----------------------------------------------------------------


def coerce_cell_value(value: Any) -> str | None:
    """Normalise one untrusted cell value to a string or ``None``.

    Strings pass through; finite numbers and booleans are stringified as
    JavaScript would; everything else (null, non-finite numbers, objects,
    arrays) has no faithful string form and becomes ``None``.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        number = as_double(value)
        return number_to_string(number) if math.isfinite(number) else None
    return None


def _coerce_record(item: Mapping[Any, Any]) -> Record:
    return {str(key): coerce_cell_value(value) for key, value in item.items()}


def coerce_string_record_array(value: Any) -> list[Record]:
    """Coerce an untrusted value into a list of string-valued records.

    A non-list becomes ``[]``; items that are not objects are dropped; every
    retained item keeps all its keys with values normalised by
    :func:`coerce_cell_value`.
    """
    if not isinstance(value, list):
        return []
    return [_coerce_record(item) for item in value if isinstance(item, Mapping)]


def cell_text(record: Mapping[str, str | None], key: str) -> str:
    """A coerced record's value for ``key``; absent reads as ``""``."""
    value = record.get(key)
    return "" if value is None else value


# --- Serialization -----------------------------------------------------------


def serialize_record(record: Any, controls: Sequence[Control]) -> str:
    """One child-set as ``label: value`` lines in control order; a value that
    is not a record renders every control blank."""
    values: Mapping[str, Any] = record if isinstance(record, Mapping) else {}
    return "\n".join(
        f"{control.label}: {js_to_string(values.get(control.id))}"
        for control in controls
    )


def serialize_field_answer(field: TemplateField, value: Any) -> str:
    """Convert a plain, group or list answer to the evaluator's text.

    A string is already answer text, whatever the field kind. A group renders
    as ``label: value`` lines; a list renders each item as an ``Item N`` block,
    blocks separated by a blank line. Composite kinds with dedicated
    serializers, and values of the wrong shape, render as ``""``.
    """
    if field.kind not in PLAIN_KINDS:
        return ""
    if isinstance(value, str):
        return value
    field_input = field.input
    if isinstance(field_input, GroupInput) and isinstance(value, Mapping):
        return serialize_record(value, field_input.fields)
    if isinstance(field_input, ListInput) and isinstance(value, list):
        return "\n\n".join(
            f"Item {index + 1}\n{serialize_record(item, field_input.fields)}"
            for index, item in enumerate(value)
        )
    return ""


# --- List validation ---------------------------------------------------------

ListIssueKind = Literal["empty_list", "missing_value", "invalid_value"]


@dataclass(frozen=True, slots=True)
class ListIssue:
    """One list validation problem, located by item index and control id."""

    kind: ListIssueKind
    message: str
    item_index: int | None = None
    control_id: str | None = None


def _as_finite_number(value: str | None) -> float | None:
    trimmed = trim_or_empty(value)
    if trimmed == "":
        return None
    parsed = js_number(trimmed)
    return parsed if math.isfinite(parsed) else None


def is_condition_met(
    rule: ListConditionalRequirement, item: Mapping[str, str | None]
) -> bool:
    """True when the rule's condition holds for this item, making its target
    required. A blank or non-numeric factor leaves the condition unmet."""
    when = rule.when
    if isinstance(when, ProductGteCondition):
        product = 1.0
        for factor_id in when.factors:
            number = _as_finite_number(item.get(factor_id))
            if number is None:
                return False
            product *= number
        return product >= when.threshold
    assert_never(when)


def _control_label(control: Control) -> str:
    return js_trim(control.label) or control.id


def validate_list(
    field_input: ListInput, items: Sequence[Mapping[str, str | None]] | None
) -> list[ListIssue]:
    """Validate a coerced list answer.

    An empty list yields one ``empty_list`` issue. Otherwise, per item and
    control in order: a non-blank select value outside its options is
    ``invalid_value``; a required control left blank is ``missing_value``.
    Controls are required unless they are a conditional rule's target, in
    which case they are required only when the rule's condition is met.
    """
    if not items:
        return [
            ListIssue(
                kind="empty_list",
                message="Add at least one item before evaluating.",
            )
        ]

    rules_by_target = {
        rule.target: rule for rule in field_input.conditional_requirements
    }
    issues: list[ListIssue] = []
    for item_index, item in enumerate(items):
        human_item = item_index + 1
        for control in field_input.fields:
            value = js_trim(cell_text(item, control.id))
            if (
                isinstance(control, SelectControl)
                and value != ""
                and not any(option.value == value for option in control.options)
            ):
                issues.append(
                    ListIssue(
                        kind="invalid_value",
                        item_index=item_index,
                        control_id=control.id,
                        message=(
                            f"Item {human_item} — {_control_label(control)}: "
                            "is not a valid option."
                        ),
                    )
                )
                continue
            rule = rules_by_target.get(control.id)
            required = is_condition_met(rule, item) if rule is not None else True
            if required and value == "":
                issues.append(
                    ListIssue(
                        kind="missing_value",
                        item_index=item_index,
                        control_id=control.id,
                        message=(
                            f"Item {human_item} — {_control_label(control)}: "
                            "required value is missing."
                        ),
                    )
                )
    return issues


def is_control_required_for_item(
    field_input: ListInput, control_id: str, item: Mapping[str, str | None]
) -> bool:
    """Whether a control is currently required for an item (always, unless it
    is a conditional rule's target)."""
    rule = next(
        (r for r in field_input.conditional_requirements if r.target == control_id),
        None,
    )
    return True if rule is None else is_condition_met(rule, item)


@dataclass(frozen=True, slots=True)
class PreparedList:
    """A list answer prepared for evaluation: text when valid, issues otherwise."""

    ok: bool
    answer_text: str | None = None
    issues: tuple[ListIssue, ...] = ()


def prepare_list(field: TemplateField, answer: Any) -> PreparedList:
    """Coerce, validate and (when valid) serialize a list answer."""
    field_input = field.input
    if not isinstance(field_input, ListInput):
        raise TypeError(f'prepare_list called for non-list field "{field.id}".')
    items = coerce_string_record_array(answer)
    issues = validate_list(field_input, items)
    if issues:
        return PreparedList(ok=False, issues=tuple(issues))
    return PreparedList(ok=True, answer_text=serialize_field_answer(field, items))


# --- Completeness ------------------------------------------------------------


def _is_non_blank(value: Any) -> bool:
    return isinstance(value, str) and js_trim(value) != ""


def is_field_answer_complete(field: TemplateField, value: Any) -> bool:
    """Whether a plain, group or list answer is complete enough to evaluate.

    A plain answer is a non-blank string; a group needs every control
    non-blank; a list is complete when it has no validation issues, an item
    that is not a record counting as a record with every control blank.
    Composite kinds are judged by their own validators and report ``False``.
    """
    field_input = field.input
    if isinstance(field_input, GroupInput):
        return isinstance(value, Mapping) and all(
            _is_non_blank(value.get(control.id)) for control in field_input.fields
        )
    if isinstance(field_input, ListInput):
        if not isinstance(value, list):
            return False
        items = [
            _coerce_record(item) if isinstance(item, Mapping) else {} for item in value
        ]
        return not validate_list(field_input, items)
    if field.kind not in ("text", "textarea"):
        return False
    return _is_non_blank(value)
