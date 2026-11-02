"""AI provider settings, read from the environment once per process.

A ``.env`` file in the working directory is read first when present; its
values never override variables already set in the environment. Every
variable is optional:

- ``OPENROUTER_API_KEY`` — the OpenRouter key (required by the OpenRouter
  provider only).
- ``OPENROUTER_MODEL`` — the model id (default ``openai/gpt-5.6-luna``).
- ``PCN_AI_PROVIDER`` — ``openrouter`` (default) or ``fake``.
- ``PCN_AI_TIMEOUT_SECONDS`` — per-attempt request timeout, above 0
  (default 600).
- ``PCN_AI_MAX_RETRIES`` — retries after the first attempt on retryable
  failures, 0 to 5 (default 2).
- ``PCN_AI_PROVIDER_ORDER`` — comma-separated OpenRouter provider slugs to
  try in order (default: OpenRouter's own routing).
- ``PCN_AI_FAKE_DELAY_SECONDS`` — fake-provider latency (default 0).
- ``PCN_AI_FAKE_FAIL`` — comma-separated field, dimension or criterion ids
  the fake provider fails with a retryable error, or ``*`` for every call.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Literal

ProviderName = Literal["openrouter", "fake"]

DEFAULT_MODEL = "openai/gpt-5.6-luna"
DEFAULT_TIMEOUT_SECONDS = 600.0
DEFAULT_MAX_RETRIES = 2
MAX_RETRIES_LIMIT = 5
FAKE_FAIL_ALL = "*"


class AiConfigurationError(ValueError):
    """The AI settings are malformed or incomplete (for example, the
    OpenRouter provider without an API key)."""


@dataclass(frozen=True, slots=True)
class AiSettings:
    """The resolved AI provider settings. The API key is left out of the
    ``repr``."""

    openrouter_api_key: str | None = field(default=None, repr=False)
    openrouter_model: str = DEFAULT_MODEL
    provider: ProviderName = "openrouter"
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    provider_order: tuple[str, ...] = ()
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


def _id_list(environ: Mapping[str, str], name: str) -> tuple[str, ...]:
    raw = environ.get(name, "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def load_settings(environ: Mapping[str, str]) -> AiSettings:
    """Resolve settings from an environment mapping.

    Raises :class:`AiConfigurationError` naming the variable when a value is
    malformed.
    """
    provider = (_non_empty(environ, "PCN_AI_PROVIDER") or "openrouter").lower()
    if provider not in ("openrouter", "fake"):
        raise AiConfigurationError(
            f'PCN_AI_PROVIDER must be "openrouter" or "fake", got {provider!r}.'
        )
    return AiSettings(
        openrouter_api_key=_non_empty(environ, "OPENROUTER_API_KEY"),
        openrouter_model=_non_empty(environ, "OPENROUTER_MODEL") or DEFAULT_MODEL,
        provider="fake" if provider == "fake" else "openrouter",
        timeout_seconds=_seconds(
            environ,
            "PCN_AI_TIMEOUT_SECONDS",
            DEFAULT_TIMEOUT_SECONDS,
            allow_zero=False,
        ),
        max_retries=_retries(environ, "PCN_AI_MAX_RETRIES", DEFAULT_MAX_RETRIES),
        provider_order=_id_list(environ, "PCN_AI_PROVIDER_ORDER"),
        fake_delay_seconds=_seconds(
            environ, "PCN_AI_FAKE_DELAY_SECONDS", 0.0, allow_zero=True
        ),
        fake_fail=frozenset(_id_list(environ, "PCN_AI_FAKE_FAIL")),
    )


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
