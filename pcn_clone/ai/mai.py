"""The Posit mAI Gateway client: GPT, Gemini and Claude models behind one
:class:`~pcn_clone.ai.provider.ModelClient`.

Apps on Posit Connect reach mAI through the gateway at ``MAI_BASE_URL``.
Every request carries the mAI endpoint as the ``mai-endpoint`` query
parameter and the app id (``CONNECT_CONTENT_GUID``) as the
``X-Posit-App-Id`` header; the gateway authenticates the app, so no key or
token is sent. The model family picks the wire format:

- GPT: the OpenAI Responses API through the ``openai`` SDK, with a strict
  ``json_schema`` text format.
- Gemini: the Interactions API through the ``google-genai`` SDK, with the
  schema as ``response_format``.
- Claude: Bedrock Converse over plain HTTP, with the schema as the input of
  one forced ``answer`` tool call.

The SDKs are imported on first use, so a process running the fake
provider never loads them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

import httpx

from pcn_clone.ai.config import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    MaiConnection,
)
from pcn_clone.ai.provider import (
    BACKOFF_CAP_SECONDS,
    DEADLINE_CAP_SECONDS,
    MAX_AFTER_SEND_RETRIES,
    RETRY_AFTER_CAP_SECONDS,
    ModelReply,
    ProviderError,
    TokenUsage,
    classify_status,
    parse_reply_content,
    retry_after_seconds,
)

if TYPE_CHECKING:
    from google.genai import Client as GenaiClient
    from openai import AsyncOpenAI
    from openai.types.responses import Response

logger = logging.getLogger(__name__)

PLACEHOLDER_API_KEY = "not-used"
"""What the SDKs are given as their API key: they require one, and the
gateway ignores it."""

SOURCE_TYPE = "interactive"
CLAUDE_DEFAULT_MAX_TOKENS = 8192
"""Converse needs an explicit output limit; used when
``PCN_AI_MAX_OUTPUT_TOKENS`` is unset."""

ANSWER_TOOL = "answer"
ANSWER_TOOL_DESCRIPTION = "Return the answer in exactly this JSON shape."
MAX_SCHEMA_LEVEL = 2
_DETAIL_LIMIT = 300


# --- Schema compatibility ladder -----------------------------------------------

_LENGTH_KEYWORDS = frozenset({"minLength", "maxLength", "minItems", "maxItems"})
_SCHEMA_MAPS = frozenset({"properties", "definitions", "$defs", "patternProperties"})
_DEFINITION_REF = "#/definitions/"


def schema_at_level(schema: Mapping[str, Any], level: int) -> dict[str, Any]:
    """The response schema as sent at a compatibility ``level``.

    Level 0 is ``schema`` itself. Level 1 is a portable copy: ``definitions``
    references inlined, the ``$schema`` and ``definitions`` keys dropped and
    ``const`` written as a one-value ``enum``. Level 2 also drops the length
    and item-count bounds, which the reply's validation still enforces.
    ``schema`` is never changed.
    """
    if level <= 0:
        return dict(schema)
    definitions: Mapping[str, Any] = schema.get("definitions") or {}

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(item) for item in node]
        if not isinstance(node, Mapping):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(_DEFINITION_REF):
            target = walk(definitions[ref.removeprefix(_DEFINITION_REF)])
            siblings = walk({k: v for k, v in node.items() if k != "$ref"})
            return {**target, **siblings}
        copy: dict[str, Any] = {}
        for key, value in node.items():
            if key == "const":
                copy["enum"] = [value]
            elif level >= 2 and key in _LENGTH_KEYWORDS:
                continue
            elif key in _SCHEMA_MAPS and isinstance(value, Mapping):
                copy[key] = {name: walk(sub) for name, sub in value.items()}
            else:
                copy[key] = walk(value)
        return copy

    root = {k: v for k, v in schema.items() if k not in ("$schema", "definitions")}
    return cast(dict[str, Any], walk(root))


_SCHEMA_REJECTED = re.compile(
    r"schema|response_format|not permitted|not supported|unsupported"
    r"|invalid\W+(?:\w+\W+){0,3}?(?:keyword|property)",
    re.IGNORECASE,
)


class _SchemaRejected(ProviderError):
    """An HTTP 400 that reads like the provider refusing the response
    schema; a simpler schema may be accepted."""


# --- Failures ------------------------------------------------------------------


def _collapse(text: str) -> str:
    """``text`` on one line and at most a few hundred characters long."""
    collapsed = " ".join(text.split())
    if len(collapsed) > _DETAIL_LIMIT:
        return collapsed[: _DETAIL_LIMIT - 1] + "…"
    return collapsed


def _gateway_detail(body: str) -> str:
    """The error text of a gateway reply body: the ``message`` of a JSON
    error object when there is one, else the body itself."""
    try:
        parsed: Any = json.loads(body)
    except ValueError:
        return _collapse(body)
    for _ in range(3):
        if isinstance(parsed, Mapping):
            inner = next(
                (
                    parsed[key]
                    for key in ("error", "message", "Message", "detail")
                    if parsed.get(key)
                ),
                None,
            )
            if inner is None:
                break
            parsed = inner
        if isinstance(parsed, str):
            return _collapse(parsed)
    return _collapse(json.dumps(parsed) if not isinstance(parsed, str) else parsed)


def _fix_for(status: int, detail: str) -> str | None:
    """What to do about a gateway refusal, after the guide's error table."""
    text = detail.lower()
    if status == 400 and "x-posit-app-id" in text:
        return (
            "send X-Posit-App-Id from CONNECT_CONTENT_GUID: the app must run on "
            "Posit Connect"
        )
    if status == 400 and "mai-endpoint" in text:
        return "set MAI_ENDPOINT"
    if status == 401:
        return (
            "the gateway authenticates the app itself: send no credentials and "
            "attach no Integration"
        )
    if status == 403 and "model not allowed" in text:
        return "set MAI_MODEL to a model the gateway allows"
    if status == 403 and "quota" in text:
        return "the app's call quota is used up until it is replenished"
    if status == 403:
        return (
            "the app must run on Posit Connect, which sets CONNECT_CONTENT_GUID; "
            "local machines are refused"
        )
    if status == 404:
        return "check MAI_BASE_URL, including its trailing /, and MAI_ENDPOINT"
    if status == 413 or (status == 400 and "too long" in text):
        return "the input is too long for the model"
    return None


