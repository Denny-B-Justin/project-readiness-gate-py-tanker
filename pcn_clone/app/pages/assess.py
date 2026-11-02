"""``?page=assess``: the Central PIM Agency's submitted Concept Notes, most
recently active first.

The review store lives in the browser (``assets/review-store.js``). A
clientside callback reads the listing into the ``assess-index`` memory store
on load, after every deletion and whenever a review changes while the list
is open, as a run's results land (each bumps ``assess-refresh``); Python
renders the table from that copy. A session that cannot be read is listed as
unreadable, never left out, and can only be deleted. A row opens its
session; deleting asks for confirmation first.
"""

from __future__ import annotations

from typing import Any

import dash_mantine_components as dmc
from dash import (
    ALL,
    ClientsideFunction,
    Input,
    Output,
    State,
    callback,
    clientside_callback,
    dcc,
    html,
)
from dash.development.base_component import Component

from pcn_clone.app.a11y import aria
from pcn_clone.app.icons import icon
from pcn_clone.app.projects_data import format_date, resolve_timezone
from pcn_clone.app.review.ids import CONFIG, LIST_REFRESH
from pcn_clone.app.routing import page_url

LEDE = (
    "Concept Notes submitted for assessment, most recently active first. Your "
    "AI powered review workspace."
)

DELETE_TITLE = "Delete this assessment session?"
DELETE_TEXT = (
    "This permanently removes the session — its findings and any reviewer "
    "notes. The submitted Concept Note itself is not affected. This can’t be "  # noqa: RUF001
    "undone."
)


def progress_label(entry: dict[str, Any]) -> str:
    """How far a session's run has come, from its index counts: ``"5/5
    dimensions · 3/4 criteria · 1 failed"`` (the criteria only for a review
    with an MCA set, the failures only when there are any), or "All
    dimensions and criteria assessed" once every item is in."""

    def count(key: str) -> int:
        value = entry.get(key, 0)
        return value if isinstance(value, int) else 0

    has_mca = "criteriaTotal" in entry
    all_in = count("dimensionsOk") == count("dimensionsTotal") and (
        not has_mca or count("criteriaOk") == count("criteriaTotal")
    )
    if all_in:
        return (
            "All dimensions and criteria assessed"
            if has_mca
            else "All dimensions assessed"
        )
    parts = [
        f"{count('dimensionsOk') + count('dimensionsError')}/"
        f"{count('dimensionsTotal')} dimensions"
    ]
    if has_mca:
        parts.append(
            f"{count('criteriaOk') + count('criteriaError')}/"
            f"{count('criteriaTotal')} criteria"
        )
    failed = count("dimensionsError") + count("criteriaError")
    if failed:
        parts.append(f"{failed} failed")
    return " · ".join(parts)


# --- Layout pieces -------------------------------------------------------------


def delete_button(review_id: str, name: str) -> html.Button:
    """The trash button that asks to delete one session."""
    return html.Button(
        icon("trash"),
        id={"type": "assess-delete", "id": review_id},
        type="button",
        className="icon-btn icon-btn-ghost",
        **aria(label=f"Delete {name}"),
    )


def table() -> html.Div:
    """The sessions table; rows are rendered from the listing."""
    table_attributes: dict[str, Any] = {"data-nav": "assess-nav"}
    return html.Div(
        id="assess-table-wrap",
        className="table-card",
        hidden=True,
        children=html.Table(
            className="data-table as-table",
            **table_attributes,
            children=[
                html.Thead(
                    html.Tr(
                        [
                            html.Th("No", scope="col", className="col-no"),
                            html.Th("Project", scope="col"),
                            html.Th(
                                "Progress", scope="col", className="as-col-progress"
                            ),
                            html.Th(
                                "Submitted", scope="col", className="as-col-submitted"
                            ),
                            html.Th("Action", scope="col", className="col-action"),
                        ]
                    )
                ),
                html.Tbody(id="assess-rows"),
            ],
        ),
    )


def empty_state() -> html.Div:
    """The panel shown while no Concept Note has been submitted."""
    return html.Div(
        id="assess-empty",
        className="empty-state",
        hidden=True,
        children=[
            html.Span(icon("doc-check", 26), className="empty-state-icon"),
            html.P("No submissions yet", className="empty-state-title"),
            html.P(
                "When a Concept Note is submitted from its editor, its assessment"
                " session appears here for review.",
                className="empty-state-text",
            ),
            html.Div(
                dcc.Link(
                    "Go to Projects →",
                    href=page_url("projects"),
                    className="empty-state-link",
                )
            ),
        ],
    )


