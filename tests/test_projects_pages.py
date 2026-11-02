"""The Projects pages' structure: their layouts carry the ids, roles and
attributes their callbacks and styles rely on, links open pages by relative
query URL, and the Python callbacks turn store state into the right markup.
The behaviour in a browser is covered by ``tests/browser``."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable, Iterator
from types import ModuleType
from typing import Any

import pytest
from dash import Dash, dcc, html
from dash._callback_context import context_value
from dash._utils import AttributeDict
from dash.development.base_component import Component

from pcn_clone.app.projects_data import template_meta
from tests.app_helpers import walk

Trigger = Callable[..., None]


@pytest.fixture(scope="module")
def pages(app: Dash) -> dict[str, ModuleType]:
    """The two page modules, as the session's app imported them."""
    return {
        name: sys.modules[f"pcn_clone.app.pages.{name}"]
        for name in ("projects", "project")
    }


@pytest.fixture
def triggered() -> Iterator[Trigger]:
    """Run a callback as if one input fired: ``triggered(prop_id, value)``."""

    def set_context(prop_id: str, value: Any, outputs_list: Any = None) -> None:
        context_value.set(
            AttributeDict(
                triggered_inputs=[{"prop_id": prop_id, "value": value}],
                outputs_list=outputs_list or [],
            )
        )

    yield set_context
    context_value.set({})


def key(component_id: str | dict[str, str]) -> str:
    return (
        component_id
        if isinstance(component_id, str)
        else repr(sorted(component_id.items()))
    )


def by_id(tree: Any) -> dict[str, Component]:
    found: dict[str, Component] = {}
    for component in walk(tree):
        component_id = getattr(component, "id", None)
        if component_id is not None:
            found[key(component_id)] = component
    return found


def props(component: Component) -> dict[str, Any]:
    """A component's props as sent to the browser, wildcard attributes
    included."""
    result: dict[str, Any] = component.to_plotly_json()["props"]
    return result


def classes(component: Component) -> str:
    return getattr(component, "className", None) or ""


def record(
    project_id: str, title: str, edited: str, tags: list[str] | None = None
) -> dict[str, Any]:
    """A project as ``readIndex`` reports it: only the fields a row shows."""
    row: dict[str, Any] = {"id": project_id, "title": title, "editedISO": edited}
    if tags:
        row["tags"] = tags
    return row


INDEX = {
    "projects": [
        record(
            "b", "Bridge repair", "2026-10-05T09:00:00.000Z", ["Transport", "Rural"]
        ),
        record("a", "Aqueduct", "2026-08-25T09:00:00.000Z"),
        record("c", "clinic expansion", "2026-07-01T09:00:00.000Z", ["Health"]),
    ],
    "now": "2026-10-06T09:00:00.000Z",
    "timeZone": "UTC",
}


# --- Layouts ------------------------------------------------------------------


def test_layouts_render_without_arguments(pages: dict[str, ModuleType]) -> None:
    assert isinstance(pages["projects"].layout(), Component)
    assert isinstance(pages["project"].layout(), Component)


# --- Projects layout ------------------------------------------------------------


def test_projects_layout_stores(pages: dict[str, ModuleType]) -> None:
    ids = by_id(pages["projects"].layout())

    for store_id in (
        "projects-index",
        "projects-refresh",
        "projects-template-meta",
        "projects-sort",
        "projects-new-tags",
        "projects-delete-target",
        "projects-default-payload",
    ):
        assert isinstance(ids[store_id], dcc.Store), store_id
        assert ids[store_id].storage_type == "memory", store_id
    assert ids["projects-template-meta"].data == template_meta()
    assert "projects-href-base" not in ids
    assert ids["projects-refresh"].data == 0
    assert isinstance(ids["projects-nav"], dcc.Location)
    assert ids["projects-nav"].refresh == "callback-nav"


def test_projects_layout_head_and_actions(pages: dict[str, ModuleType]) -> None:
    tree = pages["projects"].layout()
    ids = by_id(tree)

    headings = [c for c in walk(tree) if isinstance(c, html.H1)]
    assert [h.className for h in headings] == ["page-title"]
    for button_id in ("projects-defaults-open", "projects-new-open"):
        assert isinstance(ids[button_id], html.Button)
        assert ids[button_id].type == "button"
    assert "btn-primary" in ids["projects-new-open"].className
    assert "btn-secondary" in ids["projects-defaults-open"].className
    assert ids["projects-count"].className == "count-badge"


def test_table_and_empty_state_start_hidden(pages: dict[str, ModuleType]) -> None:
    ids = by_id(pages["projects"].layout())

    assert ids["projects-table-wrap"].hidden is True
    assert ids["projects-empty"].hidden is True
    assert isinstance(ids["projects-rows"], html.Tbody)
    assert isinstance(ids["projects-empty-new"], html.Button)
    table = next(
        c for c in walk(ids["projects-table-wrap"]) if isinstance(c, html.Table)
    )
    assert props(table)["data-nav"] == "projects-nav"


