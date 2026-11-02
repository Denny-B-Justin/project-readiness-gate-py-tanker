"""Pydantic models for the compiled PCN content files.

The template, criteria set, assessment set, MCA set and default project are
data: these models are the single definition of their shape. Every model
forbids unknown keys, so a misspelt property fails validation instead of
being dropped. Optional properties may be omitted but not set to ``null``,
and scalars are strict (no string-to-number or number-to-string coercion).
Field names are snake_case; the JSON keys are their camelCase aliases.
Attribute assignment is blocked; nested containers (lists, dicts and raw
answer values) are shared with every holder of the model, so do not mutate
them.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from typing import Annotated, Any, Literal, Self, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic.alias_generators import to_camel

from pcn_clone.core.jsstr import as_double, js_object_keys, number_to_string

# --- Scalar types ------------------------------------------------------------


def _reject_null(value: Any) -> Any:
    if value is None:
        raise ValueError("an optional property must be omitted, not null")
    return value


def _finite_float(value: float) -> float | None:
    number = as_double(value)
    return number if math.isfinite(number) else None


def _js_number(value: Any) -> float:
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    number = _finite_float(value) if is_number else None
    if number is None:
        raise ValueError("expected a finite number")
    return number


def _js_integer(value: Any) -> int:
    number = _js_number(value)
    if not number.is_integer():
        raise ValueError("expected an integer")
    return int(number)


_NO_NULL = BeforeValidator(_reject_null)

NonEmptyStr = Annotated[str, StringConstraints(strict=True, min_length=1)]
OptionalStr = Annotated[NonEmptyStr | None, _NO_NULL]
JsInt = Annotated[int, BeforeValidator(_js_integer)]
JsNumber = Annotated[float, BeforeValidator(_js_number)]


class ContentModel(BaseModel):
    """Base for every content model: unknown keys rejected, camelCase aliases.

    Attribute assignment is blocked; nested containers are shared, do not
    mutate them.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        alias_generator=to_camel,
        populate_by_name=False,
    )

    def to_json(self) -> dict[str, Any]:
        """The model as JSON-shaped data with its original camelCase keys."""
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")


# --- Controls ----------------------------------------------------------------


class SelectOption(ContentModel):
    """One choice in a select control: the stored value and its label."""

    value: NonEmptyStr
    label: NonEmptyStr


class TextControl(ContentModel):
    """A single-line text control."""

    id: NonEmptyStr
    label: NonEmptyStr
    type: Literal["text"]


class MonthControl(ContentModel):
    """A ``YYYY-MM`` month control."""

    id: NonEmptyStr
    label: NonEmptyStr
    type: Literal["month"]


class NumberControl(ContentModel):
    """A numeric control; its value is still stored as a string."""

    id: NonEmptyStr
    label: NonEmptyStr
    type: Literal["number"]


class TextareaControl(ContentModel):
    """A multi-line text control."""

    id: NonEmptyStr
    label: NonEmptyStr
    type: Literal["textarea"]


class SelectControl(ContentModel):
    """A select control; the answer stores one option's ``value``."""

    id: NonEmptyStr
    label: NonEmptyStr
    type: Literal["select"]
    options: Annotated[list[SelectOption], Field(min_length=1)]


Control = Annotated[
    TextControl | MonthControl | NumberControl | TextareaControl | SelectControl,
    Field(discriminator="type"),
]
"""A control: the atom grouped, list, worksheet and table inputs are built from."""


# --- Worksheet configuration -------------------------------------------------


class WorksheetRowSource(ContentModel):
    """The list field a worksheet draws its rows from."""

    section_id: NonEmptyStr
    field_id: NonEmptyStr
    label_control_id: NonEmptyStr
    start_date_control_id: NonEmptyStr


class WorksheetRowTotal(ContentModel):
    """A worksheet row's derived total: the row controls summed into it."""

    id: NonEmptyStr
    label: NonEmptyStr
    sum: Annotated[list[NonEmptyStr], Field(min_length=1)]


class WorksheetSummary(ContentModel):
    """How the worksheet's read-only category summary is grouped."""

    group_by: NonEmptyStr
    include_total_row: Annotated[bool, Field(strict=True)]


# --- Scenario comparison configuration ---------------------------------------


class ScenarioColumn(ContentModel):
    """One column of a scenario-comparison table."""

    id: NonEmptyStr
    label: NonEmptyStr


