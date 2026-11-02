"""The OpenRouter client shapes requests through the SDK, classifies
failures, bounds its retries and deadline, reuses one connection pool and
keeps the API key out of errors and logs. The SDK's HTTP layer is a mock
transport."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import httpx
import pytest
from openrouter import OpenRouter

from pcn_clone.ai import evaluate_field
from pcn_clone.ai.provider import (
    DEADLINE_CAP_SECONDS,
    ModelReply,
    OpenRouterClient,
    ProviderError,
    TokenUsage,
    classify_status,
    retry_after_seconds,
)
from pcn_clone.ai.schemas import (
    ASSESSMENT_FINDING_FORMAT,
    FIELD_EVALUATION_FORMAT,
    assessment_finding_schema,
    field_evaluation_schema,
)
from tests.ai.support import default_fields

REPLY = {"verdict": "pass", "reasoning": "Meets the rubric.", "suggestions": []}


def _completion(content: Any = None, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "gen-1",
        "created": 1_760_000_000,
        "model": "openai/gpt-5.6-luna-20260901",
        "object": "chat.completion",
        "system_fingerprint": None,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(REPLY) if content is None else content,
                },
            }
        ],
        "usage": {
            "prompt_tokens": 1200,
            "completion_tokens": 340,
            "total_tokens": 1540,
            "completion_tokens_details": {"reasoning_tokens": 256},
        },
    }
    body.update(overrides)
    return body


def _error(status: int, message: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": status, "message": message}})


Handler = Callable[[httpx.Request], Any]
"""A mock endpoint: returns an ``httpx.Response`` or an awaitable of one."""


class Server:
    """A mock OpenRouter endpoint replying from a queue of handlers (the
    last one repeats)."""

    def __init__(self, *responses: Handler) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> Any:
        self.requests.append(request)
        handler = self.responses[min(len(self.requests), len(self.responses)) - 1]
        return handler(request)

    def body(self, index: int = 0) -> dict[str, Any]:
        parsed: dict[str, Any] = json.loads(self.requests[index].content)
        return parsed


class FixedRandom(random.Random):
    """A jitter source that always draws ``value``."""

    def __init__(self, value: float) -> None:
        super().__init__()
        self.value = value

    def random(self) -> float:
        return self.value


class CountingTransport(httpx.MockTransport):
    """A mock transport that counts how often it is closed."""

    closed = 0

    async def aclose(self) -> None:
        self.closed += 1


def _client(server: Server, **options: Any) -> OpenRouterClient:
    settings: dict[str, Any] = {
        "api_key": "sk-test",
        "backoff_seconds": 0.0,
        "transport": httpx.MockTransport(server),
    }
    return OpenRouterClient(**{**settings, **options})


def _recorded_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Make the client's waits instant, recording each requested delay."""
    delays: list[float] = []

    async def record(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("pcn_clone.ai.provider.asyncio.sleep", record)
    return delays


def _complete(
    client: OpenRouterClient,
    schema: dict[str, Any] | None = None,
    format_name: str = FIELD_EVALUATION_FORMAT,
) -> ModelReply:
    return asyncio.run(
        client.complete(
            system="SYSTEM",
            user="USER",
            schema=field_evaluation_schema() if schema is None else schema,
            format_name=format_name,
        )
    )


def _ok(
    body: dict[str, Any] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _: httpx.Response(200, json=_completion() if body is None else body)


def test_request_shape() -> None:
    server = Server(_ok())
    reply = _complete(_client(server, model="openai/gpt-5.6-luna", timeout_seconds=42))

    [request] = server.requests
    assert request.method == "POST"
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-test"
    assert request.extensions["timeout"] == {
        "connect": 42.0,
        "read": 42.0,
        "write": 42.0,
        "pool": 42.0,
    }
    assert server.body() == {
        "model": "openai/gpt-5.6-luna",
        "messages": [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "USER"},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": FIELD_EVALUATION_FORMAT,
                "strict": True,
                "schema": field_evaluation_schema(),
            },
        },
        "provider": {"require_parameters": True},
        "stream": False,
    }
    for absent in ("temperature", "max_tokens", "max_completion_tokens", "reasoning"):
        assert absent not in server.body()
    assert reply == ModelReply(
        data=REPLY,
        model="openai/gpt-5.6-luna-20260901",
        usage=TokenUsage(input_tokens=1200, output_tokens=340, reasoning_tokens=256),
    )


