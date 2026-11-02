"""The review pages' structure: the Assessment list renders the listing the
browser reads (rows, unreadable rows, progress, empty state, the delete
dialog), the review page is gated and renders its stores, context bar,
provenance and gate panels, the shell carries the run's stores, and the
browser scripts take every id and message from the configuration."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from dash import Dash, dcc, html
from dash.development.base_component import Component

from pcn_clone.app.form import form_view
from pcn_clone.app.review import ids
from pcn_clone.app.review.config import client_config
from pcn_clone.app.review.context_bar import PROVENANCE_FIELDS
from pcn_clone.app.review.workspace import workspace_view
from tests.app_helpers import walk

ASSETS = Path(__file__).resolve().parents[1] / "pcn_clone" / "app" / "assets"
REVIEW_JS = (ASSETS / "review.js").read_text(encoding="utf-8")
STORE_JS = (ASSETS / "review-store.js").read_text(encoding="utf-8")

REVIEW = {
    "id": "r-1",
    "projectTitle": "Upper Valley District Road",
    "templateId": "pcn_global",
    "templateLabel": "Global",
    "templateVersion": "1.5.0",
    "sourceProjectTemplateVersion": "1.5.0",
    "assessmentSetId": "pcn_global_reviewer_default",
    "assessmentSetVersion": "0.3.0",
    "mcaSetId": "pcn_global_mca_default",
    "mcaSetVersion": "0.1.0",
    "model": "fake/pcn-reviewer",
    "submitted": "10.06.2026, 17:58",
}


@pytest.fixture(scope="module")
def pages(app: Dash) -> dict[str, ModuleType]:
    return {
        name: sys.modules[f"pcn_clone.app.pages.{name}"]
        for name in ("assess", "review")
    }


def by_id(tree: Any) -> dict[str, Component]:
    return {
        json.dumps(node.id, sort_keys=True)
        if isinstance(node.id, dict)
        else node.id: node
        for node in walk(tree)
        if getattr(node, "id", None) is not None
    }


def props(component: Component) -> dict[str, Any]:
    result: dict[str, Any] = component.to_plotly_json()["props"]
    return result


def text(node: Any) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, Component):
        return text(getattr(node, "children", None))
    if isinstance(node, list | tuple):
        return "".join(text(child) for child in node)
    return ""


# --- The Assessment list -------------------------------------------------------


def test_the_list_page_lays_out_its_stores_head_table_and_dialog(
    pages: dict[str, ModuleType],
) -> None:
    tree = pages["assess"].layout()
    found = by_id(tree)

    assert found["assess-nav"].refresh == "callback-nav"
    assert found["assess-refresh"].data == 0
    assert {"assess-index", "assess-delete-target"} <= set(found)
    kickers = [n for n in walk(tree) if getattr(n, "className", None) == "page-kicker"]
    assert [text(n) for n in kickers] == ["Central PIM Agency view"]
    assert [text(n) for n in walk(tree) if isinstance(n, html.H1)] == ["Assessment"]
    assert found["assess-count"].children == "0"
    headers = [
        text(n) for n in walk(found["assess-table-wrap"]) if isinstance(n, html.Th)
    ]
    assert headers == ["No", "Project", "Progress", "Submitted", "Action"]
    assert found["assess-table-wrap"].hidden is True
    assert found["assess-empty"].hidden is True
    assert "No submissions yet" in text(found["assess-empty"])
    modal = found["assess-delete-modal"]
    assert modal.title == "Delete this assessment session?"
    assert modal.closeOnClickOutside is False
    assert text(modal).startswith("This permanently removes the session")
    assert text(found["assess-delete-confirm"]) == "Delete"


def test_nothing_shows_until_the_listing_is_read(pages: dict[str, ModuleType]) -> None:
    assert pages["assess"].render_table(None) == ([], "0", True, True)


def test_an_empty_listing_shows_the_empty_state(pages: dict[str, ModuleType]) -> None:
    listing = {"entries": [], "unreadable": [], "timeZone": "UTC"}

    assert pages["assess"].render_table(listing) == ([], "0", True, False)


def entry(review_id: str, title: str, created: str, **counts: int) -> dict[str, Any]:
    """A listing entry: the index entry of a review with an MCA set."""
    return {
        "schemaVersion": 2,
        "id": review_id,
        "createdISO": created,
        "editedISO": created,
        "projectTitle": title,
        "templateId": "pcn_global",
        "templateLabel": "Global",
        "dimensionsTotal": 5,
        "dimensionsOk": 0,
        "dimensionsError": 0,
        "criteriaTotal": 4,
        "criteriaOk": 0,
        "criteriaError": 0,
    } | counts


def test_rows_open_their_session_and_carry_progress_and_date(
    pages: dict[str, ModuleType],
) -> None:
    listing = {
        "entries": [
            entry("b-2", "Rural Clinic", "2026-10-05T23:30:00.000Z", dimensionsOk=3),
            entry(
                "a-1", "Road", "2026-08-25T10:00:00.000Z", dimensionsOk=5, criteriaOk=4
            ),
        ],
        "unreadable": [],
        "timeZone": "Asia/Tokyo",
    }

    rows, count, table_hidden, empty_hidden = pages["assess"].render_table(listing)

    assert (count, table_hidden, empty_hidden) == ("2", False, True)
    first = rows[0]
    assert first.className == "row-link"
    assert props(first)["data-href"] == "?page=review&review_id=b-2"
    (link,) = [n for n in walk(first) if isinstance(n, dcc.Link)]
    assert link.href == "?page=review&review_id=b-2"
    cells = [text(cell) for cell in first.children]
    assert cells[:4] == [
        "1",
        "Rural Clinic",
        "3/5 dimensions · 0/4 criteria",
        "10.06.2026",
    ]
    (button,) = [n for n in walk(first) if isinstance(n, html.Button)]
    assert button.id == {"type": "assess-delete", "id": "b-2"}
    assert props(button)["aria-label"] == "Delete Rural Clinic"
    assert text(rows[1].children[2]) == "All dimensions and criteria assessed"


@pytest.mark.parametrize(
    ("counts", "label"),
    [
        ({}, "0/5 dimensions · 0/4 criteria"),
        (
            {"dimensionsOk": 4, "dimensionsError": 1, "criteriaOk": 4},
            "5/5 dimensions · 4/4 criteria · 1 failed",
        ),
        (
            {"dimensionsOk": 5, "criteriaOk": 2, "criteriaError": 2},
            "5/5 dimensions · 4/4 criteria · 2 failed",
        ),
        ({"dimensionsOk": 5, "criteriaOk": 4}, "All dimensions and criteria assessed"),
    ],
)
def test_progress_reads_as_the_reference_list_does(
    pages: dict[str, ModuleType], counts: dict[str, int], label: str
) -> None:
    assert pages["assess"].progress_label(entry("r", "R", "", **counts)) == label


def test_progress_without_an_mca_set_counts_dimensions_alone(
    pages: dict[str, ModuleType],
) -> None:
    plain = {
        key: value
        for key, value in entry("r", "R", "", dimensionsOk=2).items()
        if not key.startswith("criteria")
    }

    assert pages["assess"].progress_label(plain) == "2/5 dimensions"
    assert pages["assess"].progress_label(plain | {"dimensionsOk": 5}) == (
        "All dimensions assessed"
    )


def test_unreadable_sessions_are_listed_with_their_reason(
    pages: dict[str, ModuleType],
) -> None:
    listing = {
        "entries": [],
        "unreadable": [
            {"id": "old", "reason": "Saved by a different version."},
            {"reason": "The review index could not be read."},
        ],
        "timeZone": None,
    }

    rows, count, table_hidden, empty_hidden = pages["assess"].render_table(listing)

    assert (count, table_hidden, empty_hidden) == ("0", False, True)
    assert [row.className for row in rows] == ["as-unreadable", "as-unreadable"]
    assert rows[0].children[1].colSpan == 3
    assert text(rows[0].children[1]) == (
        "Unreadable assessment sessionSaved by a different version."
    )
    (button,) = [n for n in walk(rows[0]) if isinstance(n, html.Button)]
    assert props(button)["aria-label"] == "Delete unreadable session"
    assert [n for n in walk(rows[1]) if isinstance(n, html.Button)] == []


# --- The review page -----------------------------------------------------------


def test_the_review_page_opens_on_its_gate(pages: dict[str, ModuleType]) -> None:
    found = by_id(pages["review"].layout(review_id="r-1"))

    assert found["review-gate-request"].data == {
        "type": "review",
        "id": "r-1",
        "expect": {},
        "fields": list(PROVENANCE_FIELDS),
    }
    assert text(found["review-gate-body"]) == "Loading the assessment session…"


def test_a_found_review_renders_its_stores_bar_and_workspace(
    pages: dict[str, ModuleType],
) -> None:
    view = pages["review"].render_gate({"status": "ok", "record": REVIEW})
    found = by_id(view)

    assert found[ids.SESSION].data == {
        "reviewId": "r-1",
        "title": "Upper Valley District Road",
    }
    for store in (ids.RECORD, ids.SUMMARY, ids.COMPLETION, ids.PART):
        assert isinstance(found[store], dcc.Store)
        assert getattr(found[store], "data", None) is None
    status = found[ids.STATUS]
    assert props(status)["role"] == "status"
    assert props(status)["aria-live"] == "polite"
    assert {component.id for component in workspace_view()} <= set(found)
    assert [text(n) for n in walk(view) if isinstance(n, html.H1)] == [
        "Assessment — Upper Valley District Road"
    ]


def test_the_breadcrumb_switches_between_hub_and_component(
    pages: dict[str, ModuleType],
) -> None:
    view = pages["review"].render_gate({"status": "ok", "record": REVIEW})
    found = by_id(view)
    (nav,) = [n for n in walk(view) if isinstance(n, html.Nav)]
    (link,) = [n for n in walk(nav) if isinstance(n, dcc.Link)]

    assert props(nav)["aria-label"] == "Breadcrumb"
    assert (text(link), link.href) == ("Assessment", "?page=assess")
    assert text(found[ids.CRUMB_TITLE]) == "Upper Valley District Road"
    assert props(found[ids.CRUMB_TITLE])["aria-current"] == "page"
    assert getattr(found[ids.CRUMB_TITLE], "hidden", None) is None
    assert text(found[ids.CRUMB_BACK]) == "Upper Valley District Road"
    assert found[ids.CRUMB_BACK].hidden is True
    assert found[ids.CRUMB_TAIL].hidden is True
    assert props(found[ids.CRUMB_PART])["aria-current"] == "page"


def test_the_details_popover_lists_the_provenance(
    pages: dict[str, ModuleType],
) -> None:
    view = pages["review"].render_gate({"status": "ok", "record": REVIEW})
    found = by_id(view)
    rows = [n for n in walk(view) if getattr(n, "className", None) == "rv-prov-row"]

    assert props(found[ids.DETAILS])["aria-label"] == "Assessment details"
    assert [(text(r.children[0]), text(r.children[1])) for r in rows] == [
        ("Template", "Global v1.5.0pcn_global"),
        ("Assessment criteria", "v0.3.0pcn_global_reviewer_default"),
        ("Prioritisation criteria (MCA)", "v0.1.0pcn_global_mca_default"),
        ("Model", "fake/pcn-reviewer"),
        ("Submitted", "10.06.2026, 17:58"),
    ]
    assert [
        n for n in walk(view) if getattr(n, "className", None) == "rv-prov-note"
    ] == []


def test_template_drift_adds_a_note_and_no_mca_drops_its_row(
    pages: dict[str, ModuleType],
) -> None:
    drifted = {
        key: value for key, value in REVIEW.items() if not key.startswith("mca")
    } | {"sourceProjectTemplateVersion": "1.4.0"}
    view = pages["review"].render_gate({"status": "ok", "record": drifted})
    rows = [n for n in walk(view) if getattr(n, "className", None) == "rv-prov-row"]
    notes = [n for n in walk(view) if getattr(n, "className", None) == "rv-prov-note"]

    assert [text(r.children[0]) for r in rows] == [
        "Template",
        "Assessment criteria",
        "Model",
        "Submitted",
    ]
    assert [text(n) for n in notes] == [
        "This project was created against template v1.4.0; it was assessed "
        "against v1.5.0, the version live at submission."
    ]


def test_missing_and_unreadable_reviews_get_their_panels(
    pages: dict[str, ModuleType],
) -> None:
    missing = pages["review"].render_gate({"status": "not_found"})
    unreadable = pages["review"].render_gate(
        {"status": "unreadable", "message": "This review's stored data is corrupt."}
    )

    assert text(missing).startswith("This assessment session couldn’t be found.")  # noqa: RUF001
    assert text(unreadable) == (
        "This assessment session can’t be opened."  # noqa: RUF001
        "This review's stored data is corrupt.← Back to Assessment"
    )
    for panel in (missing, unreadable):
        (link,) = [n for n in walk(panel) if isinstance(n, dcc.Link)]
        assert link.href == "?page=assess"


# --- The shell and the configuration -------------------------------------------


def test_the_shell_carries_the_run_channels(app: Dash) -> None:
    found = by_id(app.layout)

    assert found[ids.CONFIG].data == client_config()
    assert found[ids.LAUNCH].data == []
    assert found[ids.INBOX].data == []


def test_every_configured_id_is_rendered(
    app: Dash, pages: dict[str, ModuleType]
) -> None:
    views = [
        app.layout,
        pages["review"].render_gate({"status": "ok", "record": REVIEW}),
        pages["assess"].layout(),
        form_view({"id": "p-1", "title": "Road"}),
    ]
    present = {node_id for view in views for node_id in by_id(view)}
    configured = client_config()["ids"]

    assert {name for name, value in configured.items() if value not in present} == set()


def test_the_scripts_take_ids_and_messages_from_the_configuration() -> None:
    literal_ids = [
        r"getElementById\(\s*[\"'`]",
        r"\bset_?[pP]rops\(\s*[\"'`]",
        r"[\"'`](rv|pf|assess)-[\w-]+[\"'`]",
        r"[\"'`]#[\w-]",
    ]
    for script in (REVIEW_JS, STORE_JS):
        assert [p for p in literal_ids if re.search(p, script)] == []

    def strings(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [s for item in value.values() for s in strings(item)]
        if isinstance(value, list | tuple):
            return [s for item in value for s in strings(item)]
        return []

    for message in strings(client_config()["messages"]):
        for fragment in re.split(r"\{\w+\}", message):
            if len(fragment) > 12:
                assert fragment not in REVIEW_JS, message
