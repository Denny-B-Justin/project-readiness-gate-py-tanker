"""Single-field evaluation: request validation, preparation, the model call
and the readiness checks, run against fake model clients."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from pcn_clone.ai import (
    ENGINE_ERROR_MESSAGE,
    NOT_CONFIGURED_MESSAGE,
    FakeClient,
    FieldEvaluationResponse,
    ProviderError,
    evaluate_field,
    is_field_ready,
    readiness,
    shared_client,
)
from pcn_clone.ai.provider import ModelReply
from pcn_clone.ai.schemas import FIELD_EVALUATION_FORMAT, field_evaluation_schema
from pcn_clone.content import load_template
from pcn_clone.core.fields import serialize_field_answer
from tests.ai.conftest import SetAiEnvironment
from tests.ai.support import (
    RecordingClient,
    default_answer,
    default_answers,
    section_of,
)
from tests.helpers import load_fixture

FIELD_PROMPTS = load_fixture("prompts/field_prompts.json")
PASS_REPLY = {"verdict": "pass", "reasoning": "Meets the rubric.", "suggestions": []}


def _evaluate(
    field_id: str,
    answer: Any,
    client: Any,
    context: Any = None,
) -> FieldEvaluationResponse:
    return asyncio.run(
        evaluate_field(section_of(field_id), field_id, answer, context, client=client)
    )


class FailingClient:
    """A client whose every call raises the given provider error."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    async def complete(
        self, *, system: str, user: str, schema: dict[str, Any], format_name: str
    ) -> ModelReply:
        self.calls += 1
        raise self.error


def test_success_sends_the_golden_prompts() -> None:
    client = RecordingClient(PASS_REPLY, model="openai/gpt-x")
    response = _evaluate(
        "investment_cost_estimate",
        default_answer("investment_cost_estimate"),
        client,
        default_answers(),
    )
    assert response.ok
    assert response.result is not None
    assert response.result.verdict == "pass"
    assert response.model == "openai/gpt-x"
    assert response.section_id == "estimated_investment_costs_and_financing"
    assert response.field_id == "investment_cost_estimate"
    assert (response.issues, response.error_message, response.retryable) == (
        (),
        None,
        False,
    )
    [call] = client.calls
    expected = FIELD_PROMPTS["investment_cost_estimate"]
    assert call["system"] == expected["system"]
    assert call["user"] == expected["user"]
    assert call["schema"] == field_evaluation_schema()
    assert call["format_name"] == FIELD_EVALUATION_FORMAT


def test_wire_shape() -> None:
    success = _evaluate("project_title", "A road", RecordingClient(PASS_REPLY))
    assert success.to_json() == {
        "ok": True,
        "sectionId": "investment_identification",
        "fieldId": "project_title",
        "result": {
            "sectionId": "investment_identification",
            "fieldId": "project_title",
            **PASS_REPLY,
        },
        "model": "test/model",
    }
    failure = _evaluate("project_risks", [], RecordingClient(PASS_REPLY))
    assert failure.to_json() == {
        "ok": False,
        "sectionId": "project_management_and_risks",
        "fieldId": "project_risks",
        "errorMessage": (
            "This field is incomplete: Add at least one item before evaluating."
        ),
        "issues": ["Add at least one item before evaluating."],
        "retryable": False,
    }


def test_group_answer_may_be_raw_or_pre_serialized() -> None:
    raw = default_answer("implementation_period")
    field = load_template().get_field(
        "investment_identification", "implementation_period"
    )
    assert field is not None
    client = RecordingClient(PASS_REPLY)
    _evaluate("implementation_period", raw, client)
    _evaluate("implementation_period", serialize_field_answer(field, raw), client)
    assert client.calls[0]["user"] == client.calls[1]["user"]
    assert client.calls[0]["user"] == FIELD_PROMPTS["implementation_period"]["user"]


def test_success_with_fake_client() -> None:
    response = _evaluate("project_title", default_answer("project_title"), FakeClient())
    assert response.ok
    assert response.result is not None
    assert response.result.verdict in ("fail", "notClear", "pass")
    assert "1.1 Project title" in response.result.reasoning
    assert all("1.1 Project title" in s for s in response.result.suggestions)
    assert response.model == "fake/pcn-reviewer"