def _http_failure(status: int, body: str, headers: Mapping[str, str]) -> ProviderError:
    """The :class:`ProviderError` for a gateway reply with an error status."""
    detail = _gateway_detail(body)
    fix = _fix_for(status, detail)
    message = f"The mAI Gateway returned HTTP {status}: {detail}"
    if fix is not None:
        message = f"{message} ({fix})"
    error_type = (
        _SchemaRejected
        if status == 400 and fix is None and _SCHEMA_REJECTED.search(detail)
        else ProviderError
    )
    return error_type(
        classify_status(status),
        message,
        status=status,
        retry_after=retry_after_seconds(headers, detail),
    )


_PRE_SEND_FAILURES = frozenset({"ConnectError", "ConnectTimeout", "PoolTimeout"})
_TIMEOUTS = frozenset({"TimeoutException", "APITimeoutError", "TimeoutError"})
_CONNECTION_FAILURES = frozenset(
    {"TransportError", "APIConnectionError", "NoResponseError"}
)


def _failure_names(error: BaseException) -> set[str]:
    """The class names along ``error``'s cause chain. The SDKs wrap the
    errors of their HTTP libraries (``httpx`` or its fork ``httpx2``), so
    failures are told apart by class name rather than by class."""
    names: set[str] = set()
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        names.update(cls.__name__ for cls in type(current).__mro__)
        current = current.__cause__ or current.__context__
    return names


def _status_of(error: BaseException) -> int | None:
    for attribute in ("status_code", "code"):
        value = getattr(error, attribute, None)
        if isinstance(value, int) and 400 <= value <= 599:
            return value
    return None


def _response_parts(error: BaseException) -> tuple[str, Mapping[str, str]]:
    """The body text and headers of the HTTP reply an SDK error carries."""
    response = getattr(error, "response", None)
    headers: Mapping[str, str] = {}
    body: str | None = None
    if response is not None:
        headers = getattr(response, "headers", None) or {}
        try:
            body = response.text
        except Exception:
            body = None
    if body is None:
        raw = getattr(error, "body", None)
        body = raw if isinstance(raw, str) else json.dumps(raw) if raw else ""
    return body, headers