class ScenarioRow(ContentModel):
    """One proposer-entered scenario row."""

    id: NonEmptyStr
    label: NonEmptyStr


class ScenarioComputedRow(ContentModel):
    """A derived row: per column, ``left - right`` of two entered rows."""

    id: NonEmptyStr
    label: NonEmptyStr
    subtract: tuple[NonEmptyStr, NonEmptyStr]


class ScenarioApplicability(ContentModel):
    """The applicability gate: the numeric rows apply only when the gate's
    answer equals ``active_value``."""

    id: NonEmptyStr
    label: NonEmptyStr
    type: Literal["select"]
    active_value: NonEmptyStr
    options: Annotated[list[SelectOption], Field(min_length=1)]


# --- Static table configuration ----------------------------------------------


class StaticTableRow(ContentModel):
    """One authored row of a static table."""

    id: NonEmptyStr
    label: NonEmptyStr


# --- List configuration ------------------------------------------------------


class ProductGteCondition(ContentModel):
    """Met when the product of the factor controls' values is at least
    ``threshold``; a blank or non-numeric factor leaves it unmet."""

    kind: Literal["product_gte"]
    factors: Annotated[list[NonEmptyStr], Field(min_length=1)]
    threshold: JsNumber


class ListConditionalRequirement(ContentModel):
    """Makes ``target`` required for an item only when ``when`` is met."""

    target: NonEmptyStr
    when: ProductGteCondition


# --- Field inputs ------------------------------------------------------------


class TextareaInput(ContentModel):
    """A multi-line text answer."""

    type: Literal["textarea"]


class TextInput(ContentModel):
    """A single-line text answer."""

    type: Literal["text"]


class GroupInput(ContentModel):
    """A fixed set of child controls answered once."""

    type: Literal["group"]
    fields: Annotated[list[Control], Field(min_length=1)]


class ListInput(ContentModel):
    """A repeatable set of child controls."""

    type: Literal["list"]
    fields: Annotated[list[Control], Field(min_length=1)]
    conditional_requirements: list[ListConditionalRequirement] = Field(
        default_factory=list
    )
    add_item_label: OptionalStr = None


class WorksheetInput(ContentModel):
    """A cost table whose rows derive from a list field elsewhere in the form."""

    type: Literal["worksheet"]
    row_source: WorksheetRowSource
    row_controls: Annotated[list[Control], Field(min_length=1)]
    row_total: WorksheetRowTotal
    summary: WorksheetSummary
    optional_row_controls: Annotated[list[NonEmptyStr] | None, _NO_NULL] = None
    narrative_fields: Annotated[list[Control], Field(min_length=1)]


class ScenarioComparisonInput(ContentModel):
    """A with/without table with derived rows, an optional gate and narratives."""

    type: Literal["scenario_comparison"]
    applicability: Annotated[ScenarioApplicability | None, _NO_NULL] = None
    columns: Annotated[list[ScenarioColumn], Field(min_length=1)]
    entered_rows: Annotated[list[ScenarioRow], Field(min_length=1)]
    computed_rows: Annotated[list[ScenarioComputedRow], Field(min_length=1)]
    required_rows: Annotated[list[NonEmptyStr] | None, _NO_NULL] = None
    narrative_fields: Annotated[list[Control], Field(min_length=1)]


class StaticTableInput(ContentModel):
    """A fixed-row matrix filled across typed columns."""

    type: Literal["static_table"]
    rows: Annotated[list[StaticTableRow], Field(min_length=1)]
    columns: Annotated[list[Control], Field(min_length=1)]
    required_columns: Annotated[list[NonEmptyStr] | None, _NO_NULL] = None


FieldInput = Annotated[
    TextareaInput
    | TextInput
    | GroupInput
    | ListInput
    | WorksheetInput
    | ScenarioComparisonInput
    | StaticTableInput,
    Field(discriminator="type"),
]
"""How a field's answer is collected."""

FieldKind = Literal[
    "textarea",
    "text",
    "group",
    "list",
    "worksheet",
    "scenario_comparison",
    "static_table",
]
"""A field's input kind."""


# --- Template ----------------------------------------------------------------


class TemplateField(ContentModel):
    """One question a proposer answers; no ``input`` means a textarea."""

    id: NonEmptyStr
    number: NonEmptyStr
    title: NonEmptyStr
    guidance: NonEmptyStr
    input: Annotated[FieldInput | None, _NO_NULL] = None

    @property
    def kind(self) -> FieldKind:
        """The input kind, ``"textarea"`` when no input is declared."""
        return self.input.type if self.input is not None else "textarea"


