"""The field-kind dispatcher against golden prepare cases, plus unit checks
for plain, group and list answers."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from pcn_clone.content import load_default_project, load_template
from pcn_clone.content.models import (
    ListInput,
    SubmissionAnswer,
    TemplateField,
    WorksheetInput,
)
from pcn_clone.core.fields import (
    coerce_string_record_array,
    is_control_required_for_item,
    is_field_answer_complete,
    prepare_list,
    serialize_field_answer,
    validate_list,
)
from pcn_clone.core.jsstr import js_trim
from pcn_clone.core.prepare import find_context_answer, prepare_field_answer
from pcn_clone.core.scenario import prepare_scenario_comparison
from pcn_clone.core.serialize import canonicalize_submission, serialize_submission
from pcn_clone.core.static_table import prepare_static_table
from pcn_clone.core.worksheet import prepare_worksheet
from tests.helpers import (
    fixture_params,
    load_fixture,
    prepare_result_json,
    prepared_json,
)

CASES = fixture_params("prepare_cases.json", label="prepare")

RISKS = ("project_management_and_risks", "project_risks")
SCOPE = ("project_description_and_impact", "scope_of_the_project")
PERIOD = ("investment_identification", "implementation_period")
TITLE = ("investment_identification", "project_title")
WORKSHEET = ("estimated_investment_costs_and_financing", "investment_cost_estimate")


def _field(section_id: str, field_id: str) -> TemplateField:
    field = load_template().get_field(section_id, field_id)
    assert field is not None
    return field


def _row_source(field: TemplateField) -> tuple[str, str]:
    assert isinstance(field.input, WorksheetInput)
    return field.input.row_source.section_id, field.input.row_source.field_id


def _kind_result(case: dict[str, Any]) -> Any:
    field = _field(case["sectionId"], case["fieldId"])
    answer = case["answer"]
    if field.kind == "list":
        return prepare_list(field, answer)
    if field.kind == "scenario_comparison":
        return prepare_scenario_comparison(field, answer)
    if field.kind == "static_table":
        return prepare_static_table(field, answer)
    if field.kind == "worksheet":
        source_field = _field(*_row_source(field))
        source_answer = find_context_answer(case["context"], *_row_source(field))
        return prepare_worksheet(field, source_field, source_answer, answer)
    return None


@pytest.mark.parametrize("case", CASES)
def test_prepare_result_matches_golden(case: dict[str, Any]) -> None:
    result = prepare_field_answer(
        load_template(),
        case["sectionId"],
        case["fieldId"],
        case["answer"],
        case["context"],
    )
    assert prepare_result_json(result) == case["result"]


@pytest.mark.parametrize("case", CASES)
def test_kind_preparer_matches_golden_raw_result(case: dict[str, Any]) -> None:
    assert _field(case["sectionId"], case["fieldId"]).kind == case["kind"]
    raw = _kind_result(case)
    if case["raw"] is None:
        assert raw is None
    else:
        assert prepared_json(raw) == case["raw"]


@pytest.mark.parametrize("case", CASES)
def test_submission_layer_matches_golden(case: dict[str, Any]) -> None:
    template = load_template()
    canonical = canonicalize_submission(template, load_default_project().submission)
    replacements = {(case["sectionId"], case["fieldId"]): case["answer"]}
    if case["kind"] == "worksheet":
        source = _row_source(_field(case["sectionId"], case["fieldId"]))
        source_answer = find_context_answer(case["context"], *source)
        replacements[source] = [] if source_answer is None else source_answer
    for entry in canonical["answers"]:
        key = (entry["sectionId"], entry["fieldId"])
        if key in replacements:
            entry["answer"] = copy.deepcopy(replacements[key])
    fields = serialize_submission(template, canonical)
    text = next(f.serialized_text for f in fields if f.field_id == case["fieldId"])
    assert text == case["submissionSerializedText"]


def test_field_prompts_embed_the_prepared_answer_text() -> None:
    prompts = load_fixture("prompts/field_prompts.json")
    template = load_template()
    canonical = canonicalize_submission(template, load_default_project().submission)
    for entry in canonical["answers"]:
        result = prepare_field_answer(
            template,
            entry["sectionId"],
            entry["fieldId"],
            entry["answer"],
            canonical["answers"],
        )
        assert result.ok
        answer = js_trim(result.answer_text or "") or "(no answer provided)"
        fenced = f'## Proposer\'s answer\n"""\n{answer}\n"""'
        assert fenced in prompts[entry["fieldId"]]["user"], entry["fieldId"]


# --- Dispatcher --------------------------------------------------------------


def test_unknown_field_raises_lookup_error() -> None:
    with pytest.raises(LookupError, match='no field "nope/nope"'):
        prepare_field_answer(load_template(), "nope", "nope", "")


def test_context_accepts_submission_answer_models() -> None:
    template = load_template()
    answers = {
        (entry.section_id, entry.field_id): entry
        for entry in load_default_project().submission.answers
    }
    context = [answers[SCOPE]]
    assert isinstance(context[0], SubmissionAnswer)
    from_models = prepare_field_answer(
        template, *WORKSHEET, answers[WORKSHEET].answer, context
    )
    from_mappings = prepare_field_answer(
        template,
        *WORKSHEET,
        answers[WORKSHEET].answer,
        [{"sectionId": SCOPE[0], "fieldId": SCOPE[1], "answer": answers[SCOPE].answer}],
    )
    assert from_models.ok
    assert from_models == from_mappings


def test_missing_row_source_field_blocks_the_worksheet() -> None:
    template = load_template()
    sections = [
        section.model_copy(
            update={"fields": [f for f in section.fields if f.id != SCOPE[1]]}
        )
        if section.id == SCOPE[0]
        else section
        for section in template.sections
    ]
    without_scope = template.model_copy(update={"sections": sections})
    result = prepare_field_answer(
        without_scope, *WORKSHEET, {"componentCosts": {}, "narratives": {}}
    )
    assert prepare_result_json(result) == {
        "ok": False,
        "serializedText": None,
        "issues": [
            'Row source field "project_description_and_impact/'
            'scope_of_the_project" is missing from the template.'
        ],
    }


# --- Plain, group and list answers -------------------------------------------


def _risk(likelihood: str, impact: str, measures: str = "") -> dict[str, str]:
    return {
        "_rowId": "r",
        "risk_factor": "Cost overrun",
        "likelihood": likelihood,
        "impact": impact,
        "risk_reduction_measures": measures,
    }


def _risks_input() -> ListInput:
    field_input = _field(*RISKS).input
    assert isinstance(field_input, ListInput)
    return field_input


def test_plain_and_group_answers_serialize_directly() -> None:
    template = load_template()
    title = prepare_field_answer(template, *TITLE, " Road ")
    assert prepare_result_json(title) == {
        "ok": True,
        "serializedText": " Road ",
        "issues": [],
    }
    group = prepare_field_answer(
        template,
        *PERIOD,
        {"project_start_date": "2026-03", "estimated_project_completion_date": 5},
    )
    assert group.answer_text == (
        "Project Start Date: 2026-03\nEstimated Project Completion Date: 5"
    )
    nested = serialize_field_answer(
        _field(*PERIOD),
        {"project_start_date": [1, None, "a"], "estimated_project_completion_date": {}},
    )
    assert nested == (
        "Project Start Date: 1,,a\nEstimated Project Completion Date: [object Object]"
    )
    assert serialize_field_answer(_field(*PERIOD), ["not", "a", "record"]) == ""
    assert serialize_field_answer(_field(*TITLE), 7) == ""


def test_list_serializes_numbered_items_ignoring_row_ids() -> None:
    result = prepare_field_answer(
        load_template(),
        *SCOPE,
        [
            {
                "_rowId": "a",
                "component": "Design",
                "expected_start_date": "2026-01",
                "expected_end_date": "2026-06",
            },
            {
                "component": "Works",
                "expected_start_date": "2026-07",
                "expected_end_date": "2027-12",
            },
        ],
    )
    assert result.answer_text == (
        "Item 1\nComponent: Design\nExpected start date: 2026-01\n"
        "Expected end date: 2026-06\n\n"
        "Item 2\nComponent: Works\nExpected start date: 2026-07\n"
        "Expected end date: 2027-12"
    )


def test_conditional_requirement_fires_at_the_threshold() -> None:
    field_input = _risks_input()

    def issues_for(*items: dict[str, str]) -> list[tuple[str, str | None]]:
        coerced = coerce_string_record_array(list(items))
        return [(i.kind, i.control_id) for i in validate_list(field_input, coerced)]

    assert issues_for(_risk("1", "3")) == []
    assert issues_for(_risk("2", "2")) == [("missing_value", "risk_reduction_measures")]
    assert issues_for(_risk("4", "1", "Hedge")) == []
    assert issues_for(_risk("", "5")) == [("missing_value", "likelihood")]
    assert is_control_required_for_item(
        field_input, "risk_reduction_measures", _risk("5", "5")
    )
    assert not is_control_required_for_item(
        field_input, "risk_reduction_measures", _risk("1", "1")
    )
    assert is_control_required_for_item(field_input, "risk_factor", _risk("1", "1"))


def test_list_issue_messages() -> None:
    items = coerce_string_record_array([_risk("2", "2"), _risk("abc", "5")])
    assert [issue.message for issue in validate_list(_risks_input(), items)] == [
        "Item 1 — Risk reduction measures: required value is missing.",
        "Item 2 — Likelihood: is not a valid option.",
    ]


def test_list_coercion_matches_javascript_string_conversion() -> None:
    coerced = coerce_string_record_array(
        [
            1,
            "x",
            None,
            ["nested"],
            {
                "str": "keep",
                "num": 4,
                "float": 4.0,
                "zero": 0,
                "bool": True,
                "huge": 10**400,
                "nan": float("nan"),
                "inf": float("inf"),
                "nul": None,
                "obj": {"a": 1},
                "arr": [1, 2],
            },
        ]
    )
    assert coerced == [
        {
            "str": "keep",
            "num": "4",
            "float": "4",
            "zero": "0",
            "bool": "true",
            "huge": None,
            "nan": None,
            "inf": None,
            "nul": None,
            "obj": None,
            "arr": None,
        }
    ]
    assert coerce_string_record_array("not a list") == []
    assert coerce_string_record_array(None) == []


def test_empty_list_is_one_issue() -> None:
    result = prepare_field_answer(load_template(), *SCOPE, [])
    assert prepare_result_json(result) == {
        "ok": False,
        "serializedText": None,
        "issues": ["Add at least one item before evaluating."],
    }


def test_completeness_for_plain_group_and_list() -> None:
    assert is_field_answer_complete(_field(*TITLE), "x")
    assert not is_field_answer_complete(_field(*TITLE), " \ufeff")
    assert is_field_answer_complete(
        _field(*PERIOD),
        {
            "project_start_date": "2026-01",
            "estimated_project_completion_date": "2027-01",
        },
    )
    assert not is_field_answer_complete(
        _field(*PERIOD), {"project_start_date": "2026-01"}
    )
    assert is_field_answer_complete(_field(*RISKS), [_risk("1", "1")])
    assert not is_field_answer_complete(_field(*RISKS), [_risk("5", "5")])
    assert not is_field_answer_complete(
        _field("estimated_investment_costs_and_financing", "revenues"), "text"
    )


def test_a_non_record_list_item_makes_the_list_incomplete() -> None:
    assert is_field_answer_complete(_field(*RISKS), [_risk("1", "1")])
    assert not is_field_answer_complete(_field(*RISKS), ["junk", _risk("1", "1")])
    assert not is_field_answer_complete(_field(*RISKS), [_risk("1", "1"), None])
