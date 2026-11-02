"""Whole-submission serialization and the assessment input digest.

A submission is first canonicalized (exactly one answer per template field,
in template order, blanks filled), then each answer is reduced to text with
the per-field preparer. A blank answer renders ``No answer provided.``; a
structurally invalid composite renders its validation issues. Nothing is
silently dropped.

The input digest is ``aiv1-`` plus the SHA-256 of the JSON encoding of the
ordered ``[fieldId, serializedText]`` pairs, byte-compatible with
JavaScript's ``JSON.stringify``.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pcn_clone.content.models import (
    ROW_ID_KEY,
    SubmissionLike,
    Template,
    TemplateField,
    submission_parts,
)
from pcn_clone.core.jsstr import js_json_stringify, js_trim
from pcn_clone.core.prepare import prepare_field_answer
from pcn_clone.core.scenario import empty_scenario_comparison_answer
from pcn_clone.core.static_table import empty_static_table_answer
from pcn_clone.core.worksheet import empty_worksheet_answer

NO_ANSWER_MARKER = "No answer provided."
"""The text of a field the submission leaves blank."""

INVALID_ANSWER_HEADER = "This answer is structurally invalid and could not be rendered:"
"""The first line of the marker for a structurally invalid composite answer."""

ASSESSMENT_INPUT_DIGEST_PREFIX = "aiv1-"
"""The domain prefix of the assessment input digest."""

CanonicalSubmission = dict[str, Any]
"""``{"templateId": str, "answers": [{"sectionId", "fieldId", "answer"}, ...]}``,
the answers being private copies."""


class SubmissionError(ValueError):
    """A submission does not belong to, or is not canonical for, its template."""


@dataclass(frozen=True, slots=True)
class SerializedField:
    """One serialized field: ids, display labels and the exact text."""

    section_id: str
    section_label: str
    field_id: str
    field_label: str
    serialized_text: str


def check_submission_consistency(
    template: Template, submission: SubmissionLike
) -> list[str]:
    """Problems that stop a submission from belonging to the template: a
    foreign template id, an unknown field, or a field answered twice. Empty
    when consistent; problems appear in answer order."""
    template_id, answers = submission_parts(submission)
    problems: list[str] = []
    if template_id != template.id:
        problems.append(
            f'Submission targets template "{template_id}", but is paired '
            f'with template "{template.id}".'
        )
    seen: set[str] = set()
    for section_id, field_id, _ in answers:
        key = f"{section_id}/{field_id}"
        if template.get_field(section_id, field_id) is None:
            problems.append(
                f'Answer references unknown field "{key}" — not in the template.'
            )
        if key in seen:
            problems.append(f'Field "{key}" is answered more than once.')
        else:
            seen.add(key)
    return problems


def blank_answer_value(field: TemplateField) -> Any:
    """The explicit blank answer for a field, by input kind."""
    kind = field.kind
    if kind == "group":
        return {}
    if kind == "list":
        return []
    if kind == "worksheet":
        return empty_worksheet_answer()
    if kind == "scenario_comparison":
        return empty_scenario_comparison_answer()
    if kind == "static_table":
        return empty_static_table_answer()
    return ""


def canonicalize_submission(
    template: Template, submission: SubmissionLike
) -> CanonicalSubmission:
    """Exactly one answer per template field, in template order, with
    unanswered fields completed as explicit blanks. Answers are deep copies,
    so the result can be edited without touching the source submission.

    Raises ``SubmissionError`` when the submission is inconsistent with the
    template.
    """
    problems = check_submission_consistency(template, submission)
    if problems:
        raise SubmissionError(
            "Cannot canonicalize an inconsistent submission:\n"
            + "\n".join(f"  - {problem}" for problem in problems)
        )
    _, answers = submission_parts(submission)
    by_key = {
        f"{section_id}/{field_id}": answer for section_id, field_id, answer in answers
    }
    canonical: list[dict[str, Any]] = []
    for section, field in template.iter_fields():
        key = f"{section.id}/{field.id}"
        canonical.append(
            {
                "sectionId": section.id,
                "fieldId": field.id,
                "answer": copy.deepcopy(by_key[key])
                if key in by_key
                else blank_answer_value(field),
            }
        )
    return {"templateId": template.id, "answers": canonical}


def is_blank_answer_value(value: Any) -> bool:
    """True for ``None``, a whitespace-only string, or a container whose every
    value (ignoring ``_rowId``) is itself blank; empty containers are blank."""
    if value is None:
        return True
    if isinstance(value, str):
        return js_trim(value) == ""
    if isinstance(value, list):
        return all(is_blank_answer_value(item) for item in value)
    if isinstance(value, Mapping):
        return all(
            key == ROW_ID_KEY or is_blank_answer_value(child)
            for key, child in value.items()
        )
    return False


def invalid_answer_marker(issues: Iterable[str]) -> str:
    """The marker rendered in place of a structurally invalid composite."""
    return INVALID_ANSWER_HEADER + "\n" + "\n".join(f"- {issue}" for issue in issues)


def _field_text(
    template: Template,
    section_id: str,
    field_id: str,
    answer: Any,
    context: list[dict[str, Any]],
) -> str:
    if is_blank_answer_value(answer):
        return NO_ANSWER_MARKER
    prepared = prepare_field_answer(template, section_id, field_id, answer, context)
    if not prepared.ok:
        return invalid_answer_marker(prepared.issues)
    text = prepared.answer_text or ""
    return text if js_trim(text) != "" else NO_ANSWER_MARKER


def serialize_submission(
    template: Template, submission: SubmissionLike
) -> list[SerializedField]:
    """Serialize a canonical submission into per-field text, in template order.

    Raises ``SubmissionError`` when the submission targets another template
    or is not canonical (a field missing, answered twice, or displaced by an
    answer to a field outside the template).
    """
    template_id, answers = submission_parts(submission)
    if template_id != template.id:
        raise SubmissionError(
            f'serialize_submission: submission targets template "{template_id}", '
            f'not "{template.id}".'
        )
    by_key = {
        f"{section_id}/{field_id}": answer for section_id, field_id, answer in answers
    }
    field_count = sum(len(section.fields) for section in template.sections)
    if len(by_key) != len(answers):
        raise SubmissionError(
            "serialize_submission: submission is not canonical — a field is "
            "answered more than once. Run canonicalize_submission first."
        )
    if len(by_key) != field_count:
        raise SubmissionError(
            "serialize_submission: submission is not canonical — expected exactly "
            f"one answer per template field ({field_count}), got {len(by_key)}. "
            "Run canonicalize_submission first."
        )

    context = [
        {"sectionId": section_id, "fieldId": field_id, "answer": answer}
        for section_id, field_id, answer in answers
    ]
    fields: list[SerializedField] = []
    for section, field in template.iter_fields():
        key = f"{section.id}/{field.id}"
        if key not in by_key:
            raise SubmissionError(
                f'serialize_submission: no answer for field "{key}" — submission '
                "is not canonical. Run canonicalize_submission first."
            )
        fields.append(
            SerializedField(
                section_id=section.id,
                section_label=f"{section.number}. {section.title}",
                field_id=field.id,
                field_label=f"{field.number} {field.title}",
                serialized_text=_field_text(
                    template, section.id, field.id, by_key[key], context
                ),
            )
        )
    return fields


def digest_payload(fields: Sequence[SerializedField]) -> str:
    """The exact JSON text the input digest hashes."""
    return js_json_stringify(
        [[field.field_id, field.serialized_text] for field in fields]
    )


def input_digest(fields: Sequence[SerializedField]) -> str:
    """``aiv1-`` + hex SHA-256 of the UTF-8 encoded :func:`digest_payload`."""
    payload = digest_payload(fields).encode("utf-8")
    return ASSESSMENT_INPUT_DIGEST_PREFIX + hashlib.sha256(payload).hexdigest()


def render_document(fields: Sequence[SerializedField]) -> str:
    """The submission as the reviewer prompts present it: a ``##`` heading per
    section and a ``###`` block per field with its text fenced in triple
    quotes, blocks separated by blank lines."""
    parts: list[str] = []
    current_section: str | None = None
    for field in fields:
        if field.section_label != current_section:
            current_section = field.section_label
            parts.append(f"## {field.section_label} (sectionId: {field.section_id})")
        parts.append(
            f"### {field.field_label} "
            f"(sectionId: {field.section_id}, fieldId: {field.field_id})\n"
            f'"""\n{field.serialized_text}\n"""'
        )
    return "\n\n".join(parts)