class Section(ContentModel):
    """A numbered group of fields."""

    id: NonEmptyStr
    number: NonEmptyStr
    title: NonEmptyStr
    fields: Annotated[list[TemplateField], Field(min_length=1)]


class Template(ContentModel):
    """The PCN template: sections of fields."""

    id: NonEmptyStr
    version: NonEmptyStr
    title: NonEmptyStr
    label: NonEmptyStr
    region: NonEmptyStr
    description: OptionalStr = None
    guidance: OptionalStr = None
    sections: Annotated[list[Section], Field(min_length=1)]

    def get_section(self, section_id: str) -> Section | None:
        """The section with this id, if any."""
        return next((s for s in self.sections if s.id == section_id), None)

    def get_field(self, section_id: str, field_id: str) -> TemplateField | None:
        """The field with this id within the given section, if any."""
        section = self.get_section(section_id)
        if section is None:
            return None
        return next((f for f in section.fields if f.id == field_id), None)

    def iter_fields(self) -> Iterator[tuple[Section, TemplateField]]:
        """Every (section, field) pair in template order."""
        for section in self.sections:
            for field in section.fields:
                yield section, field


# --- Criteria and assessment sets --------------------------------------------


class VerdictDescriptors(ContentModel):
    """What a Fail, a Not Clear and a Pass each mean."""

    fail: NonEmptyStr
    not_clear: NonEmptyStr
    pass_: NonEmptyStr = Field(alias="pass")


class FieldCriteria(ContentModel):
    """The verdict rubric for one template field."""

    section_id: NonEmptyStr
    field_id: NonEmptyStr
    label: OptionalStr = None
    verdicts: VerdictDescriptors


class CriteriaSet(ContentModel):
    """Per-field verdict rubrics for one template."""

    id: NonEmptyStr
    template_id: NonEmptyStr
    version: NonEmptyStr
    description: OptionalStr = None
    fields: Annotated[list[FieldCriteria], Field(min_length=1)]

    def get(self, section_id: str, field_id: str) -> FieldCriteria | None:
        """The rubric for one field, if the set has one."""
        return next(
            (
                entry
                for entry in self.fields
                if entry.section_id == section_id and entry.field_id == field_id
            ),
            None,
        )


class AssessmentDimension(ContentModel):
    """One whole-document check a reviewer applies."""

    id: NonEmptyStr
    label: NonEmptyStr
    description: NonEmptyStr
    guidance: NonEmptyStr
    verdicts: VerdictDescriptors


class AssessmentSet(ContentModel):
    """The reviewer-facing assessment dimensions for one template."""

    id: NonEmptyStr
    template_id: NonEmptyStr
    version: NonEmptyStr
    description: OptionalStr = None
    dimensions: Annotated[list[AssessmentDimension], Field(min_length=1)]

    @model_validator(mode="after")
    def _unique_dimension_ids(self) -> Self:
        seen: set[str] = set()
        problems: list[str] = []
        for dimension in self.dimensions:
            if dimension.id in seen:
                problems.append(f'Duplicate dimension id "{dimension.id}".')
            seen.add(dimension.id)
        if problems:
            raise ValueError("\n".join(problems))
        return self

    def get_dimension(self, dimension_id: str) -> AssessmentDimension | None:
        """The dimension with this id, if any."""
        return next((d for d in self.dimensions if d.id == dimension_id), None)


# --- MCA set -----------------------------------------------------------------


class McaScaleEntry(ContentModel):
    """One point on the shared ordinal scale."""

    value: Annotated[JsInt, Field(ge=1)]
    label: NonEmptyStr
    meaning: NonEmptyStr


class McaBand(ContentModel):
    """A priority band: an inclusive lower bound on the percent of maximum."""

    id: NonEmptyStr
    label: NonEmptyStr
    min_percent_of_maximum: Annotated[JsNumber, Field(ge=0, le=100)]


class McaCriterion(ContentModel):
    """One weighted prioritisation criterion with a descriptor per scale value."""

    id: NonEmptyStr
    label: NonEmptyStr
    weight: Annotated[JsInt, Field(gt=0)]
    description: NonEmptyStr
    descriptors: dict[str, NonEmptyStr]


