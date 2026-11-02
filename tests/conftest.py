"""Shared fixtures for the web application tests.

A process holds one Dash app (``create_app`` returns the same instance on
every call), so every test that needs the app or its pages uses the
session-wide ``app`` and ``client`` here rather than building its own
``Dash``: a second app would re-register every page callback. Checks that
need a server nobody has requested yet run in a fresh process instead (see
``tests.app_helpers.in_fresh_process``).

The suite runs offline against the fake AI provider. ``PCN_AI_PROVIDER`` is
set when this module is imported, before any fixture builds the app and
before a fresh process or app server copies the environment; the cached AI
settings are reset to read it. ``OPENROUTER_API_KEY`` is left alone: the
live test uses it, and skips itself without it.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest
from dash import Dash

from pcn_clone.ai import reset_settings
from pcn_clone.app import create_app
from tests.app_helpers import started_client

if TYPE_CHECKING:
    from starlette.testclient import TestClient

os.environ["PCN_AI_PROVIDER"] = "fake"
reset_settings()


@pytest.fixture(scope="session")
def app() -> Dash:
    """The application, with every page imported and registered."""
    return create_app()


@pytest.fixture(scope="session")
def client(app: Dash) -> Iterator[TestClient]:
    """An HTTP client on the running application (startup has run)."""
    with started_client(app) as client:
        yield client
