"""Whole-submission assessment and MCA scoring: the intake snapshot, the
request guards, reply validation and quote verification, the wire shapes and
concurrent calls, run against fake model clients."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import pytest

from pcn_clone.ai import (
    ASSESSMENT_ERROR_MESSAGE,
    NOT_CONFIGURED_MESSAGE,
    SCORING_ERROR_MESSAGE,
    AssessDimensionRequest,
    AssessDimensionResponse,
    FakeClient,
    IntakeSnapshot,
    ModelReply,
    ScoreCriterionRequest,
    ScoreCriterionResponse,
    assess_dimension,
    build_snapshot,
    score_criterion,
)
from pcn_clone.ai.schemas import ASSESSMENT_FINDING_FORMAT, MCA_SCORE_FINDING_FORMAT
from pcn_clone.content import (
    load_assessment,
    load_default_project,
    load_mca,
    load_template,
)
from pcn_clone.core.evidence import verify_quote
from tests.ai.conftest import SetAiEnvironment
from tests.ai.support import RecordingClient
from tests.helpers import load_fixture

SERIALIZED = load_fixture("serialized_default.json")
ASSESSMENT_PROMPTS = load_fixture("prompts/assessment_prompts.json")
MCA_PROMPTS = load_fixture("prompts/mca_prompts.json")
SCHEMAS = load_fixture("prompts/schemas.json")

FAKE_MODEL = "fake/pcn-reviewer"
DIMENSIONS = [dimension.id for dimension in load_assessment().dimensions]
CRITERIA = [criterion.id for criterion in load_mca().matrix.criteria]

TITLE_CITATION = {
    "sectionId": "investment_identification",
    "fieldId": "project_title",
    "quote": "Rehabilitation of the 18 km Upper Valley District Road",
}
DIMENSION_REPLY = {
    "verdict": "pass",
    "reasoning": "Meets the rubric.",
    "evidence": [TITLE_CITATION],
    "questions": ["Is the design final?"],
}
NOT_EVIDENCED_REPLY = {
    "justification": "The document is silent on this criterion.",
    "basis": {"kind": "not_evidenced", "score": 1},
}
DOCUMENTED_REPLY = {
    "justification": "The cited passage matches the descriptor for score 4.",
    "basis": {"kind": "documented", "score": 4, "evidence": [TITLE_CITATION]},
}


@pytest.fixture(autouse=True)
def fake_provider(ai_env: SetAiEnvironment) -> None:
    """Every test runs under the fake provider, whose model is
    ``fake/pcn-reviewer``."""
    ai_env(PCN_AI_PROVIDER="fake")


def _snapshot() -> IntakeSnapshot:
    return build_snapshot(load_default_project().submission)


def _pins(snapshot: IntakeSnapshot) -> dict[str, Any]:
    data = snapshot.to_json()
    return {
        key: data[key]
        for key in (
            "templateId",
            "templateVersion",
            "model",
            "assessmentInputDigest",
            "submission",
        )
    }


def _dimension_request(dimension_id: str, **changes: Any) -> dict[str, Any]:
    snapshot = _snapshot()
    return {
        **_pins(snapshot),
        "assessmentSetId": snapshot.assessment_set_id,
        "assessmentSetVersion": snapshot.assessment_set_version,
        "dimensionId": dimension_id,
        **changes,
    }


def _criterion_request(criterion_id: str, **changes: Any) -> dict[str, Any]:
    snapshot = _snapshot()
    return {
        **_pins(snapshot),
        "mcaSetId": snapshot.mca_set_id,
        "mcaSetVersion": snapshot.mca_set_version,
        "criterionId": criterion_id,
        **changes,
    }


def _assess(request: Any, client: Any) -> AssessDimensionResponse:
    return asyncio.run(assess_dimension(request, client=client))


def _score(request: Any, client: Any) -> ScoreCriterionResponse:
    return asyncio.run(score_criterion(request, client=client))


def _foreign_submission() -> dict[str, Any]:
    submission = _snapshot().to_json()["submission"]
    return {**submission, "templateId": "pcn_other"}


def _unknown_field_answer() -> dict[str, Any]:
    submission = _snapshot().to_json()["submission"]
    extra = {"sectionId": "nowhere", "fieldId": "nothing", "answer": "x"}
    return {**submission, "answers": [*submission["answers"], extra]}


def _edited_submission() -> dict[str, Any]:
    submission = _snapshot().to_json()["submission"]
    first, *rest = submission["answers"]
    return {**submission, "answers": [{**first, "answer": "A new title"}, *rest]}


# --- The intake snapshot -----------------------------------------------------


def test_snapshot_of_the_default_project_matches_the_fixture() -> None:
    snapshot = _snapshot()
    data = snapshot.to_json()
    template, assessment, mca = load_template(), load_assessment(), load_mca()
    assert list(data) == [
        "templateId",
        "templateLabel",
        "templateVersion",
        "assessmentSetId",
        "assessmentSetVersion",
        "mcaSetId",
        "mcaSetVersion",
        "model",
        "assessmentInputDigest",
        "submission",
        "fields",
        "dimensionDefs",
        "matrix",
    ]
    assert data["assessmentInputDigest"].startswith("aiv1-9c67")
    assert data["assessmentInputDigest"] == SERIALIZED["digest"]
    assert data["fields"] == SERIALIZED["fields"]
    assert data["submission"] == {
        "templateId": SERIALIZED["templateId"],
        "answers": SERIALIZED["canonicalAnswers"],
    }
    assert (
        data["templateId"],
        data["templateLabel"],
        data["templateVersion"],
    ) == (template.id, template.label, template.version)
    assert (data["assessmentSetId"], data["assessmentSetVersion"]) == (
        assessment.id,
        assessment.version,
    )
    assert (data["mcaSetId"], data["mcaSetVersion"]) == (mca.id, mca.version)
    assert data["model"] == FAKE_MODEL
    assert data["dimensionDefs"] == [d.to_json() for d in assessment.dimensions]
    assert set(data["dimensionDefs"][0]) == {
        "id",
        "label",
        "description",
        "guidance",
        "verdicts",
    }
    assert set(data["dimensionDefs"][0]["verdicts"]) == {"fail", "notClear", "pass"}
    assert data["matrix"] == mca.matrix.to_json()
    assert set(data["matrix"]) == {"scale", "bands", "criteria"}


def test_snapshot_accepts_the_json_shape_and_completes_blanks() -> None:
    title = SERIALIZED["canonicalAnswers"][0]
    snapshot = build_snapshot({"templateId": "pcn_global", "answers": [title]})
    answers = snapshot.submission["answers"]
    assert len(answers) == len(SERIALIZED["canonicalAnswers"])
    assert answers[0] == title
    assert snapshot.fields[1].serialized_text == "No answer provided."


def test_snapshot_model_is_the_configured_mai_model(
    ai_env: SetAiEnvironment,
) -> None:
    ai_env(
        PCN_AI_PROVIDER="WB-mAI",
        MAI_BASE_URL="https://gateway.example.invalid/posit-mai/conversationalai/",
        MAI_ENDPOINT=(
            "https://mai.example.invalid/maifactory/bedrock/model/"
            "us.anthropic.<model>/converse"
        ),
        MAI_MODEL="us.anthropic.claude-haiku-5-5",
        CONNECT_CONTENT_GUID="0b7e3a52-6c1d-4f7e-9a0b-2f5d8c4e1a93",
    )
    assert _snapshot().model == "claude-haiku-5-5"


@pytest.mark.parametrize(
    "submission",
    [
        pytest.param(_foreign_submission, id="foreign-template"),
        pytest.param(_unknown_field_answer, id="unknown-field"),
        pytest.param(
            lambda: {"templateId": "pcn_global", "answers": []}, id="no-answers"
        ),
    ],
)
def test_snapshot_rejects_a_submission_outside_the_template(submission: Any) -> None:
    with pytest.raises(ValueError):
        build_snapshot(submission())


# --- A full run --------------------------------------------------------------


def test_full_run_over_the_default_project() -> None:
    snapshot = _snapshot()
    text_by_ref = {
        (f.section_id, f.field_id): f.serialized_text for f in snapshot.fields
    }
    client = FakeClient()

    async def run() -> tuple[list[Any], list[Any]]:
        dimensions = await asyncio.gather(
            *(
                assess_dimension(_dimension_request(d), client=client)
                for d in DIMENSIONS
            )
        )
        criteria = await asyncio.gather(
            *(score_criterion(_criterion_request(c), client=client) for c in CRITERIA)
        )
        return list(dimensions), list(criteria)

    dimensions, criteria = asyncio.run(run())
    citations = []
    for dimension_id, response in zip(DIMENSIONS, dimensions, strict=True):
        assert response.ok, response.error_message
        finding = response.finding
        assert finding is not None
        assert (finding.dimension_id, finding.model) == (dimension_id, FAKE_MODEL)
        assert finding.evidence
        citations.extend(finding.evidence)
    scale = load_mca().matrix
    for criterion_id, response in zip(CRITERIA, criteria, strict=True):
        assert response.ok, response.error_message
        score = response.finding
        assert score is not None
        assert (score.criterion_id, score.model) == (criterion_id, FAKE_MODEL)
        assert scale.scale_minimum <= score.score <= scale.scale_maximum
        assert score.basis == "documented"
        assert 1 <= len(score.evidence) <= 3
        citations.extend(score.evidence)
    for citation in citations:
        cited = text_by_ref[(citation.section_id, citation.field_id)]
        assert verify_quote(citation.quote, cited)
        assert citation.verified


# --- Prompts -----------------------------------------------------------------


@pytest.mark.parametrize("dimension_id", DIMENSIONS)
def test_assessment_sends_the_golden_prompts(dimension_id: str) -> None:
    client = RecordingClient(DIMENSION_REPLY)
    assert _assess(_dimension_request(dimension_id), client).ok
    [call] = client.calls
    expected = ASSESSMENT_PROMPTS[dimension_id]
    assert (call["system"], call["user"]) == (expected["system"], expected["user"])
    assert call["schema"] == SCHEMAS["assessmentFinding"]
    assert call["format_name"] == ASSESSMENT_FINDING_FORMAT


@pytest.mark.parametrize("criterion_id", CRITERIA)
def test_scoring_sends_the_golden_prompts(criterion_id: str) -> None:
    client = RecordingClient(NOT_EVIDENCED_REPLY)
    assert _score(_criterion_request(criterion_id), client).ok
    [call] = client.calls
    expected = MCA_PROMPTS[criterion_id]
    assert (call["system"], call["user"]) == (expected["system"], expected["user"])
    assert call["schema"] == SCHEMAS["mcaScoreFinding"]
    assert call["format_name"] == MCA_SCORE_FINDING_FORMAT


# --- Replies -----------------------------------------------------------------


def test_finding_carries_the_request_model_not_the_reply_model() -> None:
    response = _assess(
        _dimension_request("cost_realism"), RecordingClient(DIMENSION_REPLY)
    )
    assert response.finding is not None
    assert response.finding.model == FAKE_MODEL


def test_paraphrased_quote_is_kept_unverified() -> None:
    paraphrase = {**TITLE_CITATION, "quote": "Upgrading the valley road"}
    reply = {**DIMENSION_REPLY, "evidence": [TITLE_CITATION, paraphrase]}
    response = _assess(_dimension_request("cost_realism"), RecordingClient(reply))
    assert response.finding is not None
    assert [c.verified for c in response.finding.evidence] == [True, False]


def test_documented_score_verifies_its_quotes() -> None:
    paraphrase = {**TITLE_CITATION, "quote": "Upgrading the valley road"}
    basis = {**DOCUMENTED_REPLY["basis"], "evidence": [paraphrase]}
    reply = {**DOCUMENTED_REPLY, "basis": basis}
    response = _score(
        _criterion_request("environmental_impact"), RecordingClient(reply)
    )
    assert response.finding is not None
    assert (response.finding.score, response.finding.basis) == (4, "documented")
    assert [c.verified for c in response.finding.evidence] == [False]


def test_unknown_citation_rejects_the_finding(
    caplog: pytest.LogCaptureFixture,
) -> None:
    invented = {**TITLE_CITATION, "fieldId": "project_slogan"}
    reply = {**DIMENSION_REPLY, "evidence": [TITLE_CITATION, invented]}
    with caplog.at_level(logging.ERROR):
        response = _assess(_dimension_request("cost_realism"), RecordingClient(reply))
    assert response.to_json() == {
        "ok": False,
        "dimensionId": "cost_realism",
        "errorMessage": ASSESSMENT_ERROR_MESSAGE,
        "error": {"kind": "retryable", "code": "provider_error"},
    }
    assert 'Assessment of dimension "cost_realism" failed' in caplog.text


def test_unknown_citation_rejects_the_score() -> None:
    invented = {**TITLE_CITATION, "sectionId": "appendix"}
    basis = {**DOCUMENTED_REPLY["basis"], "evidence": [invented]}
    reply = {**DOCUMENTED_REPLY, "basis": basis}
    response = _score(
        _criterion_request("environmental_impact"), RecordingClient(reply)
    )
    assert response.to_json() == {
        "ok": False,
        "criterionId": "environmental_impact",
        "errorMessage": SCORING_ERROR_MESSAGE,
        "error": {"kind": "retryable", "code": "provider_error"},
    }


@pytest.mark.parametrize("score", [2, 5])
def test_not_evidenced_above_the_minimum_is_rejected(score: int) -> None:
    reply = {**NOT_EVIDENCED_REPLY, "basis": {"kind": "not_evidenced", "score": score}}
    response = _score(
        _criterion_request("environmental_impact"), RecordingClient(reply)
    )
    assert not response.ok
    assert response.error is not None
    assert response.error.to_json() == {"kind": "retryable", "code": "provider_error"}


def test_reply_outside_the_contract_is_rejected() -> None:
    reply = {**DIMENSION_REPLY, "verdict": "excellent"}
    response = _assess(_dimension_request("cost_realism"), RecordingClient(reply))
    assert response.error is not None
    assert response.error.code == "provider_error"


def test_provider_failure_is_retryable(caplog: pytest.LogCaptureFixture) -> None:
    client = FakeClient(fail=["*"])
    with caplog.at_level(logging.ERROR):
        assessed = _assess(_dimension_request("cost_realism"), client)
        scored = _score(_criterion_request("environmental_impact"), client)
    assert (assessed.error_message, scored.error_message) == (
        ASSESSMENT_ERROR_MESSAGE,
        SCORING_ERROR_MESSAGE,
    )
    for response in (assessed, scored):
        assert response.error is not None
        assert response.error.to_json() == {
            "kind": "retryable",
            "code": "provider_error",
        }
    assert "Injected fake failure" in caplog.text


def test_unusable_settings_are_a_not_configured_value(
    ai_env: SetAiEnvironment,
) -> None:
    request = _dimension_request("cost_realism")
    ai_env(PCN_AI_PROVIDER="WB-mAI")
    client = RecordingClient(DIMENSION_REPLY)
    response = _assess(request, client)
    assert response.error_message == NOT_CONFIGURED_MESSAGE
    assert response.error is not None
    assert response.error.to_json() == {"kind": "retryable", "code": "provider_error"}
    assert client.calls == []


# --- Guards ------------------------------------------------------------------

DIMENSION_GUARDS = [
    pytest.param(
        {"templateId": "pcn_other"},
        "unknown_template",
        'Template "pcn_other" is not registered on this platform.',
        id="unknown-template",
    ),
    pytest.param(
        {"assessmentSetId": "other_set"},
        "unknown_assessment_set",
        'Assessment set "other_set" is not registered for template "pcn_global".',
        id="unknown-set",
    ),
    pytest.param(
        {"dimensionId": "beauty"},
        "unknown_dimension",
        'Assessment set "pcn_global_reviewer_default" has no dimension "beauty".',
        id="unknown-dimension",
    ),
    pytest.param(
        {"templateVersion": "1.4.0"},
        "template_version_mismatch",
        'Template "pcn_global" is now version "1.5.0"; this review was created '
        'against "1.4.0".',
        id="template-version",
    ),
    pytest.param(
        {"assessmentSetVersion": "0.2.0"},
        "assessment_set_version_mismatch",
        'Assessment set "pcn_global_reviewer_default" is now version "0.3.0"; '
        'this review was created against "0.2.0".',
        id="set-version",
    ),
    pytest.param(
        {"model": "openai/gpt-4o"},
        "model_mismatch",
        f'The platform now assesses with "{FAKE_MODEL}"; this review was created '
        'against "openai/gpt-4o".',
        id="model",
    ),
    pytest.param(
        {"assessmentInputDigest": "aiv1-0000"},
        "input_digest_mismatch",
        "The platform no longer serializes this submission to the text this "
        "review recorded.",
        id="digest",
    ),
]

CRITERION_GUARDS = [
    pytest.param(
        {"templateId": "pcn_other"},
        "unknown_template",
        'Template "pcn_other" is not registered on this platform.',
        id="unknown-template",
    ),
    pytest.param(
        {"mcaSetId": "other_set"},
        "unknown_mca_set",
        'MCA set "other_set" is not registered for template "pcn_global".',
        id="unknown-set",
    ),
    pytest.param(
        {"criterionId": "beauty"},
        "unknown_mca_criterion",
        'MCA set "pcn_global_mca_default" has no criterion "beauty".',
        id="unknown-criterion",
    ),
    pytest.param(
        {"templateVersion": "1.4.0"},
        "template_version_mismatch",
        'Template "pcn_global" is now version "1.5.0"; this review was created '
        'against "1.4.0".',
        id="template-version",
    ),
    pytest.param(
        {"mcaSetVersion": "0.0.9"},
        "mca_set_version_mismatch",
        'MCA set "pcn_global_mca_default" is now version "0.1.0"; this review '
        'was created against "0.0.9".',
        id="set-version",
    ),
    pytest.param(
        {"model": "openai/gpt-4o"},
        "model_mismatch",
        f'The platform now scores with "{FAKE_MODEL}"; this review was created '
        'against "openai/gpt-4o".',
        id="model",
    ),
    pytest.param(
        {"assessmentInputDigest": "aiv1-0000"},
        "input_digest_mismatch",
        "The platform no longer serializes this submission to the text this "
        "review recorded.",
        id="digest",
    ),
]


@pytest.mark.parametrize(("changes", "code", "message"), DIMENSION_GUARDS)
def test_dimension_guards_are_terminal(
    changes: dict[str, str], code: str, message: str
) -> None:
    client = RecordingClient(DIMENSION_REPLY)
    response = _assess(_dimension_request("cost_realism", **changes), client)
    assert response.to_json() == {
        "ok": False,
        "dimensionId": changes.get("dimensionId", "cost_realism"),
        "errorMessage": message,
        "error": {"kind": "terminal", "code": code},
    }
    assert client.calls == []


@pytest.mark.parametrize(("changes", "code", "message"), CRITERION_GUARDS)
def test_criterion_guards_are_terminal(
    changes: dict[str, str], code: str, message: str
) -> None:
    client = RecordingClient(NOT_EVIDENCED_REPLY)
    response = _score(_criterion_request("environmental_impact", **changes), client)
    assert response.to_json() == {
        "ok": False,
        "criterionId": changes.get("criterionId", "environmental_impact"),
        "errorMessage": message,
        "error": {"kind": "terminal", "code": code},
    }
    assert client.calls == []


def test_edited_submission_fails_the_digest() -> None:
    client = RecordingClient(DIMENSION_REPLY)
    request = _dimension_request("cost_realism", submission=_edited_submission())
    response = _assess(request, client)
    assert response.error is not None
    assert response.error.code == "input_digest_mismatch"
    assert client.calls == []


@pytest.mark.parametrize(
    "submission",
    [
        pytest.param(_foreign_submission, id="foreign-template"),
        pytest.param(_unknown_field_answer, id="unknown-field"),
    ],
)
def test_inconsistent_submission_is_terminal(submission: Any) -> None:
    client = RecordingClient(NOT_EVIDENCED_REPLY)
    request = _criterion_request("environmental_impact", submission=submission())
    response = _score(request, client)
    assert response.error is not None
    assert response.error.to_json() == {
        "kind": "terminal",
        "code": "inconsistent_submission",
    }
    assert response.error_message
    assert "Cannot canonicalize an inconsistent submission" in response.error_message
    assert client.calls == []


# --- Requests ----------------------------------------------------------------


def _without(request: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: value for name, value in request.items() if name != key}


@pytest.mark.parametrize(
    ("request_json", "dimension_id", "detail"),
    [
        pytest.param(None, "", "(root): ", id="not-an-object"),
        pytest.param(
            lambda: _without(_dimension_request("cost_realism"), "model"),
            "cost_realism",
            "model: Field required",
            id="missing-pin",
        ),
        pytest.param(
            lambda: _dimension_request("cost_realism", templateVersion=""),
            "cost_realism",
            "templateVersion: ",
            id="empty-pin",
        ),
        pytest.param(
            lambda: _dimension_request("cost_realism", mcaRevision="mrv1-x"),
            "cost_realism",
            "mcaRevision: Extra inputs are not permitted",
            id="foreign-pin",
        ),
        pytest.param(
            lambda: _dimension_request("cost_realism", dimensionId=7),
            "",
            "dimensionId: ",
            id="non-string-id",
        ),
    ],
)
def test_invalid_request_is_terminal(
    request_json: Any, dimension_id: str, detail: str
) -> None:
    client = RecordingClient(DIMENSION_REPLY)
    payload = request_json() if callable(request_json) else request_json
    response = _assess(payload, client)
    data = response.to_json()
    assert (data["ok"], data["dimensionId"]) == (False, dimension_id)
    assert data["error"] == {"kind": "terminal", "code": "invalid_request"}
    assert data["errorMessage"].startswith("Invalid request — ")
    assert detail in data["errorMessage"]
    assert client.calls == []


def test_invalid_scoring_request_echoes_the_criterion() -> None:
    request = _without(_criterion_request("environmental_impact"), "mcaSetId")
    response = _score(request, RecordingClient(NOT_EVIDENCED_REPLY))
    assert response.criterion_id == "environmental_impact"
    assert response.error is not None
    assert response.error.to_json() == {"kind": "terminal", "code": "invalid_request"}


def test_request_models_are_accepted() -> None:
    assessed = _assess(
        AssessDimensionRequest.model_validate(_dimension_request("cost_realism")),
        RecordingClient(DIMENSION_REPLY),
    )
    scored = _score(
        ScoreCriterionRequest.model_validate(
            _criterion_request("environmental_impact")
        ),
        RecordingClient(NOT_EVIDENCED_REPLY),
    )
    assert assessed.ok
    assert scored.ok


# --- Wire shapes -------------------------------------------------------------


def test_dimension_wire_shape() -> None:
    response = _assess(
        _dimension_request("cost_realism"), RecordingClient(DIMENSION_REPLY)
    )
    assert response.to_json() == {
        "ok": True,
        "dimensionId": "cost_realism",
        "finding": {
            "dimensionId": "cost_realism",
            "model": FAKE_MODEL,
            "verdict": "pass",
            "reasoning": "Meets the rubric.",
            "evidence": [{**TITLE_CITATION, "verified": True}],
            "questions": ["Is the design final?"],
        },
    }


def test_documented_score_wire_shape() -> None:
    response = _score(
        _criterion_request("environmental_impact"), RecordingClient(DOCUMENTED_REPLY)
    )
    assert response.to_json() == {
        "ok": True,
        "criterionId": "environmental_impact",
        "finding": {
            "criterionId": "environmental_impact",
            "model": FAKE_MODEL,
            "score": 4,
            "justification": DOCUMENTED_REPLY["justification"],
            "basis": {
                "kind": "documented",
                "evidence": [{**TITLE_CITATION, "verified": True}],
            },
        },
    }


def test_not_evidenced_score_wire_shape() -> None:
    response = _score(
        _criterion_request("environmental_impact"),
        RecordingClient(NOT_EVIDENCED_REPLY),
    )
    assert response.to_json() == {
        "ok": True,
        "criterionId": "environmental_impact",
        "finding": {
            "criterionId": "environmental_impact",
            "model": FAKE_MODEL,
            "score": 1,
            "justification": NOT_EVIDENCED_REPLY["justification"],
            "basis": {"kind": "not_evidenced"},
        },
    }


# --- Concurrency -------------------------------------------------------------


class CountingClient:
    """A fake client that records how many calls are in flight at once."""

    def __init__(self, delay_seconds: float) -> None:
        self.inner = FakeClient(delay_seconds=delay_seconds)
        self.in_flight = 0
        self.peak = 0

    async def complete(
        self, *, system: str, user: str, schema: dict[str, Any], format_name: str
    ) -> ModelReply:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            return await self.inner.complete(
                system=system, user=user, schema=schema, format_name=format_name
            )
        finally:
            self.in_flight -= 1


def test_nine_gathered_calls_overlap() -> None:
    delay = 0.3
    client = CountingClient(delay)
    dimension_requests = [_dimension_request(d) for d in DIMENSIONS]
    criterion_requests = [_criterion_request(c) for c in CRITERIA]

    async def run() -> list[Any]:
        return list(
            await asyncio.gather(
                *(assess_dimension(r, client=client) for r in dimension_requests),
                *(score_criterion(r, client=client) for r in criterion_requests),
            )
        )

    started = time.perf_counter()
    responses = asyncio.run(run())
    elapsed = time.perf_counter() - started
    assert len(responses) == 9
    assert all(response.ok for response in responses)
    assert client.peak == 9
    assert elapsed < delay * 3