class McaMatrix(ContentModel):
    """Scale, weighted criteria and bands.

    Invariants: the scale is the contiguous run 1..N; criterion ids are
    unique, weights sum to exactly 100 and descriptors cover exactly the
    scale values; band ids are unique, thresholds strictly descend and the
    last threshold is exactly 0, so every percentage resolves to one band.
    """

    scale: Annotated[list[McaScaleEntry], Field(min_length=2)]
    bands: Annotated[list[McaBand], Field(min_length=1)]
    criteria: Annotated[list[McaCriterion], Field(min_length=1)]

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        problems: list[str] = []
        for index, entry in enumerate(self.scale):
            if entry.value != index + 1:
                problems.append(
                    "Scale values must be a contiguous ascending run starting "
                    f"at 1; position {index} has value {entry.value}."
                )

        scale_keys = [str(entry.value) for entry in self.scale]
        seen_criteria: set[str] = set()
        weight_sum = 0
        for criterion in self.criteria:
            if criterion.id in seen_criteria:
                problems.append(f'Duplicate criterion id "{criterion.id}".')
            seen_criteria.add(criterion.id)
            weight_sum += criterion.weight
            for key in dict.fromkeys(scale_keys):
                if key not in criterion.descriptors:
                    problems.append(
                        f'Criterion "{criterion.id}" has no descriptor for '
                        f"scale value {key}."
                    )
            for key in js_object_keys(criterion.descriptors):
                if key not in scale_keys:
                    problems.append(
                        f'Criterion "{criterion.id}" has a descriptor for '
                        f'"{key}", which is not a scale value.'
                    )
        if weight_sum != 100:
            problems.append(
                f"Criterion weights must sum to exactly 100; they sum to {weight_sum}."
            )

        seen_bands: set[str] = set()
        for index, band in enumerate(self.bands):
            if band.id in seen_bands:
                problems.append(f'Duplicate band id "{band.id}".')
            seen_bands.add(band.id)
            if index > 0:
                previous = self.bands[index - 1]
                if band.min_percent_of_maximum >= previous.min_percent_of_maximum:
                    threshold = number_to_string(band.min_percent_of_maximum)
                    previous_threshold = number_to_string(
                        previous.min_percent_of_maximum
                    )
                    problems.append(
                        "Band thresholds must be strictly descending; "
                        f'"{band.id}" ({threshold}) does not descend from '
                        f'"{previous.id}" ({previous_threshold}).'
                    )
        last = self.bands[-1]
        if last.min_percent_of_maximum != 0:
            problems.append(
                "The final band's threshold must be exactly 0 so every "
                f'percent-of-maximum resolves to a band; "{last.id}" has '
                f"{number_to_string(last.min_percent_of_maximum)}."
            )

        if problems:
            raise ValueError("\n".join(problems))
        return self

    @property
    def scale_minimum(self) -> int:
        """The lowest scale value (1 by invariant)."""
        return self.scale[0].value

    @property
    def scale_maximum(self) -> int:
        """The highest scale value."""
        return self.scale[-1].value

    def get_criterion(self, criterion_id: str) -> McaCriterion | None:
        """The criterion with this id, if any."""
        return next((c for c in self.criteria if c.id == criterion_id), None)


class McaSet(ContentModel):
    """The prioritisation matrix for one template."""

    id: NonEmptyStr
    template_id: NonEmptyStr
    version: NonEmptyStr
    description: OptionalStr = None
    matrix: McaMatrix


# --- Submissions and the default project -------------------------------------

ROW_ID_KEY = "_rowId"
"""The list-item key holding a row's durable id."""


def _is_str_record(value: Any) -> bool:
    return isinstance(value, Mapping) and all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    )


def _is_nested_str_record(value: Any) -> bool:
    return isinstance(value, Mapping) and all(
        isinstance(key, str) and _is_str_record(item) for key, item in value.items()
    )


def _has_keys(value: Any, required: set[str], optional: set[str] | None = None) -> bool:
    if not isinstance(value, Mapping):
        return False
    keys = set(value)
    return required <= keys <= required | (optional or set())


def is_worksheet_answer(value: Any) -> bool:
    """True for ``{componentCosts: {rowId: {control: str}}, narratives: {id: str}}``."""
    return (
        _has_keys(value, {"componentCosts", "narratives"})
        and _is_nested_str_record(value["componentCosts"])
        and _is_str_record(value["narratives"])
    )


