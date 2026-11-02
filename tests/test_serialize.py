"""Whole-submission canonicalization, serialization and the input digest."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from pcn_clone.content import load_default_project, load_template
from pcn_clone.core.jsstr import js_json_stringify
from pcn_clone.core.serialize import (
    NO_ANSWER_MARKER,
    SerializedField,
    SubmissionError,
    canonicalize_submission,
    check_submission_consistency,
    digest_payload,
    input_digest,
    is_blank_answer_value,
    render_document,
    serialize_submission,
)
from tests.helpers import as_json, load_fixture

DEFAULT_PROJECT_DIGEST = (
    "aiv1-9c6739310785cf83573edbc5cad497bec75851e179e6dbecbe8812eb306719a6"
)

BLANK_SUBMISSION = {
    "templateId": "pcn_global",
    "answers": [
        {
            "sectionId": "investment_identification",
            "fieldId": "project_title",
            "answer": "",
        }
    ],
}


def _serialize(submission: Any) -> list[SerializedField]:
    template = load_template()
    return serialize_submission(template, canonicalize_submission(template, submission))


def _field(fields: list[SerializedField], field_id: str) -> SerializedField:
    return next(field for field in fields if field.field_id == field_id)


# --- Key acceptance ----------------------------------------------------------


def test_default_project_digest_matches_the_known_value() -> None:
    fields = _serialize(load_default_project().submission)
    assert len(fields) == 19
    assert input_digest(fields) == DEFAULT_PROJECT_DIGEST


def test_default_project_accepts_its_json_shape_as_well_as_the_model() -> None:
    submission = load_default_project().submission.to_json()
    assert input_digest(_serialize(submission)) == DEFAULT_PROJECT_DIGEST


# --- Golden fixtures ---------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture_name", "submission"),
    [
        ("serialized_default.json", None),
        ("serialized_blank.json", BLANK_SUBMISSION),
    ],
    ids=["default", "blank"],
)
def test_serialization_matches_golden_fixture(
    fixture_name: str, submission: Any
) -> None:
    golden = load_fixture(fixture_name)
    template = load_template()
    source = load_default_project().submission if submission is None else submission

    canonical = canonicalize_submission(template, source)
    assert golden["templateId"] == template.id
    assert canonical["answers"] == golden["canonicalAnswers"]

    fields = serialize_submission(template, canonical)
    assert len(fields) == len(golden["fields"]) == 19
    for mine, theirs in zip(fields, golden["fields"], strict=True):
        assert as_json(mine) == theirs, f"field {theirs['fieldId']} differs"
    assert input_digest(fields) == golden["digest"]


def test_blank_submission_renders_the_marker_for_every_field() -> None:
    fields = _serialize(BLANK_SUBMISSION)
    assert [field.serialized_text for field in fields] == [NO_ANSWER_MARKER] * 19


def test_document_is_embedded_verbatim_in_the_reviewer_prompts() -> None:
    prompts = load_fixture("prompts/assessment_prompts.json")
    document = render_document(_serialize(load_default_project().submission))
    for dimension_id, prompt in prompts.items():
        assert document in prompt["user"], dimension_id


# --- Labels, markers and policy ----------------------------------------------


def test_labels_carry_numbers_and_titles_in_template_order() -> None:
    fields = _serialize(BLANK_SUBMISSION)
    first = fields[0]
    assert first.section_label == "1. Investment Identification"
    assert first.field_label == "1.1 Project title"
    assert [field.field_id for field in fields][-1] == "land_and_property_status"


def test_invalid_composite_renders_its_issues() -> None:
    submission = {
        "templateId": "pcn_global",
        "answers": [
            {
                "sectionId": "estimated_investment_costs_and_financing",
                "fieldId": "investment_cost_estimate",
                "answer": {
                    "componentCosts": {"ghost": {"cost_category": "land"}},
                    "narratives": {},
                },
            }
        ],
    }
    text = _field(_serialize(submission), "investment_cost_estimate").serialized_text
    assert text == (
        "This answer is structurally invalid and could not be rendered:\n"
        "- Add at least one item in section 3.2 before completing the cost worksheet."
    )


def test_a_text_field_answered_with_a_record_renders_the_marker() -> None:
    submission = {
        "templateId": "pcn_global",
        "answers": [
            {
                "sectionId": "investment_identification",
                "fieldId": "project_title",
                "answer": {"title": "Road"},
            }
        ],
    }
    fields = _serialize(submission)
    assert _field(fields, "project_title").serialized_text == NO_ANSWER_MARKER


@pytest.mark.parametrize(
    ("value", "blank"),
    [
        (None, True),
        ("", True),
        (" \u00a0\ufeff\n", True),
        ("\u0085", False),
        ([], True),
        ({}, True),
        ([{"_rowId": "r1", "component": " "}], True),
        ({"rows": {"a": {"b": ""}}}, True),
        ({"_rowId": "r1"}, True),
        ([{"_rowId": "r1", "component": "x"}], False),
        (0, False),
        (False, False),
    ],
    ids=[
        "none",
        "empty-string",
        "js-whitespace-string",
        "nel-is-not-js-whitespace",
        "empty-list",
        "empty-record",
        "list-of-blank-records-with-row-id",
        "nested-blank-record",
        "row-id-only",
        "list-with-a-value",
        "zero",
        "false",
    ],
)
def test_blankness(value: Any, blank: bool) -> None:
    assert is_blank_answer_value(value) is blank


# --- Canonicalization and consistency ----------------------------------------


def test_canonicalization_fills_blanks_by_kind_in_template_order() -> None:
    canonical = canonicalize_submission(load_template(), BLANK_SUBMISSION)
    blanks = {entry["fieldId"]: entry["answer"] for entry in canonical["answers"]}
    assert blanks["implementation_period"] == {}
    assert blanks["scope_of_the_project"] == []
    assert blanks["investment_cost_estimate"] == {
        "componentCosts": {},
        "narratives": {},
    }
    assert blanks["revenues"] == {"rows": {}, "narratives": {}}
    assert blanks["documentation_and_permits"] == {"rows": {}}
    assert blanks["objectives"] == ""
    assert len(canonical["answers"]) == 19


def test_consistency_problems_are_reported_in_answer_order() -> None:
    submission = {
        "templateId": "other",
        "answers": [
            {"sectionId": "x", "fieldId": "y", "answer": ""},
            {
                "sectionId": "investment_identification",
                "fieldId": "project_title",
                "answer": "",
            },
            {
                "sectionId": "investment_identification",
                "fieldId": "project_title",
                "answer": "",
            },
        ],
    }
    assert check_submission_consistency(load_template(), submission) == [
        (
            'Submission targets template "other", but is paired with template '
            '"pcn_global".'
        ),
        'Answer references unknown field "x/y" — not in the template.',
        'Field "investment_identification/project_title" is answered more than once.',
    ]
    with pytest.raises(SubmissionError, match="inconsistent submission"):
        canonicalize_submission(load_template(), submission)


def test_a_mapping_must_carry_template_id_and_answers() -> None:
    template = load_template()
    with pytest.raises(KeyError, match="answers"):
        canonicalize_submission(template, {"templateId": "pcn_global"})
    with pytest.raises(KeyError, match="answers"):
        serialize_submission(template, {"templateId": "pcn_global"})
    with pytest.raises(KeyError, match="templateId"):
        check_submission_consistency(template, {"answers": []})


def test_an_answer_outside_the_template_cannot_displace_a_field() -> None:
    template = load_template()
    canonical = canonicalize_submission(template, BLANK_SUBMISSION)
    foreign = {"sectionId": "elsewhere", "fieldId": "other", "answer": ""}
    displaced = {**canonical, "answers": [foreign, *canonical["answers"][1:]]}
    assert len(displaced["answers"]) == 19
    with pytest.raises(
        SubmissionError,
        match='no answer for field "investment_identification/project_title"',
    ):
        serialize_submission(template, displaced)


def test_canonical_answers_do_not_alias_the_cached_default_project() -> None:
    template = load_template()
    canonical = canonicalize_submission(template, load_default_project().submission)
    for entry in canonical["answers"]:
        answer = entry["answer"]
        if isinstance(answer, (list, dict)):
            answer.clear()
    assert input_digest(_serialize(load_default_project().submission)) == (
        DEFAULT_PROJECT_DIGEST
    )


def test_non_canonical_submissions_are_refused() -> None:
    template = load_template()
    canonical = canonicalize_submission(template, BLANK_SUBMISSION)
    with pytest.raises(SubmissionError, match="not canonical"):
        serialize_submission(
            template, {**canonical, "answers": canonical["answers"][1:]}
        )
    with pytest.raises(SubmissionError, match="answered more than once"):
        serialize_submission(
            template,
            {
                **canonical,
                "answers": [*canonical["answers"][1:], canonical["answers"][1]],
            },
        )
    with pytest.raises(SubmissionError, match='targets template "other"'):
        serialize_submission(template, {**canonical, "templateId": "other"})


# --- Digest encoding ---------------------------------------------------------


def _record(field_id: str, text: str) -> SerializedField:
    return SerializedField("s", "1. S", field_id, f"1.1 {field_id}", text)


def test_digest_is_sha256_of_the_json_pairs() -> None:
    fields = [_record("a", "one"), _record("b", "two")]
    assert digest_payload(fields) == '[["a","one"],["b","two"]]'
    expected = hashlib.sha256(b'[["a","one"],["b","two"]]').hexdigest()
    assert input_digest(fields) == "aiv1-" + expected


def test_digest_is_sensitive_to_text_id_order_and_boundaries() -> None:
    base = input_digest([_record("a", "one"), _record("b", "two")])
    assert base != input_digest([_record("a", "one!"), _record("b", "two")])
    assert base != input_digest([_record("a2", "one"), _record("b", "two")])
    assert base != input_digest([_record("b", "two"), _record("a", "one")])
    assert input_digest([_record("a", "bc")]) != input_digest([_record("ab", "c")])
    assert input_digest([_record("a", "b,c,d")]) != input_digest(
        [_record("a", "b"), _record("c", "d")]
    )


@pytest.mark.parametrize(
    ("text", "encoded"),
    [
        ('quote " and backslash \\', '"quote \\" and backslash \\\\"'),
        ("\b\f\n\r\t", '"\\b\\f\\n\\r\\t"'),
        ("\x00\x01\x0b\x1f", '"\\u0000\\u0001\\u000b\\u001f"'),
        ("\x7f\x80\u0085", '"\x7f\x80\u0085"'),
        ("line\u2028para\u2029end", '"line\u2028para\u2029end"'),
        ("nbsp\u00a0bom\ufeff", '"nbsp\u00a0bom\ufeff"'),
        ("\u00e9 — \u2713 \u4e2d\u6587", '"\u00e9 — \u2713 \u4e2d\u6587"'),
        ("astral \U0001f600 \U0001d11e", '"astral \U0001f600 \U0001d11e"'),
        ("pair \ud83d\ude00 joined", '"pair \U0001f600 joined"'),
        ("lone \ud800 high", '"lone \\ud800 high"'),
        ("lone \udfff low", '"lone \\udfff low"'),
        ("reversed \ude00\ud83d", '"reversed \\ude00\\ud83d"'),
        ("slash / stays", '"slash / stays"'),
    ],
)
def test_string_encoding_matches_json_stringify(text: str, encoded: str) -> None:
    assert js_json_stringify(text) == encoded


def test_string_encoding_agrees_with_compact_json_dumps_without_lone_surrogates() -> (
    None
):
    sample = "".join(chr(code) for code in range(0xD800)) + "".join(
        chr(code) for code in range(0xE000, 0x10000)
    )
    pairs = [
        ["field", sample],
        ["astral", "".join(chr(c) for c in range(0x1F600, 0x1F650))],
    ]
    assert js_json_stringify(pairs) == json.dumps(
        pairs, ensure_ascii=False, separators=(",", ":")
    )


def test_lone_surrogates_hash_as_their_escapes() -> None:
    fields = [_record("a", "x\ud800y")]
    assert digest_payload(fields) == '[["a","x\\ud800y"]]'
    expected = hashlib.sha256(b'[["a","x\\ud800y"]]').hexdigest()
    assert input_digest(fields) == "aiv1-" + expected


def test_object_keys_follow_javascript_property_order() -> None:
    assert js_json_stringify(
        {"b": 1, "10": 2, "a": [1.5, None], "2": True, "01": 0}
    ) == ('{"2":true,"10":2,"b":1,"a":[1.5,null],"01":0}')
    assert (
        js_json_stringify([1.0, -0.0, 1e21, 1e-7, float("nan")])
        == "[1,0,1e+21,1e-7,null]"
    )
