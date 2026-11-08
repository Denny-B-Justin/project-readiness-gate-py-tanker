"""Model clients: one structured-output completion per call.

:class:`ModelClient` is the seam every model call goes through.
:class:`~pcn_clone.ai.mai.MaiClient` calls GPT, Gemini or Claude models
through the Posit mAI Gateway with a strict JSON-schema output, a
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
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pcn_clone.ai.config import (
    FAKE_FAIL_ALL,
    MAI_PROVIDER,
    AiSettings,
    resolve_mai,
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

if TYPE_CHECKING:
    from pcn_clone.ai.mai import MaiClient

logger = logging.getLogger(__name__)

ProviderErrorKind = Literal["retryable", "terminal"]

RETRYABLE_STATUS_CODES = frozenset({408, 409, 425, 429})
"""Client-error statuses worth retrying; every 5xx status is retried too."""

MAX_AFTER_SEND_RETRIES = 1
"""Retries allowed after a failure that may have reached the model (a read
timeout or a dropped connection), which a retry may pay for twice."""

BACKOFF_CAP_SECONDS = 30.0
RETRY_AFTER_CAP_SECONDS = 60.0
"""The longest ``Retry-After`` honoured; a longer one ends the retries."""

DEADLINE_CAP_SECONDS = 1800.0
"""The longest overall deadline for one call, retries included."""


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


# --- HTTP failures -------------------------------------------------------------


def classify_status(status: int) -> ProviderErrorKind:
    """``retryable`` for 408, 409, 425, 429 and every 5xx status, else
    ``terminal``."""
    return (
        "retryable" if status in RETRYABLE_STATUS_CODES or status >= 500 else "terminal"
    )


_TRY_AGAIN_IN = re.compile(r"try again in (\d+(?:\.\d+)?) ?s(?:ec(?:ond)?s?)?\b", re.I)
_REPLENISHED_IN = re.compile(r"replenished in (\d+):(\d{2}):(\d{2})", re.I)


def _header_seconds(headers: Mapping[str, str]) -> float | None:
    millis = headers.get("retry-after-ms")
    if millis is not None:
        try:
            return float(millis) / 1000.0
        except ValueError:
            pass
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return (when - datetime.now(UTC)).total_seconds()


def _message_seconds(message: str) -> float | None:
    if (match := _TRY_AGAIN_IN.search(message)) is not None:
        return float(match[1])
    if (match := _REPLENISHED_IN.search(message)) is not None:
        hours, minutes, seconds = (int(part) for part in match.groups())
        return float(hours * 3600 + minutes * 60 + seconds)
    return None


def retry_after_seconds(
    headers: Mapping[str, str], message: str | None = None
) -> float | None:
    """The wait the provider asked for, or ``None`` when it named none.

    Read from a ``retry-after-ms`` header, a ``Retry-After`` header (delay
    seconds or an HTTP date) or, failing those, the error ``message`` (an
    API-management text such as "Try again in 12 seconds." or "Quota will
    be replenished in 05:12:00.").
    """
    seconds = _header_seconds(headers)
    if seconds is None and message is not None:
        seconds = _message_seconds(message)
    if seconds is None or not math.isfinite(seconds):
        return None
    return max(0.0, seconds)


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


def client_from_env(config: AiSettings | None = None) -> FakeClient | MaiClient:
    """A new client of the kind ``PCN_AI_PROVIDER`` selects, configured from
    ``config`` (default: the process settings).

    Raises :class:`AiConfigurationError` when the environment is malformed or
    incomplete for the mAI Gateway (see :func:`~pcn_clone.ai.config.resolve_mai`).
    """
    resolved = config if config is not None else settings()
    if resolved.provider == "fake":
        return FakeClient(
            delay_seconds=resolved.fake_delay_seconds, fail=resolved.fake_fail
        )
    from pcn_clone.ai.mai import MaiClient

    return MaiClient(
        resolve_mai(resolved),
        timeout_seconds=resolved.timeout_seconds,
        max_retries=resolved.max_retries,
        max_output_tokens=resolved.max_output_tokens,
    )


@dataclass(slots=True)
class _Shared:
    settings: AiSettings | None = None
    client: FakeClient | MaiClient | None = None


_shared = _Shared()


def shared_client() -> FakeClient | MaiClient:
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
    environment fails when the app starts; log the provider, model family
    and model, and warn when the fake provider is active. Raises
    :class:`AiConfigurationError`."""
    client = shared_client()
    if isinstance(client, FakeClient):
        logger.warning(
            "PCN_AI_PROVIDER=fake: field evaluations are canned offline replies, "
            "not model output."
        )
    else:
        logger.info(
            "AI provider %s: %s family, model %s",
            MAI_PROVIDER,
            client.family,
            client.model,
        )


async def aclose() -> None:
    """Close the shared client's connections (at app shutdown)."""
    client = _shared.client
    _shared.client = _shared.settings = None
    if client is not None:
        await client.aclose()
