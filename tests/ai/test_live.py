"""One real model call through the Posit mAI Gateway.

The gateway only answers apps running on Posit Connect, so this runs there
(or wherever ``MAI_BASE_URL``, ``MAI_ENDPOINT`` and ``CONNECT_CONTENT_GUID``
are all set) and is skipped otherwise. The settings are read from the
environment and ``.env`` when the test runs, not from the process's cached
settings, and the provider is forced to the gateway.
"""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from pcn_clone.ai import client_from_env, evaluate_field
from pcn_clone.ai.config import MAI_PROVIDER, environment, load_settings
from tests.ai.support import default_answer

pytestmark = pytest.mark.live


def test_evaluates_project_title() -> None:
    live = load_settings(environment())
    missing = [
        name
        for name, value in (
            ("MAI_BASE_URL", live.mai_base_url),
            ("MAI_ENDPOINT", live.mai_endpoint),
            ("CONNECT_CONTENT_GUID", live.connect_content_guid),
        )
        if value is None
    ]
    if missing:
        pytest.skip(f"{', '.join(missing)} not set (run on Posit Connect)")
    client = client_from_env(dataclasses.replace(live, provider=MAI_PROVIDER))

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
