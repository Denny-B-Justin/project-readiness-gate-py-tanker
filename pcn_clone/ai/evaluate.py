"""Single-field evaluation: the request boundary between the form and the
model.

:func:`evaluate_field` re-validates the request, prepares the answer (a
composite answer that fails validation returns its issues without a model
call), grades it and returns a :class:`FieldEvaluationResponse`. It never
raises: every failure is a value carrying a user-facing message.

:func:`readiness` and :func:`is_field_ready` are the synchronous checks the
form runs before offering evaluation.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

from pcn_clone.ai.config import AiConfigurationError
from pcn_clone.ai.prompts import field_prompts
from pcn_clone.ai.provider import ModelClient, ProviderError, shared_client
from pcn_clone.ai.schemas import (
    FIELD_EVALUATION_FORMAT,
    FieldEvaluation,
    field_evaluation_schema,
)
from pcn_clone.content import load_criteria, load_template
from pcn_clone.content.models import (
    AnswerLike,
    ListInput,
    ScenarioComparisonInput,
    StaticTableInput,
    SubmissionAnswer,
    TemplateField,
    WorksheetInput,
    is_submission_answer_value,
)
from pcn_clone.core.fields import (
    coerce_string_record_array,
    is_field_answer_complete,
    validate_list,
)
from pcn_clone.core.prepare import find_context_answer, prepare_field_answer
from pcn_clone.core.scenario import (
    coerce_scenario_comparison_answer,
    validate_scenario_comparison,
)
from pcn_clone.core.serialize import blank_answer_value
from pcn_clone.core.static_table import (
    coerce_static_table_answer,
    validate_static_table,
)
from pcn_clone.core.worksheet import (
    coerce_worksheet_answer,
    derive_worksheet_rows,
    validate_worksheet,
)

logger = logging.getLogger(__name__)

ENGINE_ERROR_MESSAGE = "The evaluation could not be completed. Please try again."
"""The user-facing message for any failed model call."""

NOT_CONFIGURED_MESSAGE = (
    "AI evaluation is not configured on this server. Please contact the administrator."
)
"""The user-facing message when the AI settings are missing or malformed."""

INCOMPLETE_PREFIX = "This field is incomplete: "


@dataclass(frozen=True, slots=True)
class FieldEvaluationResponse:
    """The outcome of one field evaluation.

    ``ok`` with ``result`` (and the ``model`` that produced it) on success.
    Otherwise ``error_message`` is user-facing; ``issues`` lists the
    validation problems when the answer is incomplete (no model call was
    made); ``retryable`` is true when trying again may succeed.
    ``section_id`` and ``field_id`` echo the request.
    """

    ok: bool
    result: FieldEvaluation | None = None
    issues: tuple[str, ...] = ()
    error_message: str | None = None
    retryable: bool = False
    model: str | None = None
    section_id: str = ""
    field_id: str = ""

    def to_json(self) -> dict[str, Any]:
        """The response as JSON-shaped data with camelCase keys:
        ``{ok: true, sectionId, fieldId, result: {sectionId, fieldId,
        verdict, reasoning, suggestions}, model}`` or ``{ok: false,
        sectionId, fieldId, errorMessage, issues, retryable}``."""
        ids = {"sectionId": self.section_id, "fieldId": self.field_id}
        if self.ok and self.result is not None:
            return {
                "ok": True,
                **ids,
                "result": {**ids, **self.result.model_dump(mode="json")},
                "model": self.model,
            }
        return {
            "ok": False,
            **ids,
            "errorMessage": self.error_message or "",
            "issues": list(self.issues),
            "retryable": self.retryable,
        }


def _check_answer(value: Any) -> Any:
    if not is_submission_answer_value(value):
        raise ValueError("answer does not match any field answer shape")
    return value


class _Request(BaseModel):
    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", alias_generator=to_camel
    )

    section_id: Annotated[str, Field(min_length=1)]
    field_id: Annotated[str, Field(min_length=1)]
    answer: Annotated[Any, AfterValidator(_check_answer)]
    context: list[SubmissionAnswer] | None = None


def _as_list(value: Any) -> Any:
    """A context iterable as a list; any other value unchanged, for the
    request model to reject."""
    if value is None or isinstance(value, (list, str, bytes, Mapping)):
        return value
    return list(value) if isinstance(value, Iterable) else value


def _validate_request(
    section_id: Any, field_id: Any, answer: Any, context: Any
) -> _Request | str:
    """The validated request, or the ``Invalid request — …`` message."""
    try:
        return _Request.model_validate(
            {
                "sectionId": section_id,
                "fieldId": field_id,
                "answer": answer,
                "context": _as_list(context),
            }
        )
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc']) or '(root)'}: "
            f"{issue['msg']}"
            for issue in error.errors()
        )
        return f"Invalid request — {problems}"


async def evaluate_field(
    section_id: str,
    field_id: str,
    answer: Any,
    context: Iterable[AnswerLike] | None = None,
    *,
    client: ModelClient | None = None,
) -> FieldEvaluationResponse:
    """Evaluate one field's answer against its guidance and rubric.

    ``answer`` is the raw answer value (text, a group record, list items or
    a composite table answer). ``context`` carries the other answers a
    cross-field kind reads: a worksheet needs its row-source list answer.
    ``client`` defaults to the process's shared client.
    """
    sid = section_id if isinstance(section_id, str) else ""
    fid = field_id if isinstance(field_id, str) else ""
    request = _validate_request(section_id, field_id, answer, context)
    if isinstance(request, str):
        return FieldEvaluationResponse(
            ok=False, error_message=request, section_id=sid, field_id=fid
        )

    template = load_template()
    criteria = load_criteria()
    if (
        template.get_field(section_id, field_id) is None
        or criteria.get(section_id, field_id) is None
    ):
        return FieldEvaluationResponse(
            ok=False,
            error_message=f'Unknown field "{section_id}/{field_id}".',
            section_id=sid,
            field_id=fid,
        )

    try:
        prepared = prepare_field_answer(
            template, section_id, field_id, request.answer, request.context
        )
        if not prepared.ok:
            return FieldEvaluationResponse(
                ok=False,
                issues=prepared.issues,
                error_message=INCOMPLETE_PREFIX + " ".join(prepared.issues),
                section_id=sid,
                field_id=fid,
            )
        system, user = field_prompts(
            template, criteria, section_id, field_id, prepared.answer_text or ""
        )
        model_client = client if client is not None else shared_client()
        reply = await model_client.complete(
            system=system,
            user=user,
            schema=field_evaluation_schema(),
            format_name=FIELD_EVALUATION_FORMAT,
        )
        result = FieldEvaluation.model_validate(reply.data)
    except ProviderError as error:
        logger.error(
            'Evaluation failed for "%s/%s" (%s): %s',
            section_id,
            field_id,
            error.kind,
            error.message,
        )
        return FieldEvaluationResponse(
            ok=False,
            error_message=ENGINE_ERROR_MESSAGE,
            retryable=error.kind == "retryable",
            section_id=sid,
            field_id=fid,
        )
    except AiConfigurationError as error:
        logger.error("AI evaluation is not configured: %s", error)
        return FieldEvaluationResponse(
            ok=False, error_message=NOT_CONFIGURED_MESSAGE, section_id=sid, field_id=fid
        )
    except Exception:
        logger.exception('Evaluation failed for "%s/%s"', section_id, field_id)
        return FieldEvaluationResponse(
            ok=False, error_message=ENGINE_ERROR_MESSAGE, section_id=sid, field_id=fid
        )
    return FieldEvaluationResponse(
        ok=True, result=result, model=reply.model, section_id=sid, field_id=fid
    )


def _ready_request(
    section_id: Any, field_id: Any, answer: Any, context: Any
) -> tuple[TemplateField, _Request] | str:
    """The field and validated request for a readiness check, or the message
    explaining why there is none. An absent answer (``None``) reads as the
    field's blank answer."""
    template = load_template()
    field = (
        template.get_field(section_id, field_id)
        if isinstance(section_id, str) and isinstance(field_id, str)
        else None
    )
    if answer is None and field is not None:
        answer = blank_answer_value(field)
    request = _validate_request(section_id, field_id, answer, context)
    if isinstance(request, str):
        return request
    if field is None:
        return f'Unknown field "{section_id}/{field_id}".'
    return field, request


