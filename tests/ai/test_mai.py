"""The mAI Gateway client: settings resolution, the request each model
family sends, reply handling, failure classification, the schema
compatibility ladder, bounded retries and deadline, connection reuse and
privacy.

Requests go through the real SDKs and HTTP code to a local fake gateway
(:mod:`tests.ai.fake_gateway`); most tests run once per model family.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import random
import socket
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import pytest

from pcn_clone.ai import evaluate_field
from pcn_clone.ai.config import (
    DEFAULT_MODELS,
    AiConfigurationError,
    AiSettings,
    MaiConnection,
    resolve_mai,
)
from pcn_clone.ai.mai import (
    ANSWER_TOOL_DESCRIPTION,
    CLAUDE_DEFAULT_MAX_TOKENS,
    MaiClient,
    schema_at_level,
)
from pcn_clone.ai.provider import (
    DEADLINE_CAP_SECONDS,
    ModelReply,
    ProviderError,
    TokenUsage,
    classify_status,
    retry_after_seconds,
)
from pcn_clone.ai.schemas import (
    ASSESSMENT_FINDING_FORMAT,
    FIELD_EVALUATION_FORMAT,
    MCA_SCORE_FINDING_FORMAT,
    assessment_finding_schema,
    field_evaluation_schema,
    mca_score_finding_schema,
)
from pcn_clone.content import load_mca
from tests.ai.fake_gateway import (
    FAMILIES,
    USAGE,
    FakeGateway,
    Family,
    Reply,
    claude_body,
    gemini_body,
    gpt_body,
    request_parts,
)
from tests.ai.support import default_fields
from tests.helpers import load_fixture

REPLY = {"verdict": "pass", "reasoning": "Meets the rubric.", "suggestions": []}
GUID = "0b7e3a52-6c1d-4f7e-9a0b-2f5d8c4e1a93"
ENDPOINTS: dict[Family, str] = {
    "gpt": "https://azapimqa.example.invalid/maifactory/openai/responses",
    "gemini": "https://azapimqa.example.invalid/maifactory/gemini/interactions",
    "claude": (
        "https://azapimqa.example.invalid/maifactory/bedrock/model/"
        "us.anthropic.claude-haiku-5-5/converse"
    ),
}
PATHS: dict[Family, str] = {
    "gpt": "/responses",
    "gemini": "/interactions",
    "claude": "/converse",
}
PLACEHOLDER_CREDENTIALS = {
    "authorization": "Bearer not-used",
    "x-goog-api-key": "not-used",
}


@pytest.fixture(params=FAMILIES)
def family(request: pytest.FixtureRequest) -> Family:
    value: Family = request.param
    return value


@pytest.fixture
def gateway(family: Family) -> Iterator[FakeGateway]:
    """A fake gateway for each model family in turn."""
    with FakeGateway(family, answer=REPLY) as running:
        yield running


@pytest.fixture
def http_gateway() -> Iterator[FakeGateway]:
    """A fake gateway for the plain-HTTP (Claude) family, for behaviour that
    does not depend on the SDK: retry policy, backoff and deadline."""
    with FakeGateway("claude", answer=REPLY) as running:
        yield running


def _connection(gateway: FakeGateway, **overrides: Any) -> MaiConnection:
    values: dict[str, Any] = {
        "base_url": gateway.url,
        "endpoint": ENDPOINTS[gateway.family],
        "family": gateway.family,
        "model": DEFAULT_MODELS[gateway.family],
        "app_id": GUID,
    }
    return MaiConnection(**{**values, **overrides})


def _client(gateway: FakeGateway, **options: Any) -> MaiClient:
    settings: dict[str, Any] = {"backoff_seconds": 0.0, "timeout_seconds": 10.0}
    return MaiClient(_connection(gateway), **{**settings, **options})


def _complete(
    client: MaiClient,
    schema: dict[str, Any] | None = None,
    format_name: str = FIELD_EVALUATION_FORMAT,
    *,
    system: str = "SYSTEM",
    user: str = "USER",
) -> ModelReply:
    async def run() -> ModelReply:
        try:
            return await client.complete(
                system=system,
                user=user,
                schema=field_evaluation_schema() if schema is None else schema,
                format_name=format_name,
            )
        finally:
            await client.aclose()

    return asyncio.run(run())


def _failure(client: MaiClient, **options: Any) -> ProviderError:
    with pytest.raises(ProviderError) as raised:
        _complete(client, **options)
    return raised.value


def _recorded_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Make the client's waits instant, recording each requested delay."""
    delays: list[float] = []

    async def record(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("pcn_clone.ai.mai.asyncio.sleep", record)
    return delays


class FixedRandom(random.Random):
    """A jitter source that always draws ``value``."""

    def __init__(self, value: float) -> None:
        super().__init__()
        self.value = value

    def random(self) -> float:
        return self.value


# --- Settings -----------------------------------------------------------------


def _mai(**values: str | None) -> MaiConnection:
    settings: dict[str, Any] = {
        "mai_base_url": "https://gateway.example.invalid/posit-mai/conversationalai/",
        "mai_endpoint": ENDPOINTS["gpt"],
        "connect_content_guid": GUID,
        **values,
    }
    return resolve_mai(AiSettings(**settings))


@pytest.mark.parametrize("family_name", FAMILIES)
def test_family_and_default_model_come_from_the_endpoint(family_name: Family) -> None:
    connection = _mai(mai_endpoint=ENDPOINTS[family_name])
    assert connection.family == family_name
    assert connection.model == DEFAULT_MODELS[family_name]
    assert connection.app_id == GUID
    assert DEFAULT_MODELS == {
        "gpt": "gpt-5.6-luna",
        "gemini": "gemini-3.8-flash",
        "claude": "claude-haiku-5-5",
    }


@pytest.mark.parametrize(
    ("model", "family_name"),
    [
        ("gpt-6-luna", "gpt"),
        ("GPT-5.6-luna", "gpt"),
        ("gemini-3.1-flash-lite", "gemini"),
        ("claude-haiku-5-5", "claude"),
        ("us.anthropic.claude-haiku-5-5", "claude"),
        ("anthropic.claude-haiku-5-5", "claude"),
    ],
)
def test_family_comes_from_the_model(model: str, family_name: Family) -> None:
    connection = _mai(mai_model=model, mai_endpoint="https://mai.example.invalid/x")
    assert connection.family == family_name


def test_an_unknown_model_name_takes_the_endpoint_family() -> None:
    connection = _mai(mai_model="o9-preview", mai_endpoint=ENDPOINTS["gpt"])
    assert (connection.family, connection.model) == ("gpt", "o9-preview")


@pytest.mark.parametrize(
    ("model", "endpoint", "message"),
    [
        ("gpt-6-luna", ENDPOINTS["gemini"], "a GPT model but MAI_ENDPOINT is a Gemini"),
        (
            "claude-haiku-5-5",
            ENDPOINTS["gpt"],
            "a Claude model but MAI_ENDPOINT is a GPT",
        ),
        (
            "gemini-3.8-flash",
            ENDPOINTS["claude"],
            "a Gemini model but MAI_ENDPOINT is a Claude",
        ),
    ],
)
def test_model_and_endpoint_families_must_agree(
    model: str, endpoint: str, message: str
) -> None:
    with pytest.raises(AiConfigurationError, match=f"MAI_MODEL is {message}"):
        _mai(mai_model=model, mai_endpoint=endpoint)


def test_a_family_must_be_identifiable() -> None:
    with pytest.raises(AiConfigurationError, match="MAI_ENDPOINT is not a GPT"):
        _mai(mai_endpoint="https://mai.example.invalid/something/else")


@pytest.mark.parametrize(
    ("missing", "message"),
    [
        ("mai_base_url", "MAI_BASE_URL is not set"),
        ("mai_endpoint", "MAI_ENDPOINT is not set"),
        ("connect_content_guid", "CONNECT_CONTENT_GUID is not set"),
    ],
)
def test_missing_variables_are_named(missing: str, message: str) -> None:
    with pytest.raises(AiConfigurationError, match=message) as raised:
        _mai(**{missing: None})
    assert "PCN_AI_PROVIDER=fake" in str(raised.value)


def test_missing_app_id_says_the_app_must_run_on_connect() -> None:
    with pytest.raises(AiConfigurationError, match="running on Posit Connect"):
        _mai(connect_content_guid=None)


CLAUDE_BASE = "https://h.invalid/maifactory/bedrock/model/"


@pytest.mark.parametrize(
    ("model", "segment", "expected_model", "expected_segment"),
    [
        pytest.param(
            None,
            "us.anthropic.<model>",
            "claude-haiku-5-5",
            "us.anthropic.claude-haiku-5-5",
            id="placeholder-default",
        ),
        pytest.param(
            "claude-sonnet-9",
            "us.anthropic.%3Cmodel%3E",
            "claude-sonnet-9",
            "us.anthropic.claude-sonnet-9",
            id="encoded-placeholder",
        ),
        pytest.param(
            "us.anthropic.claude-sonnet-9",
            "us.anthropic.claude-haiku-5-5",
            "claude-sonnet-9",
            "us.anthropic.claude-sonnet-9",
            id="model-replaces-segment",
        ),
        pytest.param(
            None,
            "us.anthropic.claude-opus-9",
            "claude-opus-9",
            "us.anthropic.claude-opus-9",
            id="endpoint-model-kept",
        ),
    ],
)
def test_claude_model_is_written_into_the_endpoint(
    model: str | None, segment: str, expected_model: str, expected_segment: str
) -> None:
    connection = _mai(mai_model=model, mai_endpoint=f"{CLAUDE_BASE}{segment}/converse")
    assert connection.model == expected_model
    assert connection.endpoint == f"{CLAUDE_BASE}{expected_segment}/converse"


# --- Requests -----------------------------------------------------------------


def test_request_invariants(gateway: FakeGateway) -> None:
    reply = _complete(_client(gateway))
    [request] = gateway.requests
    assert request.method == "POST"
    assert request.path.startswith("/posit-mai/conversationalai/")
    assert request.path.endswith(PATHS[gateway.family])
    assert request.query == {"mai-endpoint": ENDPOINTS[gateway.family]}
    assert request.headers["x-posit-app-id"] == GUID
    assert request.headers["x-source-type"] == "interactive"
    assert request.headers["content-type"].startswith("application/json")
    assert reply == ModelReply(
        data=REPLY,
        model=DEFAULT_MODELS[gateway.family],
        usage=TokenUsage(
            input_tokens=USAGE["input"],
            output_tokens=USAGE["output"],
            reasoning_tokens=None if gateway.family == "claude" else USAGE["reasoning"],
        ),
    )


def test_no_real_credential_is_ever_sent(gateway: FakeGateway) -> None:
    _complete(_client(gateway))
    [request] = gateway.requests
    for name in ("api-key", "ocp-apim-subscription-key", "x-api-key"):
        assert name not in request.headers
    for name, placeholder in PLACEHOLDER_CREDENTIALS.items():
        assert request.headers.get(name, placeholder) == placeholder
    if gateway.family == "claude":
        assert "authorization" not in request.headers
        assert "x-goog-api-key" not in request.headers


def test_request_body(gateway: FakeGateway) -> None:
    schema = field_evaluation_schema()
    _complete(_client(gateway), schema)
    body = gateway.body()
    assert "temperature" not in json.dumps(body)
    assert request_parts(gateway.family, body) == ("SYSTEM", "USER", schema)
    if gateway.family == "gpt":
        assert body["model"] == "gpt-5.6-luna"
        assert body["instructions"] == "SYSTEM"
        assert body["input"] == [
            {"role": "user", "content": [{"type": "input_text", "text": "USER"}]}
        ]
        assert body["text"] == {
            "format": {
                "type": "json_schema",
                "name": FIELD_EVALUATION_FORMAT,
                "schema": schema,
                "strict": True,
            }
        }
        for absent in ("max_output_tokens", "reasoning", "top_p"):
            assert absent not in body
    elif gateway.family == "gemini":
        assert body["model"] == "gemini-3.8-flash"
        assert body["system_instruction"] == "SYSTEM"
        assert body["input"] == "USER"
        assert body["response_format"] == schema
        assert body["response_mime_type"] == "application/json"
        assert "generation_config" not in body
    else:
        assert body == {
            "system": [{"text": "SYSTEM"}],
            "messages": [{"role": "user", "content": [{"text": "USER"}]}],
            "inferenceConfig": {"maxTokens": CLAUDE_DEFAULT_MAX_TOKENS},
            "toolConfig": {
                "tools": [
                    {
                        "toolSpec": {
                            "name": "answer",
                            "description": ANSWER_TOOL_DESCRIPTION,
                            "inputSchema": {"json": schema},
                        }
                    }
                ],
                "toolChoice": {"tool": {"name": "answer"}},
            },
        }


def test_output_cap(gateway: FakeGateway) -> None:
    _complete(_client(gateway, max_output_tokens=500))
    body = gateway.body()
    capped = {
        "gpt": lambda: body["max_output_tokens"],
        "gemini": lambda: body["generation_config"]["max_output_tokens"],
        "claude": lambda: body["inferenceConfig"]["maxTokens"],
    }[gateway.family]()
    assert capped == 500
    assert "temperature" not in json.dumps(body)


@pytest.mark.parametrize(
    ("format_name", "schema"),
    [
        (FIELD_EVALUATION_FORMAT, lambda: field_evaluation_schema()),
        (
            ASSESSMENT_FINDING_FORMAT,
            lambda: assessment_finding_schema(default_fields()),
        ),
        (
            MCA_SCORE_FINDING_FORMAT,
            lambda: mca_score_finding_schema(default_fields(), load_mca().matrix),
        ),
    ],
)
def test_ref_schemas_reach_the_wire_intact(
    gateway: FakeGateway, format_name: str, schema: Any
) -> None:
    built = schema()
    _complete(_client(gateway), built, format_name)
    assert request_parts(gateway.family, gateway.body())[2] == built
    if gateway.family == "gpt":
        assert gateway.body()["text"]["format"]["name"] == format_name


# --- Replies ------------------------------------------------------------------


def test_claude_plain_json_text_is_accepted() -> None:
    fenced = f"```json\n{json.dumps(REPLY)}\n```"
    with FakeGateway("claude") as gateway:
        gateway.queue(
            Reply(body=claude_body(text=fenced, stop="end_turn")),
            Reply(body=claude_body(text=json.dumps(REPLY), stop="end_turn")),
            Reply(body=claude_body(json.dumps(REPLY))),
        )
        for _ in range(3):
            assert _complete(_client(gateway)).data == REPLY


def _family_body(family: Family, case: str) -> dict[str, Any]:
    text = json.dumps(REPLY)
    bodies: dict[str, dict[Family, dict[str, Any]]] = {
        "cut-off": {
            "gpt": gpt_body(
                text[:20], status="incomplete", incomplete_reason="max_output_tokens"
            ),
            "gemini": gemini_body(text[:20], status="incomplete"),
            "claude": claude_body(text=text[:20], stop="max_tokens"),
        },
        "empty": {
            "gpt": gpt_body(""),
            "gemini": gemini_body(""),
            "claude": claude_body(None, text="", stop="end_turn"),
        },
        "blocked": {
            "gpt": gpt_body("", refusal="I can't help with that."),
            "gemini": gemini_body("", status="failed"),
            "claude": claude_body(None, text="", stop="guardrail_intervened"),
        },
        "not-an-object": {
            "gpt": gpt_body("[1, 2]"),
            "gemini": gemini_body("[1, 2]"),
            "claude": claude_body([1, 2]),
        },
        "not-json": {
            "gpt": gpt_body("Sure! Here is the verdict."),
            "gemini": gemini_body("Sure! Here is the verdict."),
            "claude": claude_body(text="Sure! Here is the verdict.", stop="end_turn"),
        },
    }
    return bodies[case][family]


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("cut-off", "PCN_AI_MAX_OUTPUT_TOKENS"),
        ("empty", "no content"),
        ("blocked", ""),
        ("not-an-object", "not a JSON object"),
        ("not-json", "not valid JSON"),
    ],
)
def test_unusable_replies_are_terminal_without_retry(
    gateway: FakeGateway, case: str, message: str
) -> None:
    gateway.queue(Reply(body=_family_body(gateway.family, case)))
    error = _failure(_client(gateway))
    assert error.kind == "terminal"
    assert message in error.message
    assert len(gateway.requests) == 1


