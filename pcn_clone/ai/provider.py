"""Model clients: one structured-output completion per call.

:class:`ModelClient` is the seam every model call goes through.
:class:`OpenRouterClient` calls OpenRouter's Chat Completions endpoint
through the official SDK with a strict JSON-schema response format, a
per-attempt timeout, bounded retries and an overall deadline.
:class:`FakeClient` answers deterministically from the request, without a
network, for development and tests. Failures surface as
:class:`ProviderError`, classified as ``retryable`` (a later attempt may
succeed) or ``terminal``.

A process shares one client for its settings (:func:`shared_client`):
:func:`startup` builds it when the app starts, so a misconfiguration stops
the app, and :func:`aclose` releases its connections at shutdown.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import random
import re
from collections.abc import Iterable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal, Protocol

import httpx
from openrouter import OpenRouter, errors
from openrouter.components import (
    ChatContentText,
    ChatFormatJSONSchemaConfigTypedDict,
    ChatMessagesTypedDict,
    ChatResult,
    ProviderPreferencesTypedDict,
)

from pcn_clone.ai.config import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    FAKE_FAIL_ALL,
    AiConfigurationError,
    AiSettings,
    settings,
)
from pcn_clone.ai.schemas import (
    ASSESSMENT_FINDING_FORMAT,
    FIELD_EVALUATION_FORMAT,
    MCA_SCORE_FINDING_FORMAT,
    VERDICTS,
)
from pcn_clone.content import load_assessment, load_mca, load_template
from pcn_clone.core.evidence import verify_quote
from pcn_clone.core.jsstr import js_trim
from pcn_clone.core.serialize import INVALID_ANSWER_HEADER, NO_ANSWER_MARKER

logger = logging.getLogger(__name__)

ProviderErrorKind = Literal["retryable", "terminal"]

RETRYABLE_STATUS_CODES = frozenset({408, 409, 429})
"""Client-error statuses worth retrying; every 5xx status is retried too."""

MAX_AFTER_SEND_RETRIES = 1
"""Retries allowed after a failure that may have reached the model (a read
timeout or a dropped connection), which a retry may pay for twice."""

BACKOFF_CAP_SECONDS = 30.0
RETRY_AFTER_CAP_SECONDS = 60.0
"""The longest ``Retry-After`` honoured; a longer one ends the retries."""

DEADLINE_CAP_SECONDS = 1800.0
"""The longest overall deadline for one call, retries included."""

_PRE_SEND_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


class ProviderError(Exception):
    """A failed model call. ``retryable`` failures (timeouts, connection
    errors, rate limits, server errors) may succeed on a later attempt;
    ``terminal`` ones (bad credentials, a rejected request, an unusable
    reply) will not.

    ``status`` is the HTTP status when there was one, ``retry_after`` the
    wait in seconds the provider asked for, and ``after_send`` is true when
    the request may have reached the model before failing.
    """

    def __init__(
        self,
        kind: ProviderErrorKind,
        message: str,
        *,
        status: int | None = None,
        retry_after: float | None = None,
        after_send: bool = False,
    ) -> None:
        super().__init__(message)
        self.kind: ProviderErrorKind = kind
        self.message = message
        self.status = status
        self.retry_after = retry_after
        self.after_send = after_send


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Provider-reported token counts for one call. ``output_tokens``
    includes ``reasoning_tokens`` when the provider reports them."""

    input_tokens: int
    output_tokens: int
    reasoning_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ModelReply:
    """A completed call: the parsed JSON object, the model id that answered
    and its token usage when reported."""

    data: dict[str, Any]
    model: str
    usage: TokenUsage | None = None


class ModelClient(Protocol):
    """Anything that completes one structured-output request."""

    async def complete(
        self, *, system: str, user: str, schema: dict[str, Any], format_name: str
    ) -> ModelReply:
        """Return the model's JSON reply to ``system`` and ``user``,
        constrained to ``schema``. Raises :class:`ProviderError`."""
        ...