def test_incomplete_answer_returns_issues_without_a_call() -> None:
    client = RecordingClient(PASS_REPLY)
    response = _evaluate("project_risks", [], client)
    assert not response.ok
    assert response.issues == ("Add at least one item before evaluating.",)
    assert response.error_message == (
        "This field is incomplete: Add at least one item before evaluating."
    )
    assert not response.retryable
    assert response.result is None
    assert client.calls == []


def test_worksheet_without_context_is_incomplete() -> None:
    client = RecordingClient(PASS_REPLY)
    answer = default_answer("investment_cost_estimate")
    response = _evaluate("investment_cost_estimate", answer, client)
    assert not response.ok
    assert response.issues == (
        "Add at least one item in section 3.2 before completing the cost worksheet.",
    )
    assert client.calls == []


def test_injected_retryable_failure() -> None:
    response = _evaluate("project_title", "A road", FakeClient(fail={"project_title"}))
    assert not response.ok
    assert response.retryable
    assert response.error_message == ENGINE_ERROR_MESSAGE
    assert response.result is None
    other = _evaluate("objectives", "Better access", FakeClient(fail={"project_title"}))
    assert other.ok


def test_terminal_provider_failure(caplog: pytest.LogCaptureFixture) -> None:
    client = FailingClient(ProviderError("terminal", "HTTP 401", status=401))
    with caplog.at_level(logging.ERROR, logger="pcn_clone.ai.evaluate"):
        response = _evaluate("project_title", "A road", client)
    assert not response.ok
    assert not response.retryable
    assert response.error_message == ENGINE_ERROR_MESSAGE
    assert "HTTP 401" in caplog.text


def test_unexpected_client_exception_is_a_value() -> None:
    response = _evaluate("project_title", "A road", FailingClient(RuntimeError("boom")))
    assert not response.ok
    assert not response.retryable
    assert response.error_message == ENGINE_ERROR_MESSAGE


def test_reply_outside_the_contract_is_a_value() -> None:
    client = RecordingClient(
        {"verdict": "excellent", "reasoning": "r", "suggestions": []}
    )
    response = _evaluate("project_title", "A road", client)
    assert not response.ok
    assert not response.retryable
    assert response.error_message == ENGINE_ERROR_MESSAGE


def test_unknown_field() -> None:
    client = RecordingClient(PASS_REPLY)
    response = asyncio.run(
        evaluate_field("investment_identification", "nope", "x", client=client)
    )
    assert response == FieldEvaluationResponse(
        ok=False,
        error_message='Unknown field "investment_identification/nope".',
        section_id="investment_identification",
        field_id="nope",
    )
    assert client.calls == []


@pytest.mark.parametrize(
    ("section_id", "field_id", "answer", "context", "detail"),
    [
        ("", "project_title", "x", None, "sectionId: String should have at least"),
        ("investment_identification", "project_title", None, None, "answer: "),
        ("investment_identification", "project_title", 5, None, "answer: "),
        (
            "investment_identification",
            "project_title",
            "x",
            [{"sectionId": "s"}],
            "context.0.fieldId: Field required",
        ),
    ],
    ids=["empty-section", "null-answer", "number-answer", "bad-context"],
)
def test_invalid_request(
    section_id: str, field_id: str, answer: Any, context: Any, detail: str
) -> None:
    client = RecordingClient(PASS_REPLY)
    response = asyncio.run(
        evaluate_field(section_id, field_id, answer, context, client=client)
    )
    assert not response.ok
    assert response.error_message is not None
    assert response.error_message.startswith("Invalid request — ")
    assert detail in response.error_message
    assert client.calls == []


def test_missing_gateway_settings_are_a_terminal_not_configured_value(
    ai_env: SetAiEnvironment, caplog: pytest.LogCaptureFixture
) -> None:
    ai_env(PCN_AI_PROVIDER="WB-mAI")
    with caplog.at_level(logging.ERROR, logger="pcn_clone.ai.evaluate"):
        response = asyncio.run(
            evaluate_field("investment_identification", "project_title", "A road")
        )
    assert not response.ok
    assert not response.retryable
    assert response.error_message == NOT_CONFIGURED_MESSAGE
    assert "MAI_BASE_URL" in caplog.text
    assert "Traceback" not in caplog.text


def test_malformed_settings_are_a_not_configured_value(
    ai_env: SetAiEnvironment,
) -> None:
    ai_env(PCN_AI_PROVIDER="fake", PCN_AI_TIMEOUT_SECONDS="0")
    response = asyncio.run(
        evaluate_field("investment_identification", "project_title", "A road")
    )
    assert response.error_message == NOT_CONFIGURED_MESSAGE
    assert not response.retryable