def test_usage_is_optional(gateway: FakeGateway) -> None:
    text = json.dumps(REPLY)
    body = {
        "gpt": gpt_body(text, usage=False),
        "gemini": gemini_body(text, usage=False),
        "claude": claude_body(REPLY, usage=False),
    }[gateway.family]
    gateway.queue(Reply(body=body))
    reply = _complete(_client(gateway))
    assert reply.data == REPLY
    assert reply.usage is None


def test_non_json_success_body_is_terminal(gateway: FakeGateway) -> None:
    gateway.queue(Reply(body="<html>maintenance</html>"))
    error = _failure(_client(gateway))
    assert error.kind == "terminal"
    assert len(gateway.requests) == 1


# --- Failures -----------------------------------------------------------------


def _apim(status: int, message: str) -> Reply:
    return Reply(status, {"statusCode": status, "message": message})


TERMINAL_REFUSALS = [
    pytest.param(
        _apim(400, "Missing required header: 'X-Posit-App-Id'"),
        "the app must run on Posit Connect",
        id="400-missing-app-id",
    ),
    pytest.param(
        _apim(400, "Missing required parameter: 'mai-endpoint'"),
        "set MAI_ENDPOINT",
        id="400-missing-endpoint",
    ),
    pytest.param(_apim(401, "Unauthorized"), "send no credentials", id="401"),
    pytest.param(
        _apim(403, "Model not allowed for Posit applications."),
        "MAI_MODEL",
        id="403-model",
    ),
    pytest.param(
        _apim(403, "Invalid Posit application ID."),
        "must run on Posit Connect",
        id="403-app-id",
    ),
    pytest.param(
        _apim(403, "Access denied / Forbidden"),
        "local machines are refused",
        id="403-forbidden",
    ),
    pytest.param(
        _apim(404, "Resource not found"), "including its trailing /", id="404"
    ),
    pytest.param(_apim(413, "Request entity too large"), "too long", id="413"),
    pytest.param(
        Reply(400, {"error": {"message": "Input is too long for requested model."}}),
        "too long",
        id="400-too-long",
    ),
    pytest.param(_apim(422, "Unprocessable"), "HTTP 422", id="422"),
]