def parse_reply_content(content: str) -> dict[str, Any]:
    """The JSON object a reply carries. Raises a terminal
    :class:`ProviderError` when it is not a JSON object."""
    try:
        data = json.loads(content)
    except ValueError:
        raise ProviderError("terminal", "The model reply is not valid JSON.") from None
    if not isinstance(data, dict):
        raise ProviderError("terminal", "The model reply is not a JSON object.")
    return data


# --- OpenRouter --------------------------------------------------------------


def classify_status(status: int) -> ProviderErrorKind:
    """``retryable`` for 408, 409, 429 and every 5xx status, else ``terminal``."""
    return (
        "retryable" if status in RETRYABLE_STATUS_CODES or status >= 500 else "terminal"
    )


def retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    """The wait a ``Retry-After`` header asks for (delay seconds or an HTTP
    date), or ``None`` when absent or unreadable."""
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        seconds = (when - datetime.now(UTC)).total_seconds()
    return max(0.0, seconds) if math.isfinite(seconds) else None


def _reply_text(result: ChatResult) -> str:
    if not result.choices:
        raise ProviderError("terminal", "The provider returned no choices.")
    message = result.choices[0].message
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.text for part in content if isinstance(part, ChatContentText)
        )
    if isinstance(message.refusal, str) and message.refusal:
        raise ProviderError("terminal", f"The model refused: {message.refusal}")
    raise ProviderError("terminal", "The model returned no content.")


def _usage(result: ChatResult) -> TokenUsage | None:
    usage = result.usage
    if usage is None:
        return None
    details = usage.completion_tokens_details
    reasoning = getattr(details, "reasoning_tokens", None)
    return TokenUsage(
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        reasoning_tokens=reasoning if isinstance(reasoning, int) else None,
    )


