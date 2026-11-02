"""The application shell: the app builds around the routed page content,
every page in the table renders, the router selects pages by query string
alone, the callback graph is consistent, pages served first are complete,
page links are relative query URLs and every other URL honours the path
prefix."""

from __future__ import annotations

import ast
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from dash import Dash
from dash.development.base_component import Component

from pcn_clone.app import create_app
from pcn_clone.app.notify import TOASTS_ID
from pcn_clone.app.pages import NOT_FOUND, PAGES
from pcn_clone.app.routing import CONTENT_ID, LOCATION_ID, STATE_ID, select
from pcn_clone.app.shell import NAV_LINKS
from tests.app_helpers import find, in_fresh_process, render, walk

if TYPE_CHECKING:
    from starlette.testclient import TestClient

APP_DIR = Path(__file__).resolve().parents[1] / "pcn_clone" / "app"

PAGE_MODULES = {
    "home": "home",
    "projects": "projects",
    "project": "project",
    "assess": "assess",
    "review": "review",
    "release-notes": "release_notes",
    "methodology": "methodology",
}
"""Every page name and the module whose layout it shows."""

FIRST_REQUESTS = (
    "/?page=methodology",
    "/?page=project&project_id=some-project",
    "/nowhere?page=projects",
)
"""URLs requested first on a fresh server: a page, a page with an id, and
a page at another path (the router ignores the pathname)."""

WILDCARDS = (["ALL"], ["MATCH"], ["ALLSMALLER"])

GATED_VIEWS = {
    "project": {"id": "example", "title": "Example"},
    "review": {"id": "example", "projectTitle": "Example", "mcaSetId": "mca"},
}
"""Gated page modules and a record each renders as found: the layout a gate
renders once its check passes, which no page holds at load time."""


def classes(node: Component) -> set[str]:
    return set(str(getattr(node, "className", "") or "").split())


def to_json(component: Component) -> str:
    return json.dumps(component, default=lambda value: value.to_plotly_json())


def test_create_app_returns_the_process_app(app: Dash) -> None:
    assert create_app() is app


def test_layout_wraps_the_page_content_in_the_shell(app: Dash) -> None:
    layout = app.layout
    assert isinstance(layout, Component)
    assert type(layout).__name__ == "MantineProvider"
    assert getattr(layout, "forceColorScheme", None) == "light"

    toasts = find(layout, lambda node: getattr(node, "id", None) == TOASTS_ID)
    assert [type(node).__name__ for node in toasts] == ["NotificationContainer"]
    assert find(layout, lambda node: "suite-header" in classes(node))
    main = find(layout, lambda node: type(node).__name__ == "Main")
    assert [getattr(node, "id", None) for node in main] == [CONTENT_ID]
    assert getattr(main[0], "children", None) is None
    locations = find(layout, lambda node: type(node).__name__ == "Location")
    assert [node.id for node in locations] == [LOCATION_ID]
    assert find(layout, lambda node: getattr(node, "id", None) == STATE_ID)


def test_header_links_every_top_level_page_in_both_rows(app: Dash) -> None:
    links = find(app.layout, lambda node: "suite-link" in classes(node))
    by_row: dict[str, list[str]] = {}
    for link in links:
        props = link.to_plotly_json()["props"]
        assert props["id"]["href"] == props["href"]
        by_row.setdefault(props["id"]["row"], []).append(props["href"])
    expected = [f"?page={page}" for _, page in NAV_LINKS]
    assert by_row == {"main": expected, "compact": expected}
    assert [select(PAGES, NOT_FOUND, href)[0] for href in expected] == [
        PAGES[page] for _, page in NAV_LINKS
    ]


def test_every_page_shows_its_page_module(app: Dash) -> None:
    modules = {
        name: page.layout.__module__.rsplit(".", 1)[-1] for name, page in PAGES.items()
    }
    assert modules == PAGE_MODULES
    assert NOT_FOUND.layout.__module__ == "pcn_clone.app.pages.not_found_404"


def test_titles_and_header_sections(app: Dash) -> None:
    assert {name: (page.title, page.section) for name, page in PAGES.items()} == {
        "home": ("Readiness Gate — PIM-PAM", "home"),
        "projects": ("Projects — PIM-PAM", "projects"),
        "project": ("Concept Note — PIM-PAM", "projects"),
        "assess": ("Assessment — PIM-PAM", "assess"),
        "review": ("Assessment — PIM-PAM", "assess"),
        "release-notes": ("Release Notes — PIM-PAM", "release-notes"),
        "methodology": ("Methodology — PIM-PAM", "methodology"),
    }
    assert (NOT_FOUND.title, NOT_FOUND.section) == ("Page not found — PIM-PAM", None)


