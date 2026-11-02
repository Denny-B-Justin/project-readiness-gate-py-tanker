"""Structured-output contracts: the JSON schemas the model receives and the
pydantic models its replies are validated with.

The JSON schema builders emit draft-07 schemas in a fixed layout: a
sub-schema used more than once (the citation quote) is defined once in a
top-level ``definitions`` block, alongside a copy of the root schema, and
referenced by ``$ref``. The pydantic models add what a JSON schema cannot
say: a quote or justification must be non-blank after trimming, and lengths
count UTF-16 code units.

A citation names a field of one serialized submission. Validating a reply
with a :class:`ReplyScope` as the pydantic validation ``context`` checks each
citation against that submission and, for an MCA score, the score against the
matrix's scale; without one, only the shape is checked.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    model_validator,
)
from pydantic.alias_generators import to_camel

from pcn_clone.content.models import JsInt, McaMatrix
from pcn_clone.core.jsstr import js_trim, to_utf16
from pcn_clone.core.serialize import SerializedField

JSON_SCHEMA_DRAFT_07 = "http://json-schema.org/draft-07/schema#"

FIELD_EVALUATION_FORMAT = "field_evaluation"
ASSESSMENT_FINDING_FORMAT = "assessment_finding"
MCA_SCORE_FINDING_FORMAT = "mca_score_finding"

VERDICTS = ("fail", "notClear", "pass")
Verdict = Literal["fail", "notClear", "pass"]

ASSESSMENT_QUOTE_MAX_LENGTH = 300
MCA_QUOTE_MAX_LENGTH = ASSESSMENT_QUOTE_MAX_LENGTH
MCA_JUSTIFICATION_MAX_LENGTH = 600
MCA_MAX_CITATIONS = 3
MCA_SCALE_MINIMUM = 1
"""The first value of every MCA scale (scales run contiguously from 1)."""

# --- Shared descriptions -----------------------------------------------------

_SECTION_ID_DESCRIPTION = "Id of the section the cited field belongs to."
_FIELD_ID_DESCRIPTION = "Id of the cited field, within that section."
_QUOTE_DESCRIPTION = (
    "A short verbatim quote copied exactly from the cited field's text, "
    f"at most {ASSESSMENT_QUOTE_MAX_LENGTH} characters."
)
_JUSTIFICATION_DESCRIPTION = (
    "2 to 4 sentences arguing the score against this criterion's descriptor "
    "language — not a summary of the project. State the tie-break if one "
    "was applied, or what the document is silent on if the basis is "
    f"not_evidenced. At most {MCA_JUSTIFICATION_MAX_LENGTH} characters."
)


def _string_list(description: str) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "description": description}


def _verdict(description: str) -> dict[str, Any]:
    return {"type": "string", "enum": list(VERDICTS), "description": description}


def _closed_object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _finish(root: dict[str, Any], definitions: dict[str, Any] | None) -> dict[str, Any]:
    schema = dict(root)
    if definitions is not None:
        schema["definitions"] = definitions
    schema["$schema"] = JSON_SCHEMA_DRAFT_07
    return schema


# --- Field evaluation --------------------------------------------------------


def field_evaluation_schema() -> dict[str, Any]:
    """The JSON schema of a single-field evaluation reply."""
    return _finish(
        _closed_object(
            {
                "verdict": _verdict(
                    "The single overall verdict for the answer: 'fail', "
                    "'notClear', or 'pass'."
                ),
                "reasoning": {
                    "type": "string",
                    "description": (
                        "A concise explanation of why this verdict was reached. "
                        "It must refer explicitly to the Fail / Not Clear / Pass "
                        "rubric descriptors and the field guidance, and make clear "
                        "why a higher verdict was not awarded."
                    ),
                },
                "suggestions": _string_list(
                    "Concrete, actionable suggestions the proposer can apply to "
                    "improve the answer. May be empty only when the answer is "
                    "already strong."
                ),
            }
        ),
        None,
    )


# --- Citations ---------------------------------------------------------------


def citable_fields(fields: Sequence[SerializedField]) -> dict[str, list[str]]:
    """The submission's field ids grouped by section id, both in first-seen
    order and without duplicates. Raises ``ValueError`` for no fields."""
    if not fields:
        raise ValueError(
            "Cannot build a citation-constrained output contract over zero fields."
        )
    by_section: dict[str, list[str]] = {}
    for field in fields:
        ids = by_section.setdefault(field.section_id, [])
        if field.field_id not in ids:
            ids.append(field.field_id)
    return by_section


def _quote_schema() -> dict[str, Any]:
    return {
        "type": "string",
        "minLength": 1,
        "maxLength": ASSESSMENT_QUOTE_MAX_LENGTH,
        "description": _QUOTE_DESCRIPTION,
    }


def _citation_items(
    fields: Sequence[SerializedField], quote_ref: str
) -> tuple[dict[str, Any], bool]:
    """The citation item schema (one branch per section) and whether the
    quote schema is referenced through ``quote_ref``."""
    branches = [
        _closed_object(
            {
                "sectionId": {
                    "type": "string",
                    "const": section_id,
                    "description": _SECTION_ID_DESCRIPTION,
                },
                "fieldId": {
                    "type": "string",
                    "enum": field_ids,
                    "description": _FIELD_ID_DESCRIPTION,
                },
                "quote": (
                    _quote_schema()
                    if index == 0
                    else {"$ref": f"#/definitions/{quote_ref}"}
                ),
            }
        )
        for index, (section_id, field_ids) in enumerate(citable_fields(fields).items())
    ]
    if len(branches) == 1:
        return branches[0], False
    return {"anyOf": branches}, True


def _with_quote_definitions(
    root: dict[str, Any], format_name: str, quote_ref: str, referenced: bool
) -> dict[str, Any]:
    definitions = (
        {quote_ref: _quote_schema(), format_name: copy.deepcopy(root)}
        if referenced
        else None
    )
    return _finish(root, definitions)


# --- Assessment finding ------------------------------------------------------


def assessment_finding_schema(fields: Sequence[SerializedField]) -> dict[str, Any]:
    """The JSON schema of one dimension's assessment reply, its citations
    constrained to the submission's own section and field ids.

    Raises ``ValueError`` for an empty submission.
    """
    quote_ref = (
        f"{ASSESSMENT_FINDING_FORMAT}_properties_evidence_items_anyOf_0_"
        "properties_quote"
    )
    items, referenced = _citation_items(fields, quote_ref)
    root = _closed_object(
        {
            "verdict": _verdict(
                "The single overall verdict for this dimension: 'fail', "
                "'notClear', or 'pass'."
            ),
            "reasoning": {
                "type": "string",
                "description": (
                    "A concise explanation of why this verdict was reached. It "
                    "must refer explicitly to the dimension's rubric descriptors "
                    "and to specific parts of the submission, and make clear why "
                    "a higher verdict was not awarded."
                ),
            },
            "evidence": {
                "type": "array",
                "items": items,
                "description": (
                    "Citations grounding the reasoning: each names a "
                    "section/field from the submission and carries a short "
                    "verbatim quote from that field's text."
                ),
            },
            "questions": _string_list(
                "Questions the reviewer should put to the proposer for this "
                "dimension. May be empty when nothing needs asking."
            ),
        }
    )
    return _with_quote_definitions(
        root, ASSESSMENT_FINDING_FORMAT, quote_ref, referenced
    )


# --- MCA score finding -------------------------------------------------------


def mca_score_finding_schema(
    fields: Sequence[SerializedField], matrix: McaMatrix
) -> dict[str, Any]:
    """The JSON schema of one criterion's MCA score reply: documented scores
    bounded to the matrix's scale with 1–3 citations constrained to the
    submission, or a not-evidenced score fixed at the scale minimum.

    Raises ``ValueError`` for an empty submission.
    """
    quote_ref = (
        f"{MCA_SCORE_FINDING_FORMAT}_properties_basis_anyOf_0_properties_"
        "evidence_items_anyOf_0_properties_quote"
    )
    items, referenced = _citation_items(fields, quote_ref)
    documented = _closed_object(
        {
            "kind": {"type": "string", "const": "documented"},
            "score": {
                "type": "integer",
                "minimum": matrix.scale_minimum,
                "maximum": matrix.scale_maximum,
                "description": (
                    "The ordinal score, matching the descriptor the cited "
                    "evidence supports. Where the project sits between two "
                    "descriptors, take the lower score."
                ),
            },
            "evidence": {
                "type": "array",
                "items": items,
                "minItems": 1,
                "maxItems": MCA_MAX_CITATIONS,
                "description": (
                    "1 to 3 citations grounding the score: each names a "
                    "section/field from the submission and carries a short "
                    "verbatim quote from that field's text."
                ),
            },
        }
    )
    not_evidenced = _closed_object(
        {
            "kind": {"type": "string", "const": "not_evidenced"},
            "score": {
                "type": "number",
                "const": matrix.scale_minimum,
                "description": (
                    "The scale minimum — the only score a criterion the "
                    "document is silent on can receive."
                ),
            },
        }
    )
    root = _closed_object(
        {
            "justification": {
                "type": "string",
                "minLength": 1,
                "maxLength": MCA_JUSTIFICATION_MAX_LENGTH,
                "description": _JUSTIFICATION_DESCRIPTION,
            },
            "basis": {"anyOf": [documented, not_evidenced]},
        }
    )
    return _with_quote_definitions(
        root, MCA_SCORE_FINDING_FORMAT, quote_ref, referenced
    )


# --- Reply models ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReplyScope:
    """Validation context for a reviewer reply: the submission it cites and,
    for an MCA score, the matrix whose scale bounds the score."""

    fields: Sequence[SerializedField]
    matrix: McaMatrix | None = None


def _utf16_length(text: str) -> int:
    return len(to_utf16(text)) // 2


def _bounded_text(label: str, max_length: int) -> AfterValidator:
    def check(value: str) -> str:
        if _utf16_length(value) > max_length:
            raise ValueError(f"{label} must be at most {max_length} characters.")
        if js_trim(value) == "":
            raise ValueError(f"{label} must not be blank.")
        return value

    return AfterValidator(check)


Quote = Annotated[
    str,
    Field(min_length=1, description=_QUOTE_DESCRIPTION),
    _bounded_text("Quote", ASSESSMENT_QUOTE_MAX_LENGTH),
]
Justification = Annotated[
    str,
    Field(min_length=1, description=_JUSTIFICATION_DESCRIPTION),
    _bounded_text("Justification", MCA_JUSTIFICATION_MAX_LENGTH),
]


class _Reply(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        alias_generator=to_camel,
        populate_by_name=True,
    )


def _scope(info: ValidationInfo) -> ReplyScope | None:
    return info.context if isinstance(info.context, ReplyScope) else None


class FieldEvaluation(_Reply):
    """A single-field evaluation: one verdict, the reasoning for it and
    suggestions for improving the answer. Unknown keys are ignored."""

    model_config = ConfigDict(extra="ignore")

    verdict: Verdict
    reasoning: str
    suggestions: list[str]


class Citation(_Reply):
    """One evidence citation: a field of the submission and a short verbatim
    quote from its text."""

    section_id: Annotated[str, Field(min_length=1)]
    field_id: Annotated[str, Field(min_length=1)]
    quote: Quote

    @model_validator(mode="after")
    def _cites_submission_field(self, info: ValidationInfo) -> Self:
        scope = _scope(info)
        if scope is not None:
            field_ids = citable_fields(scope.fields).get(self.section_id, [])
            if self.field_id not in field_ids:
                raise ValueError(
                    f'Citation "{self.section_id}/{self.field_id}" is not a field '
                    "of the submission."
                )
        return self


class AssessmentFinding(_Reply):
    """One dimension's assessment as the model returns it."""

    verdict: Verdict
    reasoning: str
    evidence: list[Citation]
    questions: list[str]


