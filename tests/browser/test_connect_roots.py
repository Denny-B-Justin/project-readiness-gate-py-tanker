"""The app as Posit Connect serves it (``tests/browser/connect_like.py``):
Dash's prefix is the content URL, and the same app is opened at the content
URL, at a vanity URL and at the vanity URL without its trailing slash.
Only page documents are requested at the visitor's root; assets and
callbacks go to the content URL from every root (the scaffold serves no
deeper vanity paths), a review run completes over the WebSocket (which the
scaffold serves only there), and navigating never leaves the root the
visitor arrived at."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

from pcn_clone.app.routing import page_url
from tests.browser.connect_like import CONTENT_ROOT, VANITY_ROOT
from tests.browser.form_steps import READY, seed_default
from tests.browser.harness import AppServer, Chrome, Page, url_param
from tests.browser.projects_steps import LIST_READY
from tests.browser.review_steps import ON_REVIEW_URL, states, stored, wait_idle

ROOTS = (CONTENT_ROOT, VANITY_ROOT, VANITY_ROOT.rstrip("/"))

ON_PROJECT_PAGE = "!!document.querySelector('.pf-crumb-title')"


@pytest.fixture(scope="module")
def connect_server(
    chrome_binary: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[AppServer]:
    server = AppServer(
        tmp_path_factory.mktemp("connect") / "uvicorn.log",
        {"DASH_REQUESTS_PATHNAME_PREFIX": CONTENT_ROOT},
        asgi="tests.browser.connect_like:server",
        ready_path=CONTENT_ROOT,
    )
    server.start()
    yield server
    server.stop()


@pytest.fixture
def tab(chrome: Chrome, connect_server: AppServer) -> Iterator[Page]:
    """A fresh tab with empty storage that records network activity; the
    test fails on any console error, uncaught exception, failed load or
    error response."""
    page = chrome.new_page(connect_server.url)
    page.send("Network.enable")
    page.goto(CONTENT_ROOT + "?page=projects", ready="!!window.pcnStore")
    page.js("localStorage.clear(); sessionStorage.clear(); true")
    yield page
    failed = [
        event["params"]
        for event in page.events
        if (
            event["method"] == "Network.loadingFailed"
            and not event["params"].get("canceled")
        )
        or (
            event["method"] == "Network.responseReceived"
            and event["params"]["response"]["status"] >= 400
        )
    ]
    errors = page.errors()
    page.close()
    assert failed == []
    assert errors == [], errors


def at(root: str, search: str) -> str:
    """An expression true while the address is ``root`` with ``search``."""
    return (
        f"location.pathname === {json.dumps(root)}"
        f" && location.search === {json.dumps(search)}"
    )


def requests(page: Page, since: int) -> list[tuple[str, str]]:
    """``(resource type, URL)`` of every request the tab sent from event
    index ``since`` on."""
    return [
        (event["params"].get("type", ""), event["params"]["request"]["url"])
        for event in page.events[since:]
        if event["method"] == "Network.requestWillBeSent"
    ]


@pytest.mark.parametrize("root", ROOTS)
def test_navigation_keeps_the_root(tab: Page, root: str) -> None:
    since = len(tab.events)
    tab.goto(root + "?page=projects", ready=LIST_READY)
    assert tab.js("document.title") == "Projects — PIM-PAM"

    tab.click("#projects-new-open")
    tab.wait_for(
        "!!document.querySelector('.mantine-Modal-content #projects-new-title')"
    )
    tab.type("#projects-new-title", "Bridge Repair")
    tab.wait_for("!document.getElementById('projects-new-create').disabled")
    tab.click("#projects-new-create")
    tab.wait_for(f"location.pathname === {json.dumps(root)} && {ON_PROJECT_PAGE}")
    project = page_url("project", project_id=tab.js(url_param("project_id")))
    assert tab.js("location.search") == project

    tab.click(".pf-crumb-link")
    tab.wait_for(at(root, "?page=projects"))
    tab.wait_for(LIST_READY)
    tab.click("#projects-rows tr:first-child .cell-strong")
    tab.wait_for(at(root, project))
    tab.wait_for(ON_PROJECT_PAGE)
    tab.js("history.back()")
    tab.wait_for(at(root, "?page=projects"))
    tab.wait_for(LIST_READY)

    for label, search, title in [
        ("Assessment", "?page=assess", "Assessment — PIM-PAM"),
        ("Home", "?page=home", "Readiness Gate — PIM-PAM"),
    ]:
        tab.click(f".suite-nav a.suite-link[href={json.dumps(search)}]")
        tab.wait_for(at(root, search))
        tab.wait_for(f"document.title === {json.dumps(title)}")
        tab.wait_for(
            "document.querySelector('.suite-nav [aria-current=page]').textContent"
            f" === {json.dumps(label)}"
        )
    tab.reload(ready="!!document.querySelector('.home')")
    assert tab.js("location.pathname") == root

    origin = tab.js("location.origin")
    sent = [(kind, url) for kind, url in requests(tab, since) if url.startswith(origin)]
    documents = [url for kind, url in sent if kind == "Document"]
    others = [url for kind, url in sent if kind != "Document"]
    assert documents
    assert [
        url for url in documents if url.removeprefix(origin).split("?", 1)[0] != root
    ] == []
    assert any(url.startswith(origin + CONTENT_ROOT + "assets/") for url in others)
    assert any(url.startswith(origin + CONTENT_ROOT + "_dash-") for url in others)
    assert [url for url in others if not url.startswith(origin + CONTENT_ROOT)] == []


@pytest.mark.parametrize("root", [CONTENT_ROOT, VANITY_ROOT])
def test_a_review_runs_over_the_content_url_websocket(tab: Page, root: str) -> None:
    """The scaffold accepts WebSockets only under the content URL, so the
    run completing shows the socket used Dash's prefix."""
    project_id = seed_default(tab)
    tab.goto(root + page_url("project", project_id=project_id), ready=READY)
    tab.click("#pf-submit")
    tab.wait_for(f"location.pathname === {json.dumps(root)} && {ON_REVIEW_URL}")
    review_id = str(tab.js(url_param("review_id")))
    wait_idle(tab, review_id)

    assert {status for status, _ in states(stored(tab, review_id)).values()} == {"ok"}