def test_provider_order_and_ref_schema_pass_through() -> None:
    server = Server(_ok())
    schema = assessment_finding_schema(default_fields())
    _complete(
        _client(server, provider_order=("openai", "azure")),
        schema,
        ASSESSMENT_FINDING_FORMAT,
    )
    body = server.body()
    assert body["provider"] == {
        "require_parameters": True,
        "order": ["openai", "azure"],
    }
    assert body["response_format"]["json_schema"]["schema"] == schema
    assert body["response_format"]["json_schema"]["name"] == ASSESSMENT_FINDING_FORMAT


def test_usage_is_optional() -> None:
    body = _completion()
    del body["usage"]
    assert _complete(_client(Server(_ok(body)))).usage is None


def test_content_parts_are_joined() -> None:
    text = json.dumps(REPLY)
    parts = [{"type": "text", "text": text[:10]}, {"type": "text", "text": text[10:]}]
    assert _complete(_client(Server(_ok(_completion(parts))))).data == REPLY


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (400, "terminal"),
        (401, "terminal"),
        (402, "terminal"),
        (404, "terminal"),
        (408, "retryable"),
        (409, "retryable"),
        (422, "terminal"),
        (429, "retryable"),
        (500, "retryable"),
        (502, "retryable"),
        (503, "retryable"),
        (524, "retryable"),
        (529, "retryable"),
    ],
)
def test_classify_status(status: int, kind: str) -> None:
    assert classify_status(status) == kind


def _failure(server: Server, **options: Any) -> tuple[ProviderError, int]:
    with pytest.raises(ProviderError) as raised:
        _complete(_client(server, **options))
    return raised.value, len(server.requests)


def test_rate_limit_is_retried_then_retryable() -> None:
    error, attempts = _failure(Server(lambda _: _error(429, "Rate limit exceeded")))
    assert error.kind == "retryable"
    assert error.status == 429
    assert "Rate limit exceeded" in error.message
    assert attempts == 3


def test_server_error_is_retried_then_retryable() -> None:
    error, attempts = _failure(
        Server(lambda _: _error(500, "Internal error")), max_retries=1
    )
    assert error.kind == "retryable"
    assert error.status == 500
    assert attempts == 2


def test_non_json_error_page_is_classified_by_status() -> None:
    page = httpx.Response(502, text="<html>Bad gateway</html>")
    error, attempts = _failure(Server(lambda _: page), max_retries=0)
    assert error.kind == "retryable"
    assert error.status == 502
    assert attempts == 1


def test_unauthorized_is_terminal_without_retry() -> None:
    error, attempts = _failure(Server(lambda _: _error(401, "No auth credentials")))
    assert error.kind == "terminal"
    assert error.status == 401
    assert attempts == 1


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout],
)
def test_pre_send_failures_use_every_retry(failure: type[httpx.TransportError]) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise failure("unreachable", request=request)

    error, attempts = _failure(Server(fail), max_retries=3)
    assert error.kind == "retryable"
    assert not error.after_send
    assert attempts == 4