class DocumentedBasis(_Reply):
    """A score grounded in 1–3 citations."""

    kind: Literal["documented"]
    score: Annotated[JsInt, Field(ge=MCA_SCALE_MINIMUM)]
    evidence: Annotated[
        list[Citation], Field(min_length=1, max_length=MCA_MAX_CITATIONS)
    ]

    @model_validator(mode="after")
    def _score_on_scale(self, info: ValidationInfo) -> Self:
        scope = _scope(info)
        matrix = scope.matrix if scope is not None else None
        if matrix is not None and not (
            matrix.scale_minimum <= self.score <= matrix.scale_maximum
        ):
            raise ValueError(
                f"A documented score must be on the scale "
                f"{matrix.scale_minimum}..{matrix.scale_maximum}."
            )
        return self


class NotEvidencedBasis(_Reply):
    """The score for a criterion the submission is silent on: the scale
    minimum, with no citations."""

    kind: Literal["not_evidenced"]
    score: JsInt

    @model_validator(mode="after")
    def _score_is_minimum(self, info: ValidationInfo) -> Self:
        scope = _scope(info)
        matrix = scope.matrix if scope is not None else None
        minimum = matrix.scale_minimum if matrix is not None else MCA_SCALE_MINIMUM
        if self.score != minimum:
            raise ValueError(
                f"A not_evidenced score must be the scale minimum ({minimum})."
            )
        return self


class McaScoreFinding(_Reply):
    """One criterion's MCA score as the model returns it."""

    justification: Justification
    basis: Annotated[DocumentedBasis | NotEvidencedBasis, Field(discriminator="kind")]
