"""AI provider settings, read from the environment once per process.

A ``.env`` file in the working directory is read first when present; its
values never override variables already set in the environment. Blank
values count as unset.

- ``PCN_AI_PROVIDER`` — ``WB-mAI`` (default; the Posit mAI Gateway) or
  ``fake``, in any letter case.
- ``MAI_BASE_URL`` — the gateway URL (required by ``WB-mAI``); a missing
  trailing ``/`` is added.
- ``MAI_ENDPOINT`` — the mAI endpoint, sent as the ``mai-endpoint`` query
  parameter (required by ``WB-mAI``). It also names the model family: GPT
  (``.../openai/responses``), Gemini (``.../gemini/interactions``) or Claude
  (``.../bedrock/model/us.anthropic.<model>/converse``).
- ``MAI_MODEL`` — the model name (optional; default per family:
  ``gpt-5.6-luna``, ``gemini-3.8-flash`` or ``claude-haiku-5-5``). It must
  belong to the same family as ``MAI_ENDPOINT``.
- ``CONNECT_CONTENT_GUID`` — set by Posit Connect itself and sent as the
  ``X-Posit-App-Id`` header (required by ``WB-mAI``).
- ``PCN_AI_TIMEOUT_SECONDS`` — per-attempt request timeout, above 0
  (default 600).
- ``PCN_AI_MAX_RETRIES`` — retries after the first attempt on retryable
  failures, 0 to 5 (default 2).
- ``PCN_AI_MAX_OUTPUT_TOKENS`` — the output cap per call, a positive whole
  number (default: the model's own; Claude always sends one, 8192).
- ``PCN_AI_FAKE_DELAY_SECONDS`` — fake-provider latency (default 0).
- ``PCN_AI_FAKE_FAIL`` — comma-separated field, dimension or criterion ids
  the fake provider fails with a retryable error, or ``*`` for every call.

The gateway authenticates the app itself, so no API key, token or
subscription key is read. :func:`resolve_mai` turns the settings into the
connection the gateway client uses.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

ProviderName = Literal["WB-mAI", "fake"]
ModelFamily = Literal["gpt", "gemini", "claude"]

MAI_PROVIDER: ProviderName = "WB-mAI"
DEFAULT_MODELS: Mapping[ModelFamily, str] = {
    "gpt": "gpt-5.6-luna",
    "gemini": "gemini-3.8-flash",
    "claude": "claude-haiku-5-5",
}
DEFAULT_TIMEOUT_SECONDS = 600.0
DEFAULT_MAX_RETRIES = 2
MAX_RETRIES_LIMIT = 5
FAKE_FAIL_ALL = "*"


class AiConfigurationError(ValueError):
    """The AI settings are malformed or incomplete (for example, the mAI
    Gateway provider without ``MAI_BASE_URL``)."""


@dataclass(frozen=True, slots=True)
class AiSettings:
    """The AI provider settings as read from the environment. The mAI
    values are checked for completeness by :func:`resolve_mai`."""

    provider: ProviderName = MAI_PROVIDER
    mai_base_url: str | None = None
    mai_endpoint: str | None = None
    mai_model: str | None = None
    connect_content_guid: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    max_output_tokens: int | None = None
    fake_delay_seconds: float = 0.0
    fake_fail: frozenset[str] = frozenset()


_ASSIGNMENT = re.compile(r"^(?:export\s+)?(?P<key>[^=\s]+)\s*=\s*(?P<value>.*)$")
_INLINE_COMMENT = re.compile(r"\s+#.*$")


def _dotenv_value(raw: str) -> str:
    """A value with matching quotes unwrapped (anything after the closing
    quote is a comment) or, unquoted, with a whitespace-led ``#`` comment
    removed."""
    if raw[:1] in ("'", '"'):
        closing = raw.find(raw[0], 1)
        if closing != -1:
            return raw[1:closing]
    return _INLINE_COMMENT.sub("", raw).strip()


def parse_dotenv(text: str) -> dict[str, str]:
    """The ``KEY=value`` pairs of a ``.env`` file.

    Blank lines and ``#`` comment lines are skipped, an ``export`` prefix is
    allowed, a value in matching single or double quotes is taken verbatim
    up to the closing quote, and an unquoted value ends at a ``#`` that
    follows whitespace. A leading byte-order mark is ignored.
    """
    values: dict[str, str] = {}
    for raw_line in text.removeprefix("﻿").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGNMENT.match(line)
        if match is not None:
            values[match["key"]] = _dotenv_value(match["value"])
    return values


def _non_empty(environ: Mapping[str, str], name: str) -> str | None:
    value = environ.get(name, "").strip()
    return value or None


def _seconds(
    environ: Mapping[str, str], name: str, default: float, *, allow_zero: bool
) -> float:
    raw = _non_empty(environ, name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise AiConfigurationError(f"{name} must be a number, got {raw!r}.") from None
    in_range = value >= 0 if allow_zero else value > 0
    if not (math.isfinite(value) and in_range):
        bound = ">= 0" if allow_zero else "> 0"
        raise AiConfigurationError(
            f"{name} must be a finite number {bound}, got {raw!r}."
        )
    return value


def _retries(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = _non_empty(environ, name)
    if raw is None:
        return default
    if not raw.isdigit() or int(raw) > MAX_RETRIES_LIMIT:
        raise AiConfigurationError(
            f"{name} must be a whole number from 0 to {MAX_RETRIES_LIMIT}, got {raw!r}."
        )
    return int(raw)


def _positive_int(environ: Mapping[str, str], name: str) -> int | None:
    raw = _non_empty(environ, name)
    if raw is None:
        return None
    if not raw.isdigit() or int(raw) == 0:
        raise AiConfigurationError(
            f"{name} must be a positive whole number, got {raw!r}."
        )
    return int(raw)


def _base_url(environ: Mapping[str, str], name: str) -> str | None:
    raw = _non_empty(environ, name)
    if raw is None:
        return None
    if not re.match(r"^https?://[^/\s]+", raw, re.IGNORECASE):
        raise AiConfigurationError(
            f"{name} must be an http:// or https:// URL, got {raw!r}."
        )
    return raw if raw.endswith("/") else f"{raw}/"


def _id_list(environ: Mapping[str, str], name: str) -> tuple[str, ...]:
    raw = environ.get(name, "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def load_settings(environ: Mapping[str, str]) -> AiSettings:
    """Resolve settings from an environment mapping.

    Raises :class:`AiConfigurationError` naming the variable when a value is
    malformed.
    """
    provider = _non_empty(environ, "PCN_AI_PROVIDER") or MAI_PROVIDER
    if provider.lower() not in (MAI_PROVIDER.lower(), "fake"):
        raise AiConfigurationError(
            f'PCN_AI_PROVIDER must be "{MAI_PROVIDER}" or "fake", got {provider!r}.'
        )
    return AiSettings(
        provider="fake" if provider.lower() == "fake" else MAI_PROVIDER,
        mai_base_url=_base_url(environ, "MAI_BASE_URL"),
        mai_endpoint=_non_empty(environ, "MAI_ENDPOINT"),
        mai_model=_non_empty(environ, "MAI_MODEL"),
        connect_content_guid=_non_empty(environ, "CONNECT_CONTENT_GUID"),
        timeout_seconds=_seconds(
            environ,
            "PCN_AI_TIMEOUT_SECONDS",
            DEFAULT_TIMEOUT_SECONDS,
            allow_zero=False,
        ),
        max_retries=_retries(environ, "PCN_AI_MAX_RETRIES", DEFAULT_MAX_RETRIES),
        max_output_tokens=_positive_int(environ, "PCN_AI_MAX_OUTPUT_TOKENS"),
        fake_delay_seconds=_seconds(
            environ, "PCN_AI_FAKE_DELAY_SECONDS", 0.0, allow_zero=True
        ),
        fake_fail=frozenset(_id_list(environ, "PCN_AI_FAKE_FAIL")),
    )


# --- The mAI connection ------------------------------------------------------

_FAMILY_NAMES: Mapping[ModelFamily, str] = {
    "gpt": "GPT",
    "gemini": "Gemini",
    "claude": "Claude",
}
_CLAUDE_MODEL_PREFIXES = ("us.anthropic.", "anthropic.")
_CLAUDE_MODEL_SEGMENT = re.compile(r"(?P<head>/model/)(?P<model>[^/?#]+)(?=/converse)")
_MODEL_PLACEHOLDER = re.compile(r"<model>|%3Cmodel%3E", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class MaiConnection:
    """Everything a gateway request needs: the gateway URL (ending in
    ``/``), the ``mai-endpoint`` value (for Claude, with the model written
    into its path), the model family and name, and the Posit app id."""

    base_url: str
    endpoint: str
    family: ModelFamily
    model: str
    app_id: str


def _family_of_model(model: str) -> ModelFamily | None:
    name = model.lower()
    if name.startswith("gpt"):
        return "gpt"
    if name.startswith("gemini"):
        return "gemini"
    if name.startswith(("claude", *_CLAUDE_MODEL_PREFIXES)):
        return "claude"
    return None


def _family_of_endpoint(endpoint: str) -> ModelFamily | None:
    path = endpoint.lower().split("?", 1)[0].rstrip("/")
    if "/openai/" in path or path.endswith("/responses"):
        return "gpt"
    if "/gemini/" in path or path.endswith("/interactions"):
        return "gemini"
    if "/bedrock/" in path or path.endswith("/converse"):
        return "claude"
    return None


def _bare_claude_model(model: str) -> str:
    """A Claude model id without its ``us.anthropic.`` (or ``anthropic.``)
    inference-profile prefix."""
    for prefix in _CLAUDE_MODEL_PREFIXES:
        if model.lower().startswith(prefix):
            return model[len(prefix) :]
    return model


def _claude_endpoint_model(endpoint: str) -> str | None:
    """The concrete model a Claude endpoint names, or ``None`` when its
    model segment is missing or still the ``<model>`` placeholder."""
    match = _CLAUDE_MODEL_SEGMENT.search(endpoint)
    if match is None or _MODEL_PLACEHOLDER.search(match["model"]):
        return None
    return _bare_claude_model(match["model"])


def _claude_endpoint(endpoint: str, model: str) -> str:
    """``endpoint`` with its model path segment naming ``model``: the
    ``<model>`` placeholder is filled in, or the model after an existing
    ``...anthropic.`` prefix is replaced. The host is left alone."""
    match = _CLAUDE_MODEL_SEGMENT.search(endpoint)
    if match is None:
        return endpoint
    segment = match["model"]
    if _MODEL_PLACEHOLDER.search(segment):
        replaced = _MODEL_PLACEHOLDER.sub(model, segment)
    else:
        cut = segment.lower().rfind("anthropic.")
        prefix = segment[: cut + len("anthropic.")] if cut >= 0 else "us.anthropic."
        replaced = prefix + model
    return endpoint[: match.start("model")] + replaced + endpoint[match.end("model") :]


def resolve_mai(config: AiSettings) -> MaiConnection:
    """The gateway connection the mAI settings describe.

    The model family comes from ``MAI_MODEL`` when its name says it, else
    from ``MAI_ENDPOINT``. The model is ``MAI_MODEL``, else (Claude) the one
    the endpoint names, else the family default; a Claude model is reported
    without its ``us.anthropic.`` prefix.

    Raises :class:`AiConfigurationError` naming the variable when one is
    missing, when no family can be told, or when the model and endpoint
    belong to different families.
    """
    if config.mai_base_url is None:
        raise AiConfigurationError(
            f"PCN_AI_PROVIDER is {MAI_PROVIDER} but MAI_BASE_URL is not set; set "
            "the gateway URL, or set PCN_AI_PROVIDER=fake for offline replies."
        )
    if config.mai_endpoint is None:
        raise AiConfigurationError(
            f"PCN_AI_PROVIDER is {MAI_PROVIDER} but MAI_ENDPOINT is not set; set "
            "the mAI endpoint, or set PCN_AI_PROVIDER=fake for offline replies."
        )
    if config.connect_content_guid is None:
        raise AiConfigurationError(
            f"PCN_AI_PROVIDER is {MAI_PROVIDER} but CONNECT_CONTENT_GUID is not "
            "set: the mAI Gateway only answers apps running on Posit Connect, "
            "which sets it. Set PCN_AI_PROVIDER=fake for offline replies."
        )
    endpoint_family = _family_of_endpoint(config.mai_endpoint)
    model_family = (
        _family_of_model(config.mai_model) if config.mai_model is not None else None
    )
    if (
        model_family is not None
        and endpoint_family is not None
        and model_family != endpoint_family
    ):
        raise AiConfigurationError(
            f"MAI_MODEL is a {_FAMILY_NAMES[model_family]} model but MAI_ENDPOINT "
            f"is a {_FAMILY_NAMES[endpoint_family]} endpoint; use the same "
            "provider for both."
        )
    family = model_family or endpoint_family
    if family is None:
        raise AiConfigurationError(
            "MAI_ENDPOINT is not a GPT (.../openai/responses), Gemini "
            "(.../gemini/interactions) or Claude (.../bedrock/model/.../converse) "
            "endpoint, and MAI_MODEL does not name a model family."
        )
    endpoint = config.mai_endpoint
    model = config.mai_model
    if family == "claude":
        model = _bare_claude_model(model) if model is not None else None
        model = model or _claude_endpoint_model(endpoint) or DEFAULT_MODELS[family]
        endpoint = _claude_endpoint(endpoint, model)
    return MaiConnection(
        base_url=config.mai_base_url,
        endpoint=endpoint,
        family=family,
        model=model or DEFAULT_MODELS[family],
        app_id=config.connect_content_guid,
    )


# --- The process settings ----------------------------------------------------


def environment(dotenv_path: Path | None = None) -> dict[str, str]:
    """The process environment over the values of a ``.env`` file (default:
    ``.env`` in the working directory), the process environment winning."""
    path = dotenv_path if dotenv_path is not None else Path.cwd() / ".env"
    file_values = (
        parse_dotenv(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}
    )
    return {**file_values, **os.environ}


@cache
def settings() -> AiSettings:
    """The process-wide settings, resolved on first use and cached until
    :func:`reset_settings`.

    Raises :class:`AiConfigurationError` when an environment value is
    malformed.
    """
    return load_settings(environment())


def reset_settings() -> None:
    """Forget the cached settings so the next :func:`settings` call reads the
    environment again (and the shared model client is rebuilt from them)."""
    settings.cache_clear()