def _sdk_failure(error: Exception, timeout_seconds: float) -> ProviderError:
    """The :class:`ProviderError` for an exception an SDK or HTTP call
    raised. Only class names and gateway error texts reach the message:
    never the request, its URL or its body."""
    status = _status_of(error)
    if status is not None:
        body, headers = _response_parts(error)
        return _http_failure(status, body, headers)
    names = _failure_names(error)
    if pre_send := sorted(names & _PRE_SEND_FAILURES):
        return ProviderError(
            "retryable", f"The connection could not be made ({pre_send[0]})."
        )
    if names & _TIMEOUTS:
        return ProviderError(
            "retryable", f"No reply within {timeout_seconds:g} s.", after_send=True
        )
    if names & _CONNECTION_FAILURES:
        return ProviderError(
            "retryable",
            f"The connection failed ({type(error).__name__}).",
            after_send=True,
        )
    return ProviderError(
        "terminal", f"The request could not be made ({type(error).__name__})."
    )


def _cut_off() -> ProviderError:
    return ProviderError(
        "terminal",
        "The model reply was cut off at its output limit; raise "
        "PCN_AI_MAX_OUTPUT_TOKENS.",
    )


def _no_content() -> ProviderError:
    return ProviderError("terminal", "The model returned no content.")


# --- Replies -------------------------------------------------------------------


def _gpt_reply(response: Response) -> tuple[dict[str, Any], TokenUsage | None]:
    if response.status == "incomplete":
        details = response.incomplete_details
        reason = details.reason if details is not None else None
        if reason == "max_output_tokens":
            raise _cut_off()
        raise ProviderError(
            "terminal", f"The model reply is incomplete ({reason or 'no reason'})."
        )
    if response.status == "failed":
        raise ProviderError("terminal", "The model call failed.")
    for item in response.output:
        if item.type == "message" and any(
            part.type == "refusal" for part in item.content
        ):
            raise ProviderError("terminal", "The model refused to answer.")
    text = response.output_text
    if not text.strip():
        raise _no_content()
    usage = response.usage
    reply_usage = (
        TokenUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            reasoning_tokens=usage.output_tokens_details.reasoning_tokens,
        )
        if usage is not None
        else None
    )
    return parse_reply_content(text), reply_usage


_GEMINI_CUT_OFF = frozenset({"incomplete", "budget_exceeded", "requires_continuation"})


def _gemini_reply(interaction: Any) -> tuple[dict[str, Any], TokenUsage | None]:
    status = getattr(interaction, "status", None)
    if status in _GEMINI_CUT_OFF:
        raise _cut_off()
    if status != "completed":
        raise ProviderError("terminal", f"The model call ended as {status!r}.")
    text = getattr(interaction, "output_text", None)
    if not isinstance(text, str) or not text.strip():
        raise _no_content()
    usage = getattr(interaction, "usage", None)
    reply_usage: TokenUsage | None = None
    inputs = getattr(usage, "total_input_tokens", None)
    outputs = getattr(usage, "total_output_tokens", None)
    if isinstance(inputs, int) and isinstance(outputs, int):
        thoughts = getattr(usage, "total_thought_tokens", None)
        thoughts = thoughts if isinstance(thoughts, int) else None
        reply_usage = TokenUsage(
            input_tokens=inputs,
            output_tokens=outputs + (thoughts or 0),
            reasoning_tokens=thoughts,
        )
    return parse_reply_content(text), reply_usage


_FENCE = re.compile(r"^```(?:json)?\s*\n?(?P<body>.*?)\n?```$", re.DOTALL)
_CLAUDE_BLOCKED = frozenset({"guardrail_intervened", "content_filtered"})