def test_sortable_headers_are_buttons_with_aria_sort(
    pages: dict[str, ModuleType],
) -> None:
    ids = by_id(pages["projects"].layout())

    for col in ("name", "updated"):
        header = ids[f"projects-sort-{col}-th"]
        assert isinstance(header, html.Th)
        assert header.scope == "col"
        assert props(header)["aria-sort"] == "none"
        button = ids[f"projects-sort-{col}"]
        assert isinstance(button, html.Button)
        assert button.type == "button"
        assert button.className == "sort-btn"
        assert button.n_clicks == 0
        assert props(ids[f"projects-sort-{col}-arrow"])["aria-hidden"] == "true"


def test_create_dialog_structure(pages: dict[str, ModuleType]) -> None:
    ids = by_id(pages["projects"].layout())

    modal = ids["projects-new-modal"]
    assert modal.opened is False
    assert isinstance(modal.title, str)
    assert modal.closeButtonProps == {"aria-label": "Close"}
    assert modal.children[0] is ids["projects-new-lede"]
    assert ids["projects-new-lede"].className == "pj-dialog-lede"
    assert isinstance(ids["projects-new-title"], dcc.Input)
    assert isinstance(ids["projects-new-tag-input"], dcc.Input)
    labels = {
        c.htmlFor
        for c in walk(modal)
        if isinstance(c, html.Label) and getattr(c, "htmlFor", None)
    }
    assert labels == {"projects-new-title", "projects-new-tag-input"}
    assert ids["projects-new-create"].disabled is True
    assert ids["projects-new-cancel"].type == "button"
    suggestions = [k for k in ids if "projects-tag-suggest" in k]
    assert len(suggestions) == len(pages["projects"].SUGGESTED_TAGS)


def test_create_dialog_opens_on_new_query(pages: dict[str, ModuleType]) -> None:
    ids = by_id(pages["projects"].layout(new="1"))
    assert ids["projects-new-modal"].opened is True


def test_defaults_dialog_structure(pages: dict[str, ModuleType]) -> None:
    ids = by_id(pages["projects"].layout())

    modal = ids["projects-defaults-modal"]
    assert isinstance(modal.title, str)
    assert modal.closeButtonProps == {"aria-label": "Close"}
    assert modal.children[0] is ids["projects-defaults-lede"]
    fieldset = ids["projects-defaults-list"]
    assert isinstance(fieldset, html.Fieldset)
    assert fieldset.disabled is False
    assert props(fieldset)["aria-busy"] == "false"
    card = ids[
        key({"type": "projects-default-card", "id": "upper_valley_district_road"})
    ]
    assert isinstance(card, html.Button)
    assert card in list(walk(fieldset))
    badge = next(c for c in walk(card) if "pj-default-badge" in classes(c))
    assert badge.children == "PCN v1 — Global"
    assert ids["projects-defaults-cancel"].type == "button"


def test_delete_dialog_structure(pages: dict[str, ModuleType]) -> None:
    ids = by_id(pages["projects"].layout())

    modal = ids["projects-delete-modal"]
    assert modal.closeOnClickOutside is False
    assert modal.withCloseButton is False
    assert isinstance(modal.title, str)
    assert "btn-destructive" in ids["projects-delete-confirm"].className
    assert "btn-secondary" in ids["projects-delete-cancel"].className


# --- Python callbacks -------------------------------------------------------------


def test_render_table_before_the_index_is_read(pages: dict[str, ModuleType]) -> None:
    rows, count, table_hidden, empty_hidden, *_ = pages["projects"].render_table(
        None, None
    )
    assert (rows, count, table_hidden, empty_hidden) == ([], "0", True, True)


def test_render_table_with_no_projects(pages: dict[str, ModuleType]) -> None:
    index = {"projects": [], "now": INDEX["now"], "timeZone": "UTC"}
    rows, count, table_hidden, empty_hidden, *_ = pages["projects"].render_table(
        index, None
    )
    assert (rows, count, table_hidden, empty_hidden) == ([], "0", True, False)


def test_render_table_rows(pages: dict[str, ModuleType]) -> None:
    rows, count, table_hidden, empty_hidden, *headers = pages["projects"].render_table(
        INDEX, None
    )

    assert count == "3"
    assert (table_hidden, empty_hidden) == (False, True)
    assert [props(row)["data-href"] for row in rows] == [
        "?page=project&project_id=b",
        "?page=project&project_id=a",
        "?page=project&project_id=c",
    ]
    assert all(row.className == "row-link" for row in rows)
    first = rows[0]
    link = next(c for c in walk(first) if isinstance(c, dcc.Link))
    assert (link.href, link.className) == ("?page=project&project_id=b", "cell-title")
    tags = [c.children for c in walk(first) if "pj-tag" in classes(c)]
    assert tags == ["Transport", "Rural"]
    assert [c.children for c in walk(first) if classes(c) == "cell-strong"] == [
        "10.05.2026"
    ]
    assert [c.children for c in walk(first) if classes(c) == "cell-sub"] == [
        "1 day ago"
    ]
    button = by_id(first)[key({"type": "projects-delete", "id": "b"})]
    assert props(button)["aria-label"] == "Delete Bridge repair"
    assert headers == [
        "sortable",
        "none",
        "↕",
        "sortable pj-col-updated active",
        "descending",
        "↓",
    ]