def _issues(field: TemplateField, request: _Request) -> list[str]:
    field_input = field.input
    answer = request.answer
    if isinstance(field_input, WorksheetInput):
        template = load_template()
        source = field_input.row_source
        source_field = template.get_field(source.section_id, source.field_id)
        source_rows = coerce_string_record_array(
            find_context_answer(request.context, source.section_id, source.field_id)
        )
        rows = derive_worksheet_rows(field_input, source_rows)
        issues = validate_worksheet(
            field_input,
            rows,
            coerce_worksheet_answer(answer),
            None if source_field is None else source_field.number,
        )
        return [issue.message for issue in issues]
    if isinstance(field_input, ScenarioComparisonInput):
        scenario = coerce_scenario_comparison_answer(answer)
        return [i.message for i in validate_scenario_comparison(field_input, scenario)]
    if isinstance(field_input, StaticTableInput):
        table = coerce_static_table_answer(answer)
        return [i.message for i in validate_static_table(field_input, table)]
    if isinstance(field_input, ListInput):
        items = coerce_string_record_array(answer)
        return [issue.message for issue in validate_list(field_input, items)]
    return []


def readiness(
    section_id: str,
    field_id: str,
    answer: Any,
    context: Iterable[AnswerLike] | None = None,
) -> list[str]:
    """The messages explaining why a field is not ready to evaluate, for the
    "Complete the following before evaluating" panel. Never raises.

    The request is validated as :func:`evaluate_field` validates it, except
    that an absent answer (``None``) reads as the field's blank answer; a
    malformed request or an unknown field reports one message. List,
    worksheet, scenario-comparison and static-table fields report their
    validators' issues, which are exactly the issues evaluation would return.
    Text, textarea and group fields report nothing: a blank one is not ready
    (see :func:`is_field_ready`) but needs no explanation.
    """
    checked = _ready_request(section_id, field_id, answer, context)
    if isinstance(checked, str):
        return [checked]
    return _issues(*checked)


def is_field_ready(
    section_id: str,
    field_id: str,
    answer: Any,
    context: Iterable[AnswerLike] | None = None,
) -> bool:
    """Whether the form should offer evaluation for a field. Never raises.

    List, worksheet, scenario-comparison and static-table fields are ready
    when :func:`readiness` reports nothing; text, textarea and group fields
    when the answer is complete (non-blank text, every group control
    filled). A malformed request or an unknown field is never ready.
    """
    checked = _ready_request(section_id, field_id, answer, context)
    if isinstance(checked, str):
        return False
    field, request = checked
    if isinstance(
        field.input,
        (ListInput, WorksheetInput, ScenarioComparisonInput, StaticTableInput),
    ):
        return not _issues(field, request)
    return is_field_answer_complete(field, request.answer)