def _claude_reply(payload: Any) -> tuple[dict[str, Any], TokenUsage | None]:
    if not isinstance(payload, Mapping):
        raise ProviderError("terminal", "The gateway reply is not a JSON object.")
    stop = payload.get("stopReason")
    if stop == "max_tokens":
        raise _cut_off()
    if stop in _CLAUDE_BLOCKED:
        raise ProviderError("terminal", "The model reply was blocked.")
    output = payload.get("output")
    message = output.get("message") if isinstance(output, Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    blocks = [block for block in content or () if isinstance(block, Mapping)]
    data: dict[str, Any] | None = None
    for block in blocks:
        tool = block.get("toolUse")
        if isinstance(tool, Mapping) and tool.get("name") == ANSWER_TOOL:
            answer = tool.get("input")
            if isinstance(answer, str):
                data = parse_reply_content(answer)
            elif isinstance(answer, dict):
                data = answer
            else:
                raise ProviderError("terminal", "The model reply is not a JSON object.")
            break
    if data is None:
        text = "".join(
            block["text"] for block in blocks if isinstance(block.get("text"), str)
        ).strip()
        if not text:
            raise _no_content()
        fenced = _FENCE.match(text)
        data = parse_reply_content(fenced["body"] if fenced else text)
    usage = payload.get("usage")
    reply_usage: TokenUsage | None = None
    if isinstance(usage, Mapping):
        inputs, outputs = usage.get("inputTokens"), usage.get("outputTokens")
        if isinstance(inputs, int) and isinstance(outputs, int):
            reply_usage = TokenUsage(input_tokens=inputs, output_tokens=outputs)
    return data, reply_usage


# --- The client ----------------------------------------------------------------


class MaiClient:
    """Structured-output completions through the Posit mAI Gateway.

    ``connection`` (see :func:`~pcn_clone.ai.config.resolve_mai`) names the
    gateway, the mAI endpoint, the model family and model, and the app id.
    Each request sends the system and user prompts and the strict JSON
    schema in the family's own form; sampling and reasoning settings are
    left to the model, and the output is capped only when
    ``max_output_tokens`` is set (Claude: 8192 when it is not).

    Providers accept different JSON-Schema subsets in strict mode, so a 400
    that reads like a schema refusal resends the request at once with a
    simpler schema (:func:`schema_at_level`); the level reached is kept for
    later calls. Replies are validated by the caller either way.

    Each attempt is bounded by ``timeout_seconds`` and the whole call by
    ``timeout_seconds × (max_retries + 1)`` (at most 30 minutes). Failures
    before the request is sent, and HTTP 408, 409, 425, 429 and 5xx, are
    retried up to ``max_retries`` times; a read timeout or dropped
    connection, which the model may already be billing, is retried at most
    once. Waits double from ``backoff_seconds`` (capped at 30 s) with
    jitter, or follow the gateway's ``Retry-After``. The SDKs' own retries
    are off. Errors and logs never carry prompts, replies or request bodies.

    The SDK client (or, for Claude, the HTTP client) and its connection pool
    are created on first use for the running event loop and reused until
    :meth:`aclose`. ``rng`` replaces the jitter source (for tests).
    """

    def __init__(
        self,
        connection: MaiConnection,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        max_output_tokens: int | None = None,
        backoff_seconds: float = 1.0,
        rng: random.Random | None = None,
    ) -> None:
        self.connection = connection
        self.family = connection.family
        self.model = connection.model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.max_output_tokens = max_output_tokens
        self.backoff_seconds = backoff_seconds
        self.schema_level = 0
        self._rng = rng if rng is not None else random.Random()
        self._sdk: AsyncOpenAI | GenaiClient | httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def __repr__(self) -> str:
        return f"MaiClient(family={self.family!r}, model={self.model!r})"

    @property
    def deadline_seconds(self) -> float:
        """The overall deadline for one call, retries included."""
        return min(self.timeout_seconds * (self.max_retries + 1), DEADLINE_CAP_SECONDS)

    @property
    def headers(self) -> dict[str, str]:
        """The fixed headers every request carries."""
        return {
            "X-Posit-App-Id": self.connection.app_id,
            "x-source-type": SOURCE_TYPE,
        }

    @property
    def query(self) -> dict[str, str]:
        """The fixed query parameters every request carries."""
        return {"mai-endpoint": self.connection.endpoint}

    async def aclose(self) -> None:
        """Close the connection pool; a later call opens a new one. A pool
        opened on another event loop cannot be closed from this one and is
        dropped."""
        sdk, loop = self._sdk, self._loop
        self._sdk = self._loop = None
        if sdk is None or loop is not asyncio.get_running_loop():
            return
        if isinstance(sdk, httpx.AsyncClient):
            await sdk.aclose()
        elif self.family == "gpt":
            await cast("AsyncOpenAI", sdk).close()
        else:
            gemini = cast("GenaiClient", sdk)
            await gemini.aio.aclose()
            gemini.close()

    def _session(self) -> AsyncOpenAI | GenaiClient | httpx.AsyncClient:
        """The client bound to the running event loop, created on first use
        (a pool opened on another loop cannot be reused and is dropped)."""
        loop = asyncio.get_running_loop()
        if self._sdk is None or self._loop is not loop:
            self._sdk = self._build()
            self._loop = loop
        return self._sdk

    def _build(self) -> AsyncOpenAI | GenaiClient | httpx.AsyncClient:
        base_url = self.connection.base_url
        if self.family == "gpt":
            from openai import AsyncOpenAI

            return AsyncOpenAI(
                base_url=base_url,
                api_key=PLACEHOLDER_API_KEY,
                default_headers=self.headers,
                default_query=self.query,
                timeout=self.timeout_seconds,
                max_retries=0,
            )
        if self.family == "gemini":
            from google import genai
            from google.genai import types

            client_args: dict[str, Any] = {"params": self.query}
            return genai.Client(
                api_key=PLACEHOLDER_API_KEY,
                http_options=types.HttpOptions(
                    base_url=base_url.rstrip("/"),
                    api_version="",
                    headers=self.headers,
                    timeout=round(self.timeout_seconds * 1000),
                    client_args=client_args,
                    async_client_args=client_args,
                    retry_options=types.HttpRetryOptions(
                        attempts=1, http_status_codes=[599]
                    ),
                ),
            )
        return httpx.AsyncClient(
            headers={**self.headers, "Content-Type": "application/json"},
            timeout=self.timeout_seconds,
        )

    def _retry_delay(self, attempt: int, error: ProviderError) -> float | None:
        """Seconds to wait before the next attempt, or ``None`` to stop."""
        backoff = min(self.backoff_seconds * 2.0**attempt, BACKOFF_CAP_SECONDS)
        jittered = backoff * (0.5 + 0.5 * self._rng.random())
        if error.retry_after is None:
            return jittered
        if error.retry_after > RETRY_AFTER_CAP_SECONDS:
            return None
        return max(jittered, error.retry_after)

    async def complete(
        self, *, system: str, user: str, schema: dict[str, Any], format_name: str
    ) -> ModelReply:
        """Complete one request, retrying retryable failures within the
        overall deadline."""
        try:
            async with asyncio.timeout(self.deadline_seconds) as deadline:
                return await self._with_retries(
                    system, user, schema, format_name, deadline
                )
        except TimeoutError:
            raise ProviderError(
                "retryable",
                f"No reply within the overall deadline of {self.deadline_seconds:g} s.",
                after_send=True,
            ) from None

    async def _with_retries(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        format_name: str,
        deadline: asyncio.Timeout,
    ) -> ModelReply:
        loop = asyncio.get_running_loop()
        attempt = 0
        after_send_retries = 0
        while True:
            try:
                return await self._attempt(system, user, schema, format_name)
            except ProviderError as error:
                if error.kind == "terminal" or attempt >= self.max_retries:
                    raise
                if error.after_send:
                    if after_send_retries >= MAX_AFTER_SEND_RETRIES:
                        raise
                    after_send_retries += 1
                delay = self._retry_delay(attempt, error)
                ends = deadline.when()
                if delay is None or (ends is not None and loop.time() + delay >= ends):
                    raise
                logger.warning(
                    "mAI Gateway attempt %d failed (%s); retrying in %.1f s",
                    attempt + 1,
                    error.message,
                    delay,
                )
                attempt += 1
                await asyncio.sleep(delay)

    async def _attempt(
        self, system: str, user: str, schema: dict[str, Any], format_name: str
    ) -> ModelReply:
        """One attempt, resent at once with a simpler schema while the
        provider refuses the schema."""
        while True:
            level = self.schema_level
            try:
                data, usage = await self._send(
                    system, user, schema_at_level(schema, level), format_name
                )
            except _SchemaRejected as error:
                if level >= MAX_SCHEMA_LEVEL:
                    raise ProviderError(
                        error.kind, error.message, status=error.status
                    ) from None
                self.schema_level = max(self.schema_level, level + 1)
                logger.warning(
                    "The mAI Gateway rejected the %s response schema (%s); "
                    "resending at schema level %d",
                    self.family,
                    error.message,
                    self.schema_level,
                )
                continue
            return ModelReply(data=data, model=self.model, usage=usage)

    async def _send(
        self, system: str, user: str, schema: dict[str, Any], format_name: str
    ) -> tuple[dict[str, Any], TokenUsage | None]:
        try:
            session = self._session()
        except Exception as error:
            raise ProviderError(
                "terminal",
                f"The {self.family} client could not be created "
                f"({type(error).__name__}).",
            ) from None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                if self.family == "gpt":
                    return await self._attempt_gpt(
                        cast("AsyncOpenAI", session), system, user, schema, format_name
                    )
                if self.family == "gemini":
                    return await self._attempt_gemini(
                        cast("GenaiClient", session), system, user, schema
                    )
                return await self._attempt_claude(
                    cast(httpx.AsyncClient, session), system, user, schema
                )
        except ProviderError:
            raise
        except TimeoutError:
            raise ProviderError(
                "retryable",
                f"No reply within {self.timeout_seconds:g} s.",
                after_send=True,
            ) from None
        except Exception as error:
            raise _sdk_failure(error, self.timeout_seconds) from None

    async def _attempt_gpt(
        self,
        sdk: AsyncOpenAI,
        system: str,
        user: str,
        schema: dict[str, Any],
        format_name: str,
    ) -> tuple[dict[str, Any], TokenUsage | None]:
        options: dict[str, Any] = {}
        if self.max_output_tokens is not None:
            options["max_output_tokens"] = self.max_output_tokens
        response = await sdk.responses.create(
            model=self.model,
            instructions=system,
            input=[{"role": "user", "content": [{"type": "input_text", "text": user}]}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": format_name,
                    "schema": schema,
                    "strict": True,
                }
            },
            **options,
        )
        return _gpt_reply(response)

    async def _attempt_gemini(
        self, sdk: GenaiClient, system: str, user: str, schema: dict[str, Any]
    ) -> tuple[dict[str, Any], TokenUsage | None]:
        options: dict[str, Any] = {}
        if self.max_output_tokens is not None:
            options["generation_config"] = {"max_output_tokens": self.max_output_tokens}
        interactions: Any = sdk.aio.interactions
        interaction = await interactions.create(
            model=self.model,
            system_instruction=system,
            input=user,
            response_format=schema,
            response_mime_type="application/json",
            automatic_continuation=False,
            **options,
        )
        return _gemini_reply(interaction)

    async def _attempt_claude(
        self, http: httpx.AsyncClient, system: str, user: str, schema: dict[str, Any]
    ) -> tuple[dict[str, Any], TokenUsage | None]:
        body = {
            "system": [{"text": system}],
            "messages": [{"role": "user", "content": [{"text": user}]}],
            "inferenceConfig": {
                "maxTokens": self.max_output_tokens or CLAUDE_DEFAULT_MAX_TOKENS
            },
            "toolConfig": {
                "tools": [
                    {
                        "toolSpec": {
                            "name": ANSWER_TOOL,
                            "description": ANSWER_TOOL_DESCRIPTION,
                            "inputSchema": {"json": schema},
                        }
                    }
                ],
                "toolChoice": {"tool": {"name": ANSWER_TOOL}},
            },
        }
        response = await http.post(
            f"{self.connection.base_url}converse", params=self.query, json=body
        )
        if not response.is_success:
            raise _http_failure(response.status_code, response.text, response.headers)
        try:
            payload = response.json()
        except ValueError:
            raise ProviderError(
                "terminal", "The gateway reply is not valid JSON."
            ) from None
        return _claude_reply(payload)