def is_scenario_comparison_answer(value: Any) -> bool:
    """True for ``{applicability?: {id: str}, rows: {row: {column: str}},
    narratives: {id: str}}``."""
    return (
        _has_keys(value, {"rows", "narratives"}, {"applicability"})
        and ("applicability" not in value or _is_str_record(value["applicability"]))
        and _is_nested_str_record(value["rows"])
        and _is_str_record(value["narratives"])
    )


def is_static_table_answer(value: Any) -> bool:
    """True for ``{rows: {row: {column: str}}}``."""
    return _has_keys(value, {"rows"}) and _is_nested_str_record(value["rows"])


def _is_option_appraisal_answer(value: Any) -> bool:
    return (
        _has_keys(value, {"options", "selection"})
        and isinstance(value["options"], list)
        and all(_is_str_record(item) for item in value["options"])
        and _has_keys(value["selection"], {"optionId", "justification"})
        and isinstance(value["selection"]["optionId"], str)
        and isinstance(value["selection"]["justification"], str)
    )


def _is_periodic_amounts_answer(value: Any) -> bool:
    return (
        _has_keys(value, {"values", "narratives"})
        and _is_str_record(value["values"])
        and _is_str_record(value["narratives"])
    )


def _is_financial_matrix_answer(value: Any) -> bool:
    return (
        _has_keys(value, {"rows", "narratives"})
        and _is_nested_str_record(value["rows"])
        and _is_str_record(value["narratives"])
    )


def is_submission_answer_value(value: Any) -> bool:
    """True when a value has one of the shapes a field answer may take."""
    return (
        isinstance(value, str)
        or _is_str_record(value)
        or (isinstance(value, list) and all(_is_str_record(item) for item in value))
        or _is_option_appraisal_answer(value)
        or is_worksheet_answer(value)
        or is_scenario_comparison_answer(value)
        or is_static_table_answer(value)
        or _is_periodic_amounts_answer(value)
        or _is_financial_matrix_answer(value)
    )


def _check_answer_value(value: Any) -> Any:
    if not is_submission_answer_value(value):
        raise ValueError("answer does not match any field answer shape")
    return value


class SubmissionAnswer(ContentModel):
    """One answered field. The answer is kept as the raw JSON value."""

    section_id: NonEmptyStr
    field_id: NonEmptyStr
    answer: Annotated[Any, AfterValidator(_check_answer_value)]


class Submission(ContentModel):
    """A proposer's answers against one template."""

    template_id: NonEmptyStr
    answers: Annotated[list[SubmissionAnswer], Field(min_length=1)]


class DefaultProject(ContentModel):
    """An authored, completed example project."""

    id: NonEmptyStr
    version: NonEmptyStr
    title: NonEmptyStr
    description: NonEmptyStr
    tags: list[NonEmptyStr] = Field(default_factory=list)
    submission: Submission


AnswerLike = SubmissionAnswer | Mapping[str, Any]
"""One answered field: a ``SubmissionAnswer``, or its JSON shape
``{"sectionId", "fieldId", "answer"}``. A mapping is not schema-checked;
``SubmissionAnswer.model_validate`` is the boundary check."""

SubmissionLike = Submission | Mapping[str, Any]
"""A submission: a ``Submission``, or its JSON shape ``{"templateId",
"answers"}``. A mapping is not schema-checked (its answers are read as
given); ``Submission.model_validate`` is the boundary check."""

AnswerParts = tuple[str, str, Any]
"""``(section_id, field_id, answer)`` of one answered field."""


def answer_parts(entry: AnswerLike) -> AnswerParts:
    """The ids and raw answer of one answered field. A mapping must carry
    ``sectionId`` and ``fieldId``; a missing ``answer`` reads as ``None``."""
    if isinstance(entry, SubmissionAnswer):
        return entry.section_id, entry.field_id, entry.answer
    return (
        cast(str, entry["sectionId"]),
        cast(str, entry["fieldId"]),
        entry.get("answer"),
    )


def submission_parts(submission: SubmissionLike) -> tuple[str, list[AnswerParts]]:
    """The template id and answered fields of a submission. A mapping must
    carry ``templateId`` and ``answers``."""
    if isinstance(submission, Submission):
        return submission.template_id, [answer_parts(a) for a in submission.answers]
    answers: list[AnswerLike] = submission["answers"]
    return cast(str, submission["templateId"]), [answer_parts(a) for a in answers]