class OpenRouterClient:
    """Structured-output completions through OpenRouter Chat Completions.

    Each request pins the strict JSON schema as ``response_format`` and asks
    OpenRouter to route only to providers that honour every request
    parameter. Temperature, token limits and reasoning effort are left to the
    model's defaults.

    Each attempt is bounded by ``timeout_seconds`` and the whole call by
    ``timeout_seconds × (max_retries + 1)`` (at most 30 minutes). Failures
    before the request is sent, and HTTP 408, 409, 429 and 5xx, are retried
    up to ``max_retries`` times; a read timeout or dropped connection, which
    the model may already be billing, is retried at most once. Waits double
    from ``backoff_seconds`` (capped at 30 s) with jitter, or follow the
    provider's ``Retry-After``. Error messages never contain the API key.

    The HTTP connection pool and SDK are created on first use and reused
    until :meth:`aclose`. ``transport`` replaces the HTTP transport and
    ``rng`` the jitter source (for tests).
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        provider_order: Iterable[str] = (),
        backoff_seconds: float = 1.0,
        transport: httpx.AsyncBaseTransport | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.provider_order = tuple(provider_order)
        self.backoff_seconds = backoff_seconds
        self._api_key = api_key
        self._transport = transport
        self._rng = rng if rng is not None else random.Random()
        self._sdk: OpenRouter | None = None
        self._http: httpx.AsyncClient | None = None
        self._resources = ExitStack()
        self._loop: asyncio.AbstractEventLoop | None = None

    def __repr__(self) -> str:
        return f"OpenRouterClient(model={self.model!r})"

    @property
    def deadline_seconds(self) -> float:
        """The overall deadline for one call, retries included."""
        return min(self.timeout_seconds * (self.max_retries + 1), DEADLINE_CAP_SECONDS)

    def provider_preferences(self) -> ProviderPreferencesTypedDict:
        """The OpenRouter ``provider`` routing object sent with each request."""
        preferences: ProviderPreferencesTypedDict = {"require_parameters": True}
        if self.provider_order:
            preferences["order"] = list(self.provider_order)
        return preferences

    async def aclose(self) -> None:
        """Close the connection pool; a later call opens a new one."""
        http, resources = self._http, self._resources
        self._sdk = self._http = self._loop = None
        self._resources = ExitStack()
        resources.close()
        if http is not None:
            await http.aclose()

    def _session(self) -> OpenRouter:
        """The SDK bound to the running event loop, created on first use (a
        pool opened on another loop cannot be reused and is dropped)."""
        loop = asyncio.get_running_loop()
        if self._sdk is None or self._loop is not loop:
            self._resources.close()
            self._resources = ExitStack()
            self._http = httpx.AsyncClient(
                transport=self._transport, follow_redirects=True
            )
            self._sdk = self._resources.enter_context(
                OpenRouter(api_key=self._api_key, async_client=self._http)
            )
            self._loop = loop
        return self._sdk

    def _redact(self, text: str) -> str:
        return text.replace(self._api_key, "[redacted]") if self._api_key else text

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
                    "OpenRouter attempt %d failed (%s); retrying in %.1f s",
                    attempt + 1,
                    error.message,
                    delay,
                )
                attempt += 1
                await asyncio.sleep(delay)

    async def _attempt(
        self, system: str, user: str, schema: dict[str, Any], format_name: str
    ) -> ModelReply:
        messages: list[ChatMessagesTypedDict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        response_format: ChatFormatJSONSchemaConfigTypedDict = {
            "type": "json_schema",
            "json_schema": {"name": format_name, "strict": True, "schema_": schema},
        }
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self._session().chat.send_async(
                    model=self.model,
                    messages=messages,
                    response_format=response_format,
                    provider=self.provider_preferences(),
                    stream=False,
                    retries=None,
                    timeout_ms=round(self.timeout_seconds * 1000),
                )
        except errors.OpenRouterError as error:
            raise ProviderError(
                classify_status(error.status_code),
                self._redact(
                    f"OpenRouter returned HTTP {error.status_code}: {error.message}"
                ),
                status=error.status_code,
                retry_after=retry_after_seconds(error.headers),
            ) from None
        except _PRE_SEND_ERRORS as error:
            raise ProviderError(
                "retryable",
                self._redact(f"The connection could not be made: {error!r}"),
            ) from None
        except (TimeoutError, httpx.TimeoutException):
            raise ProviderError(
                "retryable",
                f"No reply within {self.timeout_seconds:g} s.",
                after_send=True,
            ) from None
        except (httpx.TransportError, errors.NoResponseError) as error:
            raise ProviderError(
                "retryable",
                self._redact(f"The connection failed: {error!r}"),
                after_send=True,
            ) from None
        except Exception as error:
            raise ProviderError(
                "terminal", self._redact(f"The request could not be made: {error!r}")
            ) from None
        return ModelReply(
            data=parse_reply_content(_reply_text(result)),
            model=result.model,
            usage=_usage(result),
        )


# --- Fake --------------------------------------------------------------------

_DOCUMENT_FIELD = re.compile(
    r"^### (?P<label>.+?) "
    r"\(sectionId: (?P<section>[^,\n]+), fieldId: (?P<field>[^)\n]+)\)\n"
    r'"""\n(?P<text>.*?)\n"""(?=\n\n|\Z)',
    re.MULTILINE | re.DOTALL,
)
_ANSWER = re.compile(
    r'^## Proposer\'s answer\n"""\n(?P<text>.*?)\n"""$', re.MULTILINE | re.DOTALL
)
_QUOTE_LIMIT = 120


@dataclass(frozen=True, slots=True)
class _DocumentField:
    label: str
    section_id: str
    field_id: str
    text: str


def _document_fields(user: str) -> list[_DocumentField]:
    return [
        _DocumentField(match["label"], match["section"], match["field"], match["text"])
        for match in _DOCUMENT_FIELD.finditer(user)
    ]


def _quote_from(text: str) -> str | None:
    """A short verbatim quote: the leading words of the first non-blank line."""
    line = next((js_trim(line) for line in text.splitlines() if js_trim(line)), "")
    if len(line) > _QUOTE_LIMIT:
        cut = line.rfind(" ", 0, _QUOTE_LIMIT)
        line = line[: cut if cut > 0 else _QUOTE_LIMIT].rstrip()
    return line if line and verify_quote(line, text) else None


class FakeClient:
    """A deterministic, offline stand-in for the model.

    Replies are schema-valid and derived from the request: the verdict or
    score comes from a stable hash of the user prompt (a blank field answer
    always fails), the prose names the field, dimension or criterion, and
    citations quote real text from the submission so quote verification
    succeeds. ``delay_seconds`` simulates latency; ``fail`` lists field,
    dimension or criterion ids whose calls raise a retryable
    :class:`ProviderError` (``*`` fails every call).
    """

    def __init__(
        self,
        *,
        delay_seconds: float = 0.0,
        fail: Iterable[str] = (),
        model: str = "fake/pcn-reviewer",
    ) -> None:
        self.delay_seconds = delay_seconds
        self.fail = frozenset(fail)
        self.model = model

    async def complete(
        self, *, system: str, user: str, schema: dict[str, Any], format_name: str
    ) -> ModelReply:
        """Answer one request deterministically."""
        if self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)
        subject_id, label = _subject(user, format_name)
        if FAKE_FAIL_ALL in self.fail or subject_id in self.fail:
            raise ProviderError("retryable", f"Injected fake failure for {subject_id}.")
        seed = int.from_bytes(hashlib.sha256(user.encode("utf-8")).digest()[:8])
        if format_name == FIELD_EVALUATION_FORMAT:
            data = _fake_field_evaluation(user, label, seed)
        elif format_name == ASSESSMENT_FINDING_FORMAT:
            data = _fake_assessment(user, label, seed)
        else:
            data = _fake_mca_score(user, label, seed, schema)
        return ModelReply(data=data, model=self.model)

    async def aclose(self) -> None:
        """Release nothing: the fake holds no connections."""


def _subject(user: str, format_name: str) -> tuple[str, str]:
    """The id and display label of what a request asks about."""
    parts = user.split("\n\n")
    heading = parts[1] if len(parts) > 1 else ""
    if format_name == FIELD_EVALUATION_FORMAT:
        for _, field in load_template().iter_fields():
            if heading == f"Field {field.number}: {field.title}":
                return field.id, f"{field.number} {field.title}"
        return heading, heading
    if format_name == ASSESSMENT_FINDING_FORMAT:
        dimensions = load_assessment().dimensions
        match = next((d.id for d in dimensions if d.label == heading), heading)
        return match, heading
    if format_name == MCA_SCORE_FINDING_FORMAT:
        criteria = load_mca().matrix.criteria
        match = next((c.id for c in criteria if c.label == heading), heading)
        return match, heading
    raise ProviderError("terminal", f'Unknown response format "{format_name}".')


def _fake_field_evaluation(user: str, label: str, seed: int) -> dict[str, Any]:
    answer = _ANSWER.search(user)
    blank = answer is None or answer["text"] == "(no answer provided)"
    verdict = "fail" if blank else VERDICTS[seed % len(VERDICTS)]
    reasoning = {
        "fail": (
            f"Fake evaluation of {label}: the answer matches the Fail descriptor; "
            "it does not yet give the information the field guidance asks for."
        ),
        "notClear": (
            f"Fake evaluation of {label}: the answer matches the Not Clear "
            "descriptor; it addresses the field but is too general to award Pass."
        ),
        "pass": (
            f"Fake evaluation of {label}: the answer matches the Pass descriptor "
            "and follows the field guidance."
        ),
    }[verdict]
    suggestions = (
        [f"Optionally add one concrete figure to strengthen {label}."]
        if verdict == "pass"
        else [
            f"Address each point of the official guidance for {label}.",
            f"Support {label} with specific figures, dates or sources.",
        ]
    )
    return {"verdict": verdict, "reasoning": reasoning, "suggestions": suggestions}


def _citations(user: str, seed: int, limit: int) -> list[dict[str, str]]:
    """Up to ``limit`` verifiable citations of answered fields."""
    answered = [
        field
        for field in _document_fields(user)
        if field.text != NO_ANSWER_MARKER
        and not field.text.startswith(INVALID_ANSWER_HEADER)
    ]
    if not answered:
        return []
    start = seed % len(answered)
    citations: list[dict[str, str]] = []
    for offset in range(len(answered)):
        field = answered[(start + offset) % len(answered)]
        quote = _quote_from(field.text)
        cited = {(c["sectionId"], c["fieldId"]) for c in citations}
        if quote is not None and (field.section_id, field.field_id) not in cited:
            citations.append(
                {
                    "sectionId": field.section_id,
                    "fieldId": field.field_id,
                    "quote": quote,
                }
            )
        if len(citations) == limit:
            break
    return citations


def _fake_assessment(user: str, label: str, seed: int) -> dict[str, Any]:
    evidence = _citations(user, seed, 2)
    verdict = VERDICTS[seed % len(VERDICTS)] if evidence else "notClear"
    return {
        "verdict": verdict,
        "reasoning": (
            f"Fake assessment of {label}: the submission is read against the "
            f"dimension's rubric and the cited passages support a {verdict} verdict."
        ),
        "evidence": evidence,
        "questions": [f"What further evidence supports the {label.lower()} case?"],
    }


def _fake_mca_score(
    user: str, label: str, seed: int, schema: Mapping[str, Any]
) -> dict[str, Any]:
    branches = schema["properties"]["basis"]["anyOf"]
    documented = branches[0]["properties"]["score"]
    minimum = branches[1]["properties"]["score"]["const"]
    evidence = _citations(user, seed, 2)
    if not evidence:
        return {
            "justification": (
                f"Fake score for {label}: the submission is silent on this "
                "criterion, so the score is the scale minimum."
            ),
            "basis": {"kind": "not_evidenced", "score": minimum},
        }
    span = documented["maximum"] - documented["minimum"] + 1
    score = documented["minimum"] + seed % span
    return {
        "justification": (
            f"Fake score for {label}: the cited passages match the descriptor "
            f"for score {score}. A higher descriptor is not evidenced."
        ),
        "basis": {"kind": "documented", "score": score, "evidence": evidence},
    }


# --- Selection ---------------------------------------------------------------


def client_from_env(config: AiSettings | None = None) -> FakeClient | OpenRouterClient:
    """A new client of the kind ``PCN_AI_PROVIDER`` selects, configured from
    ``config`` (default: the process settings).

    Raises :class:`AiConfigurationError` when the environment is malformed or
    the OpenRouter provider has no API key.
    """
    resolved = config if config is not None else settings()
    if resolved.provider == "fake":
        return FakeClient(
            delay_seconds=resolved.fake_delay_seconds, fail=resolved.fake_fail
        )
    if resolved.openrouter_api_key is None:
        raise AiConfigurationError(
            "PCN_AI_PROVIDER is openrouter but OPENROUTER_API_KEY is not set; "
            "set the key, or set PCN_AI_PROVIDER=fake for offline replies."
        )
    return OpenRouterClient(
        api_key=resolved.openrouter_api_key,
        model=resolved.openrouter_model,
        timeout_seconds=resolved.timeout_seconds,
        max_retries=resolved.max_retries,
        provider_order=resolved.provider_order,
    )


@dataclass(slots=True)
class _Shared:
    settings: AiSettings | None = None
    client: FakeClient | OpenRouterClient | None = None


_shared = _Shared()


def shared_client() -> FakeClient | OpenRouterClient:
    """The process-wide client for the current settings, created on first use
    and rebuilt when the settings change (after ``reset_settings``).

    Raises :class:`AiConfigurationError` like :func:`client_from_env`.
    """
    current = settings()
    if _shared.client is None or _shared.settings is not current:
        _shared.client = client_from_env(current)
        _shared.settings = current
    return _shared.client


def startup() -> None:
    """Resolve the settings and build the shared client, so a misconfigured
    environment fails when the app starts; warn when the fake provider is
    active. Raises :class:`AiConfigurationError`."""
    if isinstance(shared_client(), FakeClient):
        logger.warning(
            "PCN_AI_PROVIDER=fake: field evaluations are canned offline replies, "
            "not model output."
        )


async def aclose() -> None:
    """Close the shared client's connections (at app shutdown)."""
    client = _shared.client
    _shared.client = _shared.settings = None
    if client is not None:
        await client.aclose()