@pytest.mark.parametrize(
    "failure",
    [httpx.ReadTimeout, httpx.WriteTimeout, httpx.ReadError, httpx.RemoteProtocolError],
)
def test_after_send_failures_retry_at_most_once(
    failure: type[httpx.TransportError],
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise failure("lost", request=request)

    error, attempts = _failure(Server(fail), max_retries=4)
    assert error.kind == "retryable"
    assert error.after_send
    assert attempts == 2


def test_attempt_timeout_retries_at_most_once() -> None:
    async def stall(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, json=_completion())

    server = Server(stall)
    error, attempts = _failure(server, timeout_seconds=0.05, max_retries=2)
    assert error.kind == "retryable"
    assert error.message == "No reply within 0.05 s."
    assert attempts == 2


def test_overall_deadline() -> None:
    async def slow_failure(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.15)
        return _error(503, "Unavailable")

    async def stall(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, json=_completion())

    server = Server(slow_failure, stall)
    error, attempts = _failure(server, timeout_seconds=0.1, max_retries=1)
    assert error.kind == "retryable"
    assert error.message == "No reply within the overall deadline of 0.2 s."
    assert attempts == 2


def test_deadline_is_capped() -> None:
    client = OpenRouterClient(api_key="sk", timeout_seconds=600, max_retries=5)
    assert client.deadline_seconds == DEADLINE_CAP_SECONDS == 1800


def test_non_json_content_is_terminal_without_retry() -> None:
    error, attempts = _failure(Server(_ok(_completion("Sure! Here is the verdict."))))
    assert error.kind == "terminal"
    assert error.message == "The model reply is not valid JSON."
    assert attempts == 1


def test_non_object_json_is_terminal() -> None:
    error, _ = _failure(Server(_ok(_completion("[1, 2]"))))
    assert error.kind == "terminal"
    assert error.message == "The model reply is not a JSON object."


def test_non_json_success_body_is_terminal() -> None:
    page = httpx.Response(200, text="<html>maintenance</html>")
    error, attempts = _failure(Server(lambda _: page))
    assert error.kind == "terminal"
    assert attempts == 1


def test_refusal_is_terminal() -> None:
    body = _completion()
    body["choices"][0]["message"] = {
        "role": "assistant",
        "content": None,
        "refusal": "I can't help with that.",
    }
    error, _ = _failure(Server(_ok(body)))
    assert error.kind == "terminal"
    assert "refused" in error.message


def test_no_choices_is_terminal() -> None:
    error, _ = _failure(Server(_ok(_completion(choices=[]))))
    assert error.kind == "terminal"


def test_recovers_after_transient_failures() -> None:
    server = Server(
        lambda _: _error(503, "Unavailable"),
        lambda _: _error(429, "Slow down"),
        _ok(),
    )
    reply = _complete(_client(server))
    assert reply.data == REPLY
    assert len(server.requests) == 3


@pytest.mark.parametrize("max_retries", [0, 1, 4])
def test_retry_count_is_bounded(max_retries: int) -> None:
    server = Server(lambda _: _error(503, "Unavailable"))
    _, attempts = _failure(server, max_retries=max_retries)
    assert attempts == max_retries + 1


def test_backoff_doubles_with_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    delays = _recorded_sleeps(monkeypatch)
    server = Server(lambda _: _error(500, "Internal error"))
    _failure(server, max_retries=3, backoff_seconds=1.5, rng=FixedRandom(1.0))
    assert delays == [1.5, 3.0, 6.0]

    delays.clear()
    _failure(Server(server), max_retries=3, backoff_seconds=1.5, rng=FixedRandom(0.0))
    assert delays == [0.75, 1.5, 3.0]


def test_backoff_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    delays = _recorded_sleeps(monkeypatch)
    server = Server(lambda _: _error(500, "Internal error"))
    _failure(server, max_retries=2, backoff_seconds=40, rng=FixedRandom(1.0))
    assert delays == [30.0, 30.0]


def _rate_limited(retry_after: str) -> Handler:
    return lambda _: httpx.Response(
        429,
        json={"error": {"code": 429, "message": "Slow down"}},
        headers={"Retry-After": retry_after},
    )


def test_retry_after_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    delays = _recorded_sleeps(monkeypatch)
    server = Server(_rate_limited("7"), _ok())
    reply = _complete(_client(server, rng=FixedRandom(1.0)))
    assert reply.data == REPLY
    assert delays == [7.0]


def test_long_retry_after_ends_the_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    delays = _recorded_sleeps(monkeypatch)
    error, attempts = _failure(Server(_rate_limited("120")))
    assert error.retry_after == 120.0
    assert attempts == 1
    assert delays == []


def test_retry_after_parsing() -> None:
    soon = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    past = format_datetime(datetime.now(UTC) - timedelta(seconds=30), usegmt=True)
    assert 28 <= (retry_after_seconds({"retry-after": soon}) or 0) <= 30
    assert retry_after_seconds({"retry-after": past}) == 0.0
    assert retry_after_seconds({"retry-after": "2.5"}) == 2.5
    assert retry_after_seconds({"retry-after": "soon"}) is None
    assert retry_after_seconds({}) is None


# --- Connection reuse and cancellation ----------------------------------------


def _count_sdk_builds(monkeypatch: pytest.MonkeyPatch) -> list[OpenRouter]:
    """Record every SDK instance the client builds."""
    built: list[OpenRouter] = []

    class CountingOpenRouter(OpenRouter):
        def __init__(self, **options: Any) -> None:
            super().__init__(**options)
            built.append(self)

    monkeypatch.setattr("pcn_clone.ai.provider.OpenRouter", CountingOpenRouter)
    return built


def test_one_connection_pool_is_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    built = _count_sdk_builds(monkeypatch)
    server = Server(_ok())
    transport = CountingTransport(server)
    client = _client(server, transport=transport)

    async def session() -> None:
        closed = transport.closed
        for _ in range(3):
            await client.complete(
                system="S", user="U", schema={}, format_name=FIELD_EVALUATION_FORMAT
            )
        assert transport.closed == closed
        await client.aclose()
        assert transport.closed == closed + 1

    asyncio.run(session())
    assert len(server.requests) == 3
    assert len(built) == 1

    asyncio.run(session())
    assert len(built) == 2


def test_a_new_event_loop_gets_a_new_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    built = _count_sdk_builds(monkeypatch)
    client = _client(Server(_ok()))
    assert _complete(client).data == REPLY
    assert _complete(client).data == REPLY
    assert len(built) == 2


def test_cancellation_is_not_retried() -> None:
    async def scenario() -> int:
        started = asyncio.Event()

        async def stall(request: httpx.Request) -> httpx.Response:
            started.set()
            await asyncio.sleep(5)
            return httpx.Response(200, json=_completion())

        server = Server(stall)
        client = _client(server, max_retries=3)
        task = asyncio.create_task(
            client.complete(
                system="S", user="U", schema={}, format_name=FIELD_EVALUATION_FORMAT
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await client.aclose()
        return len(server.requests)

    assert asyncio.run(scenario()) == 1


# --- Secrets ---------------------------------------------------------------------

SECRET = "sk-or-v1-0123456789abcdef"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            401, json={"error": {"code": 401, "message": f"Bad key {SECRET}"}}
        ),
        httpx.Response(401, text=f"Unauthorized: {SECRET}"),
    ],
    ids=["json-body", "text-body"],
)
def test_api_key_never_leaks(
    response: httpx.Response, caplog: pytest.LogCaptureFixture
) -> None:
    server = Server(lambda _: response)
    client = _client(server, api_key=SECRET)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ProviderError) as raised:
            _complete(client)
        evaluated = asyncio.run(
            evaluate_field(
                "investment_identification", "project_title", "A road", client=client
            )
        )
    error = raised.value
    assert error.kind == "terminal"
    assert "[redacted]" in error.message
    for text in (
        error.message,
        str(error),
        repr(error.__cause__),
        repr(client),
        json.dumps(evaluated.to_json()),
        caplog.text,
    ):
        assert SECRET not in text