def test_calls_share_one_client(
    ai_env: SetAiEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    ai_env(PCN_AI_PROVIDER="fake")
    seen: list[int] = []
    original = FakeClient.complete

    async def spy(self: FakeClient, **request: Any) -> ModelReply:
        seen.append(id(self))
        return await original(self, **request)

    monkeypatch.setattr(FakeClient, "complete", spy)
    for field_id in ("project_title", "objectives"):
        response = _evaluate(field_id, "A clear answer", None)
        assert response.ok
    assert len(seen) == 2
    assert seen[0] == seen[1] == id(shared_client())


# --- Readiness ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("field_id", "answer", "context"),
    [
        ("project_risks", [], None),
        ("project_risks", [{"risk_factor": "Floods"}], None),
        (
            "investment_cost_estimate",
            {"componentCosts": {}, "narratives": {}},
            "default",
        ),
        ("investment_cost_estimate", default_answer("investment_cost_estimate"), None),
        ("operating_costs", {"rows": {}, "narratives": {}}, None),
        ("documentation_and_permits", {"rows": {}}, None),
    ],
    ids=[
        "empty-list",
        "partial-list",
        "blank-worksheet",
        "worksheet-no-context",
        "blank-scenario",
        "blank-static-table",
    ],
)
def test_readiness_matches_evaluation_issues(
    field_id: str, answer: Any, context: Any
) -> None:
    resolved = default_answers() if context == "default" else context
    issues = readiness(section_of(field_id), field_id, answer, resolved)
    assert issues
    assert not is_field_ready(section_of(field_id), field_id, answer, resolved)
    response = _evaluate(field_id, answer, RecordingClient(PASS_REPLY), resolved)
    assert list(response.issues) == issues


def test_default_answers_are_ready() -> None:
    for section, field in load_template().iter_fields():
        answer = default_answer(field.id)
        assert readiness(section.id, field.id, answer, default_answers()) == []
        assert is_field_ready(section.id, field.id, answer, default_answers())


@pytest.mark.parametrize(
    ("field_id", "answer"),
    [
        ("project_title", ""),
        ("project_title", " \n"),
        ("implementation_period", {"project_start_date": "2026-01"}),
    ],
)
def test_blank_scalar_fields_are_not_ready_but_unexplained(
    field_id: str, answer: Any
) -> None:
    assert readiness(section_of(field_id), field_id, answer) == []
    assert not is_field_ready(section_of(field_id), field_id, answer)


def test_unknown_field_readiness() -> None:
    assert readiness("a", "b", "x") == ['Unknown field "a/b".']
    assert not is_field_ready("a", "b", "x")


@pytest.mark.parametrize(
    ("section_id", "field_id", "answer", "context", "detail"),
    [
        ("project_management_and_risks", "project_risks", [], [1, 2], "context.0"),
        ("project_management_and_risks", "project_risks", [], "x", "context"),
        ("project_management_and_risks", "project_risks", [], 5, "context"),
        (
            "estimated_investment_costs_and_financing",
            "investment_cost_estimate",
            {"componentCosts": {}, "narratives": {}},
            [{"sectionId": 1}],
            "context.0.sectionId",
        ),
        ("project_management_and_risks", "project_risks", ["x"], None, "answer"),
        ("project_management_and_risks", "project_risks", 7, None, "answer"),
        (1, "project_risks", [], None, "sectionId"),
    ],
    ids=[
        "numbers-as-context",
        "string-context",
        "non-iterable-context",
        "bad-context-entry",
        "non-record-list-item",
        "number-answer",
        "number-section",
    ],
)
def test_malformed_requests_explain_themselves(
    section_id: Any, field_id: Any, answer: Any, context: Any, detail: str
) -> None:
    [issue] = readiness(section_id, field_id, answer, context)
    assert issue.startswith("Invalid request — ")
    assert detail in issue
    assert not is_field_ready(section_id, field_id, answer, context)


@pytest.mark.parametrize(
    ("field_id", "expected"),
    [
        ("project_risks", ["Add at least one item before evaluating."]),
        ("project_title", []),
    ],
)
def test_absent_answer_reads_as_blank(field_id: str, expected: list[str]) -> None:
    assert readiness(section_of(field_id), field_id, None) == expected
    assert not is_field_ready(section_of(field_id), field_id, None)