def test_every_page_layout_renders(app: Dash) -> None:
    for name, page in [*PAGES.items(), ("not found", NOT_FOUND)]:
        rendered = render(page)
        assert isinstance(rendered, Component), name
        assert to_json(rendered), name


def _route(client: TestClient, search: str) -> dict[str, Any]:
    """The router's answer for a ``location.search`` value."""
    (router,) = [
        dependency
        for dependency in client.get("/_dash-dependencies").json()
        if f"{CONTENT_ID}.children" in dependency["output"]
    ]
    response = client.post(
        "/_dash-update-component",
        json={
            "output": router["output"],
            "outputs": [
                {"id": CONTENT_ID, "property": "children"},
                {"id": STATE_ID, "property": "data"},
            ],
            "inputs": [{"id": LOCATION_ID, "property": "search", "value": search}],
            "changedPropIds": [f"{LOCATION_ID}.search"],
            "state": [],
        },
    )
    assert response.status_code == 200
    result: dict[str, Any] = response.json()["response"]
    return result


def test_the_router_reads_only_the_query_string(client: TestClient) -> None:
    (router,) = [
        dependency
        for dependency in client.get("/_dash-dependencies").json()
        if f"{CONTENT_ID}.children" in dependency["output"]
    ]
    assert router["inputs"] == [{"id": LOCATION_ID, "property": "search"}]
    assert router["state"] == []
    assert router["prevent_initial_call"] is True


@pytest.mark.parametrize("search", ["?page=nowhere", "?page=project", "?page="])
def test_an_unknown_page_or_missing_id_renders_the_not_found_page(
    client: TestClient, search: str
) -> None:
    result = _route(client, search)
    assert result[STATE_ID]["data"] == {
        "title": "Page not found — PIM-PAM",
        "nav": None,
    }
    assert "Page not found" in json.dumps(result[CONTENT_ID]["children"])


def test_a_page_with_an_id_gets_the_decoded_id_and_its_section(
    client: TestClient,
) -> None:
    result = _route(client, "?page=review&review_id=a%20b%2Fc%26d&project_id=x")
    assert result[STATE_ID]["data"] == {
        "title": "Assessment — PIM-PAM",
        "nav": "?page=assess",
    }
    content = json.dumps(result[CONTENT_ID]["children"])
    assert '"type": "review", "id": "a b/c&d"' in content


def test_no_page_shows_home(client: TestClient) -> None:
    for search in ("", "?", "?page=home"):
        result = _route(client, search)
        assert result[STATE_ID]["data"] == {
            "title": "Readiness Gate — PIM-PAM",
            "nav": "?page=home",
        }


# --- Callback graph ------------------------------------------------------------


def _split_outputs(output: str) -> list[str]:
    """The ``id.property`` outputs of one dependency (``..a.x...b.y..`` when
    there are several), each keeping its ``@hash`` when duplicates are
    allowed."""
    return output[2:-2].split("...") if output.startswith("..") else [output]


def _component_id(reference: str) -> Any:
    raw = reference.split("@", 1)[0].rsplit(".", 1)[0]
    return json.loads(raw) if raw.startswith("{") else raw


def _ids_in_source() -> list[dict[str, Any]]:
    """Pattern-matching ids the app's code builds, from every ``id={...}``
    dict literal (a variable value reads as ``None``). They stand for
    components that exist only once a callback has rendered them (a table's
    rows, a list of chips), so no layout holds them at load time."""
    ids: list[dict[str, Any]] = []
    for path in APP_DIR.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.keyword) and node.arg == "id"):
                continue
            if not isinstance(node.value, ast.Dict):
                continue
            ids.append(
                {
                    str(key.value): value.value
                    if isinstance(value, ast.Constant)
                    else None
                    for key, value in zip(
                        node.value.keys, node.value.values, strict=True
                    )
                    if isinstance(key, ast.Constant)
                }
            )
    return ids


