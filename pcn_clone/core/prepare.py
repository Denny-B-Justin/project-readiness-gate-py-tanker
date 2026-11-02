"""The field-kind dispatcher: one entry point that turns any field's answer
into the text the evaluator grades, or the issues that block evaluation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from pcn_clone.content.models import (
    AnswerLike,
    ListInput,
    ScenarioComparisonInput,
    StaticTableInput,
    Template,
    WorksheetInput,
    answer_parts,
)
from pcn_clone.core.fields import prepare_list, serialize_field_answer
from pcn_clone.core.scenario import prepare_scenario_comparison
from pcn_clone.core.static_table import prepare_static_table
from pcn_clone.core.worksheet import prepare_worksheet


class _HasMessage(Protocol):
    @property
    def message(self) -> str: ...


class _Prepared(Protocol):
    @property
    def ok(self) -> bool: ...

    @property
    def answer_text(self) -> str | None: ...

    @property
    def issues(self) -> tuple[_HasMessage, ...]: ...


@dataclass(frozen=True, slots=True)
class PrepareResult:
    """A prepared answer: ``answer_text`` when ``ok``, otherwise the blocking
    ``issues`` (human-readable messages, in validator order)."""

    ok: bool
    answer_text: str | None = None
    issues: tuple[str, ...] = ()


def find_context_answer(
    context: Iterable[AnswerLike] | None, section_id: str, field_id: str
) -> Any:
    """The first context answer for a field, or ``None`` when absent."""
    for entry in context or ():
        entry_section, entry_field, answer = answer_parts(entry)
        if entry_section == section_id and entry_field == field_id:
            return answer
    return None


def _from_prepared(prepared: _Prepared) -> PrepareResult:
    if prepared.ok:
        return PrepareResult(ok=True, answer_text=prepared.answer_text)
    return PrepareResult(
        ok=False, issues=tuple(issue.message for issue in prepared.issues)
    )


def prepare_field_answer(
    template: Template,
    section_id: str,
    field_id: str,
    answer: Any,
    context: Iterable[AnswerLike] | None = None,
) -> PrepareResult:
    """Prepare the answer to the field ``section_id/field_id``, routing by
    input kind.

    A worksheet also reads its row-source list from ``context`` (the other
    answers of the submission); lists, scenario comparisons and static tables
    are validated before serializing; every other kind serializes directly.
    Raises ``LookupError`` when the template has no such field.
    """
    field = template.get_field(section_id, field_id)
    if field is None:
        raise LookupError(
            f'Template "{template.id}" has no field "{section_id}/{field_id}".'
        )
    field_input = field.input

    if isinstance(field_input, WorksheetInput):
        source = field_input.row_source
        source_field = template.get_field(source.section_id, source.field_id)
        if source_field is None:
            return PrepareResult(
                ok=False,
                issues=(
                    (
                        f'Row source field "{source.section_id}/{source.field_id}" '
                        "is missing from the template."
                    ),
                ),
            )
        source_answer = find_context_answer(context, source.section_id, source.field_id)
        return _from_prepared(
            prepare_worksheet(field, source_field, source_answer, answer)
        )
    if isinstance(field_input, ScenarioComparisonInput):
        return _from_prepared(prepare_scenario_comparison(field, answer))
    if isinstance(field_input, StaticTableInput):
        return _from_prepared(prepare_static_table(field, answer))
    if isinstance(field_input, ListInput):
        return _from_prepared(prepare_list(field, answer))
    return PrepareResult(ok=True, answer_text=serialize_field_answer(field, answer))
