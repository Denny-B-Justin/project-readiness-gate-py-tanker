"""The structured-output schemas match the golden schemas, and the
reply models enforce what the schemas cannot."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from pcn_clone.ai.schemas import (
    ASSESSMENT_FINDING_FORMAT,
    ASSESSMENT_QUOTE_MAX_LENGTH,
    FIELD_EVALUATION_FORMAT,
    MCA_JUSTIFICATION_MAX_LENGTH,
    MCA_MAX_CITATIONS,
    MCA_QUOTE_MAX_LENGTH,
    MCA_SCORE_FINDING_FORMAT,
    VERDICTS,
    AssessmentFinding,
    FieldEvaluation,
    McaScoreFinding,
    ReplyScope,
    assessment_finding_schema,
    field_evaluation_schema,
    mca_score_finding_schema,
)
from pcn_clone.content import load_mca
from tests.ai.support import default_fields
from tests.helpers import load_fixture

SCHEMAS = load_fixture("prompts/schemas.json")

CITATION = {
    "sectionId": "investment_identification",
    "fieldId": "project_title",
    "quote": "Rehabilitation of the 18 km Upper Valley District Road",
}


def _scope() -> ReplyScope:
    return ReplyScope(fields=default_fields(), matrix=load_mca().matrix)


def test_field_evaluation_schema() -> None:
    assert field_evaluation_schema() == SCHEMAS["fieldEvaluation"]


def test_assessment_finding_schema() -> None:
    assert assessment_finding_schema(default_fields()) == SCHEMAS["assessmentFinding"]


def test_mca_score_finding_schema() -> None:
    schema = mca_score_finding_schema(default_fields(), load_mca().matrix)
    assert schema == SCHEMAS["mcaScoreFinding"]


def test_format_names_and_constants() -> None:
    assert SCHEMAS["formatNames"] == {
        "fieldEvaluation": FIELD_EVALUATION_FORMAT,
        "assessmentFinding": ASSESSMENT_FINDING_FORMAT,
        "mcaScoreFinding": MCA_SCORE_FINDING_FORMAT,
    }
    constants = SCHEMAS["constants"]
    assert constants["ASSESSMENT_QUOTE_MAX_LENGTH"] == ASSESSMENT_QUOTE_MAX_LENGTH
    assert constants["MCA_QUOTE_MAX_LENGTH"] == MCA_QUOTE_MAX_LENGTH
    assert constants["MCA_JUSTIFICATION_MAX_LENGTH"] == MCA_JUSTIFICATION_MAX_LENGTH
    assert constants["MCA_MAX_CITATIONS"] == MCA_MAX_CITATIONS
    assert constants["verdicts"] == list(VERDICTS)


def test_builders_return_fresh_objects() -> None:
    first = assessment_finding_schema(default_fields())
    first["properties"]["evidence"]["items"]["anyOf"].clear()
    assert assessment_finding_schema(default_fields()) == SCHEMAS["assessmentFinding"]


def test_single_section_needs_no_definitions() -> None:
    fields = [f for f in default_fields() if f.section_id == "investment_rationale"]
    schema = assessment_finding_schema(fields)
    assert "definitions" not in schema
    items = schema["properties"]["evidence"]["items"]
    assert items["properties"]["sectionId"]["const"] == "investment_rationale"
    assert items["properties"]["fieldId"]["enum"] == [
        "issues_and_justification",
        "objectives",
    ]
    assert items["properties"]["quote"]["maxLength"] == ASSESSMENT_QUOTE_MAX_LENGTH


def test_duplicate_fields_are_listed_once() -> None:
    field = default_fields()[0]
    items = assessment_finding_schema([field, field])["properties"]["evidence"]["items"]
    assert items["properties"]["fieldId"]["enum"] == [field.field_id]


def test_zero_fields_rejected() -> None:
    with pytest.raises(ValueError, match="over zero fields"):
        assessment_finding_schema([])
    with pytest.raises(ValueError, match="over zero fields"):
        mca_score_finding_schema([], load_mca().matrix)


# --- Field evaluation --------------------------------------------------------


def test_field_evaluation_accepts_reply() -> None:
    reply = FieldEvaluation.model_validate(
        {"verdict": "notClear", "reasoning": "r", "suggestions": ["s"], "extra": 1}
    )
    assert reply.verdict == "notClear"
    assert reply.suggestions == ["s"]


@pytest.mark.parametrize(
    "data",
    [
        {"verdict": "great", "reasoning": "r", "suggestions": []},
        {"verdict": "pass", "reasoning": 1, "suggestions": []},
        {"verdict": "pass", "reasoning": "r"},
        {"verdict": "pass", "reasoning": "r", "suggestions": "s"},
    ],
    ids=["bad-verdict", "non-string-reasoning", "missing-suggestions", "not-a-list"],
)
def test_field_evaluation_rejects(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        FieldEvaluation.model_validate(data)


# --- Assessment finding ------------------------------------------------------


def _finding(**evidence: Any) -> dict[str, Any]:
    return {
        "verdict": "pass",
        "reasoning": "r",
        "evidence": [{**CITATION, **evidence}],
        "questions": [],
    }


def test_assessment_finding_accepts_reply() -> None:
    finding = AssessmentFinding.model_validate(_finding(), context=_scope())
    assert finding.evidence[0].section_id == "investment_identification"
    assert finding.model_dump(by_alias=True)["evidence"][0] == CITATION


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (_finding(quote=" \n﻿ "), "Quote must not be blank"),
        (_finding(quote=""), "at least 1 character"),
        (_finding(quote="x" * 301), "at most 300 characters"),
        (_finding(quote="\U0001f600" * 151), "at most 300 characters"),
        ({**_finding(), "verdict": "excellent"}, "verdict"),
        ({**_finding(), "dimensionId": "x"}, "Extra inputs"),
    ],
    ids=[
        "blank-quote",
        "empty-quote",
        "301-chars",
        "302-utf16-units",
        "bad-verdict",
        "engine-owned-key",
    ],
)
def test_assessment_finding_rejects(data: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        AssessmentFinding.model_validate(data)


def test_quote_of_300_chars_accepted() -> None:
    AssessmentFinding.model_validate(_finding(quote="x" * 300))


def test_citation_must_name_a_submission_field() -> None:
    data = _finding(fieldId="objectives")
    AssessmentFinding.model_validate(data)
    with pytest.raises(ValidationError, match="is not a field of the submission"):
        AssessmentFinding.model_validate(data, context=_scope())


# --- MCA score finding -------------------------------------------------------


def _documented(score: Any = 3, count: int = 1) -> dict[str, Any]:
    return {
        "justification": "The cited text matches descriptor three.",
        "basis": {
            "kind": "documented",
            "score": score,
            "evidence": [copy.deepcopy(CITATION) for _ in range(count)],
        },
    }


def _not_evidenced(score: Any = 1) -> dict[str, Any]:
    return {
        "justification": "The submission is silent on this criterion.",
        "basis": {"kind": "not_evidenced", "score": score},
    }


@pytest.mark.parametrize(
    "data",
    [_documented(), _documented(5, 3), _documented(1.0), _not_evidenced()],
    ids=["documented", "three-citations-max-score", "integral-float", "not-evidenced"],
)
def test_mca_score_finding_accepts(data: dict[str, Any]) -> None:
    finding = McaScoreFinding.model_validate(data, context=_scope())
    assert finding.basis.kind == data["basis"]["kind"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (_documented(count=4), "at most 3 items"),
        (_documented(count=0), "at least 1 item"),
        (_not_evidenced(2), "must be the scale minimum"),
        (_documented(6), "on the scale 1..5"),
        (_documented(0), "greater than or equal to 1"),
        (_documented(2.5), "integer"),
        (_documented("3"), "expected a finite number"),
        ({**_documented(), "justification": "   "}, "Justification must not be blank"),
        ({**_documented(), "justification": "j" * 601}, "at most 600 characters"),
        (
            {"justification": "j", "basis": {"kind": "guess", "score": 1}},
            "does not match any of the expected tags",
        ),
        (
            {
                "justification": "j",
                "basis": {**_not_evidenced()["basis"], "evidence": []},
            },
            "Extra inputs",
        ),
    ],
    ids=[
        "four-citations",
        "no-citations",
        "not-evidenced-score-2",
        "above-scale",
        "below-scale",
        "fractional",
        "string-score",
        "blank-justification",
        "601-char-justification",
        "unknown-kind",
        "not-evidenced-with-evidence",
    ],
)
def test_mca_score_finding_rejects(data: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        McaScoreFinding.model_validate(data, context=_scope())


def test_not_evidenced_minimum_holds_without_scope() -> None:
    with pytest.raises(ValidationError, match="must be the scale minimum"):
        McaScoreFinding.model_validate(_not_evidenced(2))
    McaScoreFinding.model_validate(_documented(9))
