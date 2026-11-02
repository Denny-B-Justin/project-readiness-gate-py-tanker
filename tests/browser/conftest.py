"""Fixtures for the browser suite: one app server and one headless Chrome per
session, and a fresh tab with empty storage per test. Every test here carries
the ``browser`` marker and is skipped when Chrome is not installed."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.browser.harness import AppServer, Chrome, Page, find_chrome

BROWSER_DIR = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if BROWSER_DIR in item.path.parents:
            item.add_marker(pytest.mark.browser)


@pytest.fixture(scope="session")
def chrome_binary() -> str:
    binary = find_chrome()
    if binary is None:
        pytest.skip("Chrome or Chromium is not installed")
    return binary


@pytest.fixture(scope="session")
def app_server(
    chrome_binary: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[AppServer]:
    server = AppServer(tmp_path_factory.mktemp("server") / "uvicorn.log")
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def chrome(
    chrome_binary: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Chrome]:
    browser = Chrome(chrome_binary, tmp_path_factory.mktemp("chrome-profile"))
    browser.start()
    yield browser
    browser.stop()


@pytest.fixture
def page(chrome: Chrome, app_server: AppServer) -> Iterator[Page]:
    """A new tab on the app's origin with localStorage cleared. The test
    fails if the page threw an uncaught exception."""
    tab = chrome.new_page(app_server.url)
    tab.goto("/?page=projects", ready="!!window.pcnStore")
    tab.js("localStorage.clear(); sessionStorage.clear(); true")
    yield tab
    errors = tab.errors()
    tab.close()
    assert errors == [], errors
