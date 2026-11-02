"""One real model call through OpenRouter (needs ``OPENROUTER_API_KEY``).

The settings are read from the environment and ``.env`` when the test runs,
not from the process's cached settings, and the provider is forced to
OpenRouter.
"""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from pcn_clone.ai import client_from_env, evaluate_field
from pcn_clone.ai.config import environment, load_settings
from tests.ai.support import default_answer

pytestmark = pytest.mark.live


def test_evaluates_project_title() -> None:
    live = load_settings(environment())
    if live.openrouter_api_key is None:
        pytest.skip("OPENROUTER_API_KEY is not set")
    client = client_from_env(dataclasses.replace(live, provider="openrouter"))

    async def evaluate() -> None:
        response = await evaluate_field(
            "investment_identification",
            "project_title",
            default_answer("project_title"),
            client=client,
        )
        await client.aclose()
        assert response.ok, response.error_message
        assert response.result is not None
        assert response.result.verdict in ("fail", "notClear", "pass")
        assert response.result.reasoning.strip()
        assert response.model

    asyncio.run(evaluate())