@pytest.mark.parametrize(("reply", "fix"), TERMINAL_REFUSALS)
def test_refusals_are_terminal_and_name_the_fix(
    http_gateway: FakeGateway, reply: Reply, fix: str
) -> None:
    http_gateway.queue(reply)
    error = _failure(_client(http_gateway))
    assert error.kind == "terminal"
    assert error.status == reply.status
    assert f"HTTP {reply.status}" in error.message
    assert fix in error.message
    assert len(http_gateway.requests) == 1


@pytest.mark.parametrize("status", [408, 409, 425, 429, 500, 502, 503, 504])
def test_retryable_statuses_use_every_retry(
    http_gateway: FakeGateway, status: int
) -> None:
    http_gateway.queue(*[_apim(status, "Try later")] * 3)
    error = _failure(_client(http_gateway, max_retries=2))
    assert error.kind == "retryable"
    assert error.status == status
    assert len(http_gateway.requests) == 3


@pytest.mark.parametrize(
    ("reply", "kind", "attempts", "text"),
    [
        pytest.param(
            _apim(403, "Model not allowed for Posit applications."),
            "terminal",
            1,
            "Model not allowed",
            id="403",
        ),
        pytest.param(
            _apim(400, "Missing required parameter: 'mai-endpoint'"),
            "terminal",
            1,
            "set MAI_ENDPOINT",
            id="400",
        ),
        pytest.param(_apim(429, "Rate limit"), "retryable", 3, "HTTP 429", id="429"),
        pytest.param(_apim(503, "Unavailable"), "retryable", 3, "HTTP 503", id="503"),
    ],
)
def test_each_sdk_surfaces_the_gateway_status_without_retrying_itself(
    gateway: FakeGateway, reply: Reply, kind: str, attempts: int, text: str
) -> None:
    gateway.queue(*[reply] * 3)
    error = _failure(_client(gateway, max_retries=2))
    assert (error.kind, error.status) == (kind, reply.status)
    assert text in error.message
    assert len(gateway.requests) == attempts