def _fits(pattern: dict[str, Any], candidate: dict[str, Any]) -> bool:
    """A concrete or source-level id fits a pattern id: the same keys, and
    equal values except where the pattern has a wildcard or the source a
    variable."""
    return set(pattern) == set(candidate) and all(
        value in WILDCARDS or candidate[key] is None or candidate[key] == value
        for key, value in pattern.items()
    )


def test_callback_outputs_are_unique(client: TestClient) -> None:
    outputs = [
        output
        for dependency in client.get("/_dash-dependencies").json()
        for output in _split_outputs(dependency["output"])
    ]
    assert outputs
    assert sorted({output for output in outputs if outputs.count(output) > 1}) == []


def test_every_callback_id_exists(app: Dash, client: TestClient) -> None:
    gated = [
        sys.modules[f"pcn_clone.app.pages.{name}"].render_gate(
            {"status": "ok", "record": record}
        )
        for name, record in GATED_VIEWS.items()
    ]
    trees = [
        app.layout,
        *(render(page) for page in [*PAGES.values(), NOT_FOUND]),
        *gated,
    ]
    present = [
        node_id
        for tree in trees
        for node in walk(tree)
        if (node_id := getattr(node, "id", None)) is not None
    ]
    plain = {node_id for node_id in present if isinstance(node_id, str)}
    patterned = [node_id for node_id in present if isinstance(node_id, dict)]
    built = _ids_in_source()

    missing = set()
    for dependency in client.get("/_dash-dependencies").json():
        outputs = (
            [] if dependency["no_output"] else _split_outputs(dependency["output"])
        )
        references = [_component_id(output) for output in outputs] + [
            item["id"] for item in dependency["inputs"] + dependency["state"]
        ]
        for reference in references:
            if isinstance(reference, str) and reference.startswith("{"):
                reference = json.loads(reference)
            if isinstance(reference, str):
                found = reference in plain
            else:
                rendered_later = any(value in WILDCARDS for value in reference.values())
                found = any(_fits(reference, node_id) for node_id in patterned) or (
                    rendered_later
                    and any(_fits(reference, node_id) for node_id in built)
                )
            if not found:
                missing.add(json.dumps(reference, sort_keys=True))
    assert sorted(missing) == []


# --- Fresh processes -----------------------------------------------------------


@pytest.fixture(scope="module")
def first_requests() -> dict[str, Any]:
    """Each URL, requested first on its own fresh server."""
    with ThreadPoolExecutor(max_workers=len(FIRST_REQUESTS)) as pool:
        responses = pool.map(
            lambda url: in_fresh_process("first-request", url), FIRST_REQUESTS
        )
        return dict(zip(FIRST_REQUESTS, responses, strict=True))


@pytest.mark.parametrize("url", FIRST_REQUESTS)
def test_a_page_served_first_is_complete(
    first_requests: dict[str, Any], url: str
) -> None:
    response = first_requests[url]
    assert response["status"] == 200
    assert "/assets/brand.css" in response["text"]
    assert "/assets/icons.css" in response["text"]
    assert "_dashprivate_clientside_funcs" in response["text"]
    assert (
        '<meta name="description" content="AI-assisted readiness gate for Public'
        ' Investment Management Project Concept Notes.">'
    ) in response["text"]


def test_page_links_are_relative_and_other_urls_carry_the_path_prefix(
    app: Dash,
) -> None:
    rendered = in_fresh_process(
        "urls", env={"DASH_REQUESTS_PATHNAME_PREFIX": "/content/0123-abcd/"}
    )
    assert rendered["prefix"] == "/content/0123-abcd/"
    internal = [
        (source, attribute, url)
        for source, attribute, url in rendered["urls"]
        if not url.startswith(("https://", "http://"))
    ]
    page_links = [entry for entry in internal if entry[2].startswith("?")]
    others = [entry for entry in internal if not entry[2].startswith("?")]

    assert {source for source, _, _ in page_links} == {
        "shell",
        "home",
        "assess",
        "not-found",
    }
    assert {
        url: select(PAGES, NOT_FOUND, url)[0] is not NOT_FOUND
        for _, _, url in page_links
    } == dict.fromkeys(
        [
            "?page=home",
            "?page=projects",
            "?page=assess",
            "?page=release-notes",
            "?page=methodology",
            "?page=projects&new=1",
        ],
        True,
    )
    assert {"shell", "home", "methodology", "index"} <= {s for s, _, _ in others}
    assert [e for e in others if not e[2].startswith("/content/0123-abcd/")] == []