def test_render_table_sorts_by_name(pages: dict[str, ModuleType]) -> None:
    rows, _, _, _, *headers = pages["projects"].render_table(
        INDEX, {"col": "name", "dir": "asc"}
    )

    assert [props(row)["data-href"] for row in rows] == [
        "?page=project&project_id=a",
        "?page=project&project_id=b",
        "?page=project&project_id=c",
    ]
    assert headers[:3] == ["sortable active", "ascending", "↑"]
    assert headers[3:5] == ["sortable pj-col-updated", "none"]


def test_a_row_link_encodes_the_project_id(pages: dict[str, ModuleType]) -> None:
    index = {**INDEX, "projects": [record("a b/c&d", "Odd", INDEX["now"])]}
    (row,), *_ = pages["projects"].render_table(index, None)

    href = "?page=project&project_id=a+b%2Fc%26d"
    assert props(row)["data-href"] == href
    assert [c.href for c in walk(row) if isinstance(c, dcc.Link)] == [href]


def test_render_tags(pages: dict[str, ModuleType], triggered: Trigger) -> None:
    module = pages["projects"]
    outputs = [
        {"id": "projects-new-tag-chips", "property": "children"},
        [
            {"id": {"type": "projects-tag-suggest", "tag": tag}, "property": "hidden"}
            for tag in module.SUGGESTED_TAGS
        ],
        {"id": "projects-new-suggestions", "property": "hidden"},
        {"id": "projects-new-tag-input", "property": "placeholder"},
    ]
    triggered("projects-new-tags.data", ["Health", "Mine"], outputs)

    chips, hidden, row_hidden, placeholder = module.render_tags(["Health", "Mine"])

    assert [chip.children[0] for chip in chips] == ["Health", "Mine"]
    remove = chips[0].children[1]
    assert remove.id == {"type": "projects-tag-remove", "tag": "Health"}
    assert props(remove)["aria-label"] == "Remove Health"
    assert hidden == [tag == "Health" for tag in module.SUGGESTED_TAGS]
    assert row_hidden is False
    assert placeholder == "Add another…"

    _, all_hidden, all_row_hidden, _ = module.render_tags(list(module.SUGGESTED_TAGS))
    assert all(all_hidden) and all_row_hidden is True
    assert module.render_tags([])[3] == "Type a tag and press Enter…"


def test_load_default_returns_meta_and_values(
    pages: dict[str, ModuleType], triggered: Trigger
) -> None:
    triggered(
        '{"id":"upper_valley_district_road","type":"projects-default-card"}.n_clicks',
        1,
    )

    payload = asyncio.run(pages["projects"].load_default([1]))

    assert payload["ok"] is True
    assert set(payload) == {"ok", "defaultId", "meta", "values", "nonce"}
    assert payload["meta"]["tags"] == ["Transport"]
    assert len(payload["values"]) == 19


def test_load_default_rejects_an_unknown_id(
    pages: dict[str, ModuleType], triggered: Trigger
) -> None:
    triggered('{"id":"nope","type":"projects-default-card"}.n_clicks', 1)

    payload = asyncio.run(pages["projects"].load_default([1]))

    assert payload["ok"] is False
    assert payload["errorMessage"]


# --- Project gate -------------------------------------------------------------------


def test_project_layout_is_a_gate_opening_in_checking(
    pages: dict[str, ModuleType],
) -> None:
    ids = by_id(pages["project"].layout(project_id="abc"))

    assert ids["project-gate-request"].data == {
        "type": "project",
        "id": "abc",
        "expect": {"templateId": "pcn_global"},
        "fields": ["id", "title"],
    }
    assert isinstance(ids["project-gate"], dcc.Store)
    body = ids["project-gate-body"]
    assert any("pj-gate-checking" in classes(c) for c in walk(body))


def test_render_gate_states(pages: dict[str, ModuleType]) -> None:
    render = pages["project"].render_gate

    assert any("pj-gate-checking" in classes(c) for c in walk(render(None)))

    missing = render({"status": "not_found"})
    assert any("pj-gate-missing" in classes(c) for c in walk(missing))
    assert [c.href for c in walk(missing) if isinstance(c, dcc.Link)] == [
        "?page=projects"
    ]

    found = render({"status": "ok", "record": {"id": "p-1", "title": "Aqueduct"}})
    nav = next(c for c in walk(found) if isinstance(c, html.Nav))
    assert props(nav)["aria-label"] == "Breadcrumb"
    assert [c.href for c in walk(nav) if isinstance(c, dcc.Link)] == ["?page=projects"]
    current = next(c for c in walk(nav) if classes(c) == "pf-crumb-title")
    assert current.children == "Aqueduct"
    assert props(current)["aria-current"] == "page"
    project = next(c for c in walk(found) if getattr(c, "id", None) == "pf-project")
    assert project.data == {"id": "p-1", "title": "Aqueduct"}