def test_each_sdk_passes_on_retry_after(gateway: FakeGateway) -> None:
    gateway.queue(Reply(429, {"message": "Slow down"}, headers={"Retry-After": "120"}))
    error = _failure(_client(gateway))
    assert error.retry_after == 120.0
    assert len(gateway.requests) == 1


def test_each_client_attempt_is_one_http_request(gateway: FakeGateway) -> None:
    gateway.queue(_apim(503, "Unavailable"))
    error = _failure(_client(gateway, max_retries=0))
    assert error.status == 503
    assert len(gateway.requests) == 1


def test_non_json_error_page_is_classified_by_status(http_gateway: FakeGateway) -> None:
    http_gateway.queue(Reply(502, "<html>Bad http_gateway</html>"))
    error = _failure(_client(http_gateway, max_retries=0))
    assert (error.kind, error.status) == ("retryable", 502)
    assert "Bad http_gateway" in error.message


def test_apim_rate_limit_text_sets_the_wait(
    http_gateway: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    delays = _recorded_sleeps(monkeypatch)
    http_gateway.queue(_apim(429, "Rate limit is exceeded. Try again in 12 seconds."))
    reply = _complete(_client(http_gateway, rng=FixedRandom(0.0)))
    assert reply.data == REPLY
    assert delays == [12.0]


def test_apim_quota_text_ends_the_retries(
    http_gateway: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    delays = _recorded_sleeps(monkeypatch)
    http_gateway.queue(
        _apim(429, "Out of call volume quota. Quota will be replenished in 05:12:00.")
    )
    error = _failure(_client(http_gateway))
    assert error.kind == "retryable"
    assert error.retry_after == 5 * 3600 + 12 * 60
    assert len(http_gateway.requests) == 1
    assert delays == []


def test_apim_quota_on_403_is_terminal(http_gateway: FakeGateway) -> None:
    http_gateway.queue(
        _apim(403, "Out of call volume quota. Quota will be replenished in 00:01:30.")
    )
    error = _failure(_client(http_gateway))
    assert error.kind == "terminal"
    assert error.retry_after == 90.0
    assert "quota" in error.message


def test_retry_after_header_is_honoured(
    http_gateway: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    delays = _recorded_sleeps(monkeypatch)
    http_gateway.queue(
        Reply(429, {"message": "Slow down"}, headers={"Retry-After": "7"}),
        Reply(429, {"message": "Slow down"}, headers={"retry-after-ms": "2500"}),
    )
    reply = _complete(_client(http_gateway, rng=FixedRandom(1.0)))
    assert reply.data == REPLY
    assert delays == [7.0, 2.5]


def test_long_retry_after_ends_the_retries(
    http_gateway: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    delays = _recorded_sleeps(monkeypatch)
    http_gateway.queue(
        Reply(429, {"message": "Slow down"}, headers={"Retry-After": "120"})
    )
    error = _failure(_client(http_gateway))
    assert error.retry_after == 120.0
    assert len(http_gateway.requests) == 1
    assert delays == []


def test_recovers_after_transient_failures(http_gateway: FakeGateway) -> None:
    http_gateway.queue(_apim(503, "Unavailable"), _apim(429, "Slow down"))
    assert _complete(_client(http_gateway)).data == REPLY
    assert len(http_gateway.requests) == 3


@pytest.mark.parametrize("max_retries", [0, 1, 4])
def test_retry_count_is_bounded(http_gateway: FakeGateway, max_retries: int) -> None:
    http_gateway.queue(*[_apim(503, "Unavailable")] * 6)
    _failure(_client(http_gateway, max_retries=max_retries))
    assert len(http_gateway.requests) == max_retries + 1


def test_backoff_doubles_with_jitter(
    http_gateway: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    delays = _recorded_sleeps(monkeypatch)
    http_gateway.queue(*[_apim(500, "Internal error")] * 8)
    _failure(
        _client(http_gateway, max_retries=3, backoff_seconds=1.5, rng=FixedRandom(1.0))
    )
    assert delays == [1.5, 3.0, 6.0]

    delays.clear()
    _failure(
        _client(http_gateway, max_retries=3, backoff_seconds=1.5, rng=FixedRandom(0.0))
    )
    assert delays == [0.75, 1.5, 3.0]


def test_backoff_is_capped(
    http_gateway: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    delays = _recorded_sleeps(monkeypatch)
    http_gateway.queue(*[_apim(500, "Internal error")] * 3)
    _failure(
        _client(
            http_gateway,
            max_retries=2,
            timeout_seconds=600,
            backoff_seconds=40,
            rng=FixedRandom(1.0),
        )
    )
    assert delays == [30.0, 30.0]


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    return port


def test_pre_send_failures_use_every_retry(family: Family) -> None:
    with FakeGateway(family) as gateway:
        # 0.0.0.0 fails at once: unroutable on Windows, a closed port elsewhere.
        url = f"http://0.0.0.0:{_closed_port()}/posit-mai/conversationalai/"
        client = MaiClient(
            _connection(gateway, base_url=url),
            backoff_seconds=0.0,
            timeout_seconds=10.0,
            max_retries=2,
        )
        attempts: list[int] = []
        original = client._send

        async def counted(*args: Any) -> Any:
            attempts.append(1)
            return await original(*args)

        client._send = counted  # type: ignore[method-assign]
        error = _failure(client)
    assert error.kind == "retryable"
    assert not error.after_send
    assert "could not be made" in error.message
    assert len(attempts) == 3


def test_dropped_connection_retries_at_most_once(gateway: FakeGateway) -> None:
    gateway.queue(*[Reply(drop=True)] * 5)
    error = _failure(_client(gateway, max_retries=4))
    assert error.kind == "retryable"
    assert error.after_send
    assert len(gateway.requests) == 2


def _warm_failure(client: MaiClient, gateway: FakeGateway) -> ProviderError:
    """Complete one call, then fail one in the same event loop, so the
    timed call does not include building the SDK client. The first reply
    queued must be a success."""

    async def run() -> ProviderError:
        try:
            await client.complete(
                system="S",
                user="U",
                schema=field_evaluation_schema(),
                format_name=FIELD_EVALUATION_FORMAT,
            )
            with pytest.raises(ProviderError) as raised:
                await client.complete(
                    system="S",
                    user="U",
                    schema=field_evaluation_schema(),
                    format_name=FIELD_EVALUATION_FORMAT,
                )
            return raised.value
        finally:
            await client.aclose()

    return asyncio.run(run())


def test_attempt_timeout_retries_at_most_once(gateway: FakeGateway) -> None:
    gateway.queue(Reply(), *[Reply(delay=3.0)] * 3)
    client = _client(gateway, timeout_seconds=0.5, max_retries=2)
    error = _warm_failure(client, gateway)
    assert error.kind == "retryable"
    assert error.after_send
    assert error.message == "No reply within 0.5 s."
    assert len(gateway.requests) == 1 + 2


def test_overall_deadline(http_gateway: FakeGateway) -> None:
    http_gateway.queue(
        Reply(),
        Reply(429, {"message": "Slow down"}, headers={"Retry-After": "0.75"}),
        Reply(delay=3.0),
    )
    client = _client(http_gateway, timeout_seconds=0.5, max_retries=1)
    error = _warm_failure(client, http_gateway)
    assert error.kind == "retryable"
    assert error.message == "No reply within the overall deadline of 1 s."
    assert len(http_gateway.requests) == 1 + 2


def test_deadline_is_capped(http_gateway: FakeGateway) -> None:
    client = _client(http_gateway, timeout_seconds=600, max_retries=5)
    assert client.deadline_seconds == DEADLINE_CAP_SECONDS == 1800


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (400, "terminal"),
        (401, "terminal"),
        (403, "terminal"),
        (404, "terminal"),
        (408, "retryable"),
        (409, "retryable"),
        (413, "terminal"),
        (422, "terminal"),
        (425, "retryable"),
        (429, "retryable"),
        (500, "retryable"),
        (503, "retryable"),
        (529, "retryable"),
    ],
)
def test_classify_status(status: int, kind: str) -> None:
    assert classify_status(status) == kind


def test_retry_after_parsing() -> None:
    soon = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    past = format_datetime(datetime.now(UTC) - timedelta(seconds=30), usegmt=True)
    assert 28 <= (retry_after_seconds({"retry-after": soon}) or 0) <= 30
    assert retry_after_seconds({"retry-after": past}) == 0.0
    assert retry_after_seconds({"retry-after": "2.5"}) == 2.5
    assert retry_after_seconds({"retry-after-ms": "1500", "retry-after": "9"}) == 1.5
    assert retry_after_seconds({"retry-after": "soon"}) is None
    assert retry_after_seconds({}) is None
    assert retry_after_seconds({}, "Try again in 12 seconds.") == 12.0
    assert retry_after_seconds({}, "Quota will be replenished in 01:00:05.") == 3605
    assert retry_after_seconds({"retry-after": "3"}, "Try again in 12 seconds.") == 3
    assert retry_after_seconds({}, "Rate limited") is None


# --- Schema compatibility ladder ------------------------------------------------

SCHEMA_REJECTION = Reply(
    400, {"error": {"message": "Invalid schema: keyword 'const' is not supported."}}
)


def _mca_schema() -> dict[str, Any]:
    return mca_score_finding_schema(default_fields(), load_mca().matrix)


def _walk(node: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def test_schema_levels() -> None:
    schema = _mca_schema()
    original = copy.deepcopy(schema)
    assert schema_at_level(schema, 0) == schema

    portable = schema_at_level(schema, 1)
    keys = {key for key, _ in _walk(portable)}
    assert not keys & {"$ref", "$schema", "definitions", "const"}
    assert "minLength" in keys
    assert {"maxItems", "minItems"} <= keys
    basis = portable["properties"]["basis"]["anyOf"]
    assert basis[0]["properties"]["kind"] == {"type": "string", "enum": ["documented"]}
    assert basis[0]["properties"]["evidence"]["items"]["anyOf"]

    minimal = schema_at_level(schema, 2)
    keys = {key for key, _ in _walk(minimal)}
    assert not keys & {"minLength", "maxLength", "minItems", "maxItems", "$ref"}
    assert schema == original


def test_a_property_named_const_is_kept() -> None:
    schema = {
        "type": "object",
        "properties": {"const": {"type": "string", "const": "x"}},
    }
    assert schema_at_level(schema, 1) == {
        "type": "object",
        "properties": {"const": {"type": "string", "enum": ["x"]}},
    }


def test_schema_rejection_climbs_the_ladder_and_remembers(
    gateway: FakeGateway, caplog: pytest.LogCaptureFixture
) -> None:
    schema = _mca_schema()
    original = copy.deepcopy(schema)
    client = _client(gateway)
    gateway.queue(SCHEMA_REJECTION)
    with caplog.at_level(logging.WARNING, logger="pcn_clone.ai.mai"):
        _complete(client, schema, MCA_SCORE_FINDING_FORMAT)
    assert client.schema_level == 1
    assert "schema level 1" in caplog.text
    sent = [request_parts(gateway.family, r.body)[2] for r in gateway.requests]
    assert sent == [schema, schema_at_level(schema, 1)]

    _complete(client, schema, MCA_SCORE_FINDING_FORMAT)
    assert request_parts(gateway.family, gateway.body(2))[2] == schema_at_level(
        schema, 1
    )

    gateway.queue(SCHEMA_REJECTION)
    _complete(client, schema, MCA_SCORE_FINDING_FORMAT)
    assert client.schema_level == 2
    assert request_parts(gateway.family, gateway.body(4))[2] == schema_at_level(
        schema, 2
    )
    assert len(gateway.requests) == 5
    assert schema == original


def test_schema_rejection_stops_at_the_last_level(http_gateway: FakeGateway) -> None:
    http_gateway.queue(*[SCHEMA_REJECTION] * 4)
    client = _client(http_gateway, max_retries=2)
    error = _failure(client)
    assert error.kind == "terminal"
    assert error.status == 400
    assert client.schema_level == 2
    assert len(http_gateway.requests) == 3


def test_fixture_schemas_reach_the_wire_at_level_zero(gateway: FakeGateway) -> None:
    fixtures = load_fixture("prompts/schemas.json")
    for key, format_name in fixtures["formatNames"].items():
        schema = fixtures[key]
        _complete(_client(gateway), schema, format_name)
        assert request_parts(gateway.family, gateway.requests[-1].body)[2] == schema


# --- Connection reuse and cancellation --------------------------------------------


def _count_builds(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    built: list[Any] = []
    original = MaiClient._build

    def build(self: MaiClient) -> Any:
        sdk = original(self)
        built.append(sdk)
        return sdk

    monkeypatch.setattr(MaiClient, "_build", build)
    return built


def test_one_connection_pool_is_reused(
    gateway: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = _count_builds(monkeypatch)
    client = _client(gateway)

    async def session() -> None:
        for _ in range(3):
            await client.complete(
                system="S",
                user="U",
                schema=field_evaluation_schema(),
                format_name=FIELD_EVALUATION_FORMAT,
            )
        await client.aclose()

    asyncio.run(session())
    assert len(gateway.requests) == 3
    assert len(built) == 1
    assert client._sdk is None

    asyncio.run(session())
    assert len(built) == 2


def test_a_new_event_loop_gets_a_new_pool(
    gateway: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = _count_builds(monkeypatch)
    client = _client(gateway)

    async def call() -> ModelReply:
        return await client.complete(
            system="S",
            user="U",
            schema=field_evaluation_schema(),
            format_name=FIELD_EVALUATION_FORMAT,
        )

    assert asyncio.run(call()).data == REPLY
    assert asyncio.run(call()).data == REPLY
    assert len(built) == 2
    asyncio.run(client.aclose())


def test_cancellation_is_not_retried(gateway: FakeGateway) -> None:
    gateway.queue(Reply(delay=3.0))

    async def scenario() -> None:
        client = _client(gateway, max_retries=3)
        task = asyncio.create_task(
            client.complete(
                system="S",
                user="U",
                schema=field_evaluation_schema(),
                format_name=FIELD_EVALUATION_FORMAT,
            )
        )
        while not gateway.requests:
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await client.aclose()

    asyncio.run(scenario())
    assert len(gateway.requests) == 1


# --- Privacy ------------------------------------------------------------------

PROPOSAL = "CONFIDENTIAL-PROPOSAL-7f3a: build a toll bridge over the Vardar"


@pytest.mark.parametrize(
    "reply",
    [
        _apim(400, "Bad request"),
        Reply(drop=True),
    ],
    ids=["400", "dropped"],
)
def test_prompts_never_reach_errors_or_logs(
    gateway: FakeGateway, reply: Reply, caplog: pytest.LogCaptureFixture
) -> None:
    gateway.queue(*[reply] * 3)
    client = _client(gateway, max_retries=1)
    with caplog.at_level(logging.INFO), caplog.at_level(logging.DEBUG, "pcn_clone"):
        error = _failure(client, system=f"Assess {PROPOSAL}", user=PROPOSAL)
        gateway.queue(*[reply] * 3)
        evaluated = asyncio.run(
            evaluate_field(
                "investment_identification", "project_title", PROPOSAL, client=client
            )
        )
        asyncio.run(client.aclose())
    for text in (
        error.message,
        str(error),
        repr(error.__cause__),
        repr(client),
        json.dumps(evaluated.to_json()),
        caplog.text,
    ):
        assert "CONFIDENTIAL-PROPOSAL" not in text
        assert "build a toll bridge" not in text