def delete_dialog() -> dmc.Modal:
    """The delete confirmation. Overlay clicks do not dismiss it; Cancel,
    Delete and Escape do."""
    return dmc.Modal(
        id="assess-delete-modal",
        opened=False,
        size=420,
        withCloseButton=False,
        closeOnClickOutside=False,
        title=DELETE_TITLE,
        classNames={
            "content": "pj-dialog pj-dialog-delete",
            "header": "pj-dialog-header pj-alert-header",
            "title": "pj-alert-title",
            "body": "pj-dialog-body",
        },
        children=[
            html.P(DELETE_TEXT, className="pj-alert-text"),
            html.Div(
                className="pj-dialog-foot",
                children=[
                    html.Button(
                        "Cancel",
                        id="assess-delete-cancel",
                        type="button",
                        className="btn btn-secondary btn-md",
                    ),
                    html.Button(
                        "Delete",
                        id="assess-delete-confirm",
                        type="button",
                        className="btn btn-destructive btn-md",
                    ),
                ],
            ),
        ],
    )


def layout() -> Component:
    """The Assessment page; the list fills in once the browser has read it."""
    return html.Div(
        className="page",
        children=[
            dcc.Location(id="assess-nav", refresh="callback-nav"),
            dcc.Store(id="assess-index", storage_type="memory"),
            dcc.Store(id=LIST_REFRESH, storage_type="memory", data=0),
            dcc.Store(id="assess-delete-target", storage_type="memory"),
            html.Div(
                className="page-head",
                children=[
                    html.Span("Central PIM Agency view", className="page-kicker"),
                    html.H1("Assessment", className="page-title"),
                    html.P(LEDE, className="page-lede"),
                ],
            ),
            html.Div(
                className="section-label",
                children=[
                    html.Span("Submitted Concept Notes"),
                    html.Span("0", id="assess-count", className="count-badge"),
                ],
            ),
            table(),
            empty_state(),
            delete_dialog(),
        ],
    )


# --- Rendering -----------------------------------------------------------------


def review_row(entry: dict[str, Any], number: int, time_zone: Any) -> html.Tr:
    """One session's row; the whole row opens the session."""
    review_id = str(entry["id"])
    title = str(entry.get("projectTitle", ""))
    href = page_url("review", review_id=review_id)
    row_attributes: dict[str, Any] = {"data-href": href}
    return html.Tr(
        className="row-link",
        **row_attributes,
        children=[
            html.Td(str(number), className="col-no"),
            html.Td(dcc.Link(title, href=href, className="cell-title")),
            html.Td(progress_label(entry), className="as-progress"),
            html.Td(
                format_date(entry.get("createdISO"), resolve_timezone(time_zone)),
                className="cell-strong",
            ),
            html.Td(delete_button(review_id, title), className="col-action"),
        ],
    )


def unreadable_row(entry: dict[str, Any]) -> html.Tr:
    """A session that cannot be opened: the reason, and delete when the
    entry carries an id."""
    review_id = entry.get("id")
    return html.Tr(
        className="as-unreadable",
        children=[
            html.Td(icon("alert-triangle"), className="col-no"),
            html.Td(
                colSpan=3,
                children=[
                    html.Span(
                        "Unreadable assessment session", className="as-unreadable-title"
                    ),
                    html.Span(
                        str(entry.get("reason", "")), className="as-unreadable-reason"
                    ),
                ],
            ),
            html.Td(
                delete_button(review_id, "unreadable session")
                if isinstance(review_id, str) and review_id
                else None,
                className="col-action",
            ),
        ],
    )


@callback(
    Output("assess-rows", "children"),
    Output("assess-count", "children"),
    Output("assess-table-wrap", "hidden"),
    Output("assess-empty", "hidden"),
    Input("assess-index", "data"),
)
def render_table(listing: dict[str, Any] | None) -> tuple[Any, ...]:
    """The rows, count and visibility for the listing. Until it has been
    read, neither the table nor the empty state shows."""
    if not listing:
        return [], "0", True, True
    entries = list(listing.get("entries") or [])
    rows: list[Component] = [
        review_row(entry, number, listing.get("timeZone"))
        for number, entry in enumerate(entries, start=1)
    ]
    rows += [unreadable_row(entry) for entry in listing.get("unreadable") or []]
    return rows, str(len(entries)), not rows, bool(rows)


clientside_callback(
    ClientsideFunction(namespace="pcnReview", function_name="readList"),
    Output("assess-index", "data"),
    Input(LIST_REFRESH, "data"),
)

clientside_callback(
    ClientsideFunction(namespace="pcnReview", function_name="askDelete"),
    Output("assess-delete-target", "data"),
    Output("assess-delete-modal", "opened"),
    Input({"type": "assess-delete", "id": ALL}, "n_clicks"),
    State("assess-index", "data"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="pcnReview", function_name="closeDialog"),
    Output("assess-delete-modal", "opened", allow_duplicate=True),
    Input("assess-delete-cancel", "n_clicks"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="pcnReview", function_name="deleteReview"),
    Output(LIST_REFRESH, "data"),
    Output("assess-delete-modal", "opened", allow_duplicate=True),
    Input("assess-delete-confirm", "n_clicks"),
    State("assess-delete-target", "data"),
    State(CONFIG, "data"),
    prevent_initial_call=True,
)
