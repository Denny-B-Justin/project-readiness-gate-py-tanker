"""The app starts the AI layer when it is built and closes the shared
client when its server shuts down."""

from __future__ import annotations

import pytest
from dash import Dash

from tests.app_helpers import started_client


def test_server_shutdown_closes_the_shared_client(
    app: Dash, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[bool] = []

    async def record() -> None:
        closed.append(True)

    monkeypatch.setattr("pcn_clone.ai.aclose", record)
    with started_client(app) as client:
        assert client.get("/").status_code == 200
        assert closed == []
    assert closed == [True]
