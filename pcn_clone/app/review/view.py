"""The review page's body, as its gate renders it.

The gate (``pcn_clone.app.gate``, record type ``review``) reads the record
in the browser and passes on its identity, title and provenance
(``PROVENANCE_FIELDS``). The view then holds the session stores, the
context bar and the workspace (``pcn_clone.app.review.workspace``);
``review.js`` mounts the session from ``rv-session`` and fills the stores.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dash import dcc, html
from dash.development.base_component import Component

from pcn_clone.app.review import ids
from pcn_clone.app.review.context_bar import context_bar
from pcn_clone.app.review.workspace import workspace_view
from pcn_clone.app.routing import page_url


def review_view(review: Mapping[str, Any]) -> list[Component]:
    """The page for the review whose gate fields are ``review``: the session
    stores, the context bar, the page heading and the workspace."""
    title = str(review.get("projectTitle", ""))
    return [
        dcc.Store(
            id=ids.SESSION, data={"reviewId": str(review.get("id", "")), "title": title}
        ),
        dcc.Store(id=ids.RECORD),
        dcc.Store(id=ids.SUMMARY),
        dcc.Store(id=ids.COMPLETION),
        dcc.Store(id=ids.PART, data=None),
        context_bar(review),
        html.H1(f"Assessment — {title}", className="sr-only"),
        *workspace_view(),
    ]


def _panel(*children: Component, state: str) -> html.Div:
    return html.Div(className=f"pj-gate pj-gate-{state}", children=list(children))


def _back_link() -> dcc.Link:
    return dcc.Link(
        "← Back to Assessment", href=page_url("assess"), className="pj-gate-link"
    )


def checking_panel() -> html.Div:
    """The quiet state shown while the record is being read."""
    return _panel(
        html.P("Loading the assessment session…", className="pj-gate-quiet"),
        state="checking",
    )


def missing_panel() -> html.Div:
    """The state for a review this device does not hold."""
    return _panel(
        html.Div(
            className="card pj-gate-card",
            children=[
                html.P(
                    "This assessment session couldn’t be found.",  # noqa: RUF001
                    className="pj-gate-title",
                ),
                html.P(
                    "It may have been deleted, or the link points to a session "
                    "that doesn’t exist on this device.",  # noqa: RUF001
                    className="pj-gate-text",
                ),
                _back_link(),
            ],
        ),
        state="missing",
    )


def unreadable_panel(message: str) -> html.Div:
    """The state for a review whose stored record fails validation."""
    return _panel(
        html.Div(
            className="card pj-gate-card",
            children=[
                html.P(
                    "This assessment session can’t be opened.",  # noqa: RUF001
                    className="pj-gate-title",
                ),
                html.P(message, className="pj-gate-text"),
                _back_link(),
            ],
        ),
        state="unreadable",
    )
