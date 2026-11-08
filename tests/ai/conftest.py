"""Fixtures for the AI-layer tests."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from pcn_clone.ai import reset_settings

AI_VARIABLE_PREFIXES = ("PCN_AI_", "MAI_", "CONNECT_CONTENT_GUID")

SetAiEnvironment = Callable[..., None]


@pytest.fixture
def ai_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[SetAiEnvironment]:
    """A setter for the AI environment: it clears every ``PCN_AI_*`` and
    ``MAI_*`` variable and ``CONNECT_CONTENT_GUID``, sets the given ones,
    moves to a directory without a ``.env`` file and resets the cached
    settings. The settings are reset again afterwards."""

    def set_environment(**variables: str) -> None:
        for name in list(os.environ):
            if name.startswith(AI_VARIABLE_PREFIXES):
                monkeypatch.delenv(name)
        for name, value in variables.items():
            monkeypatch.setenv(name, value)
        monkeypatch.chdir(tmp_path)
        reset_settings()

    yield set_environment
    reset_settings()
