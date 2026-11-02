"""The workspace's views and card frames, drawn once per record load.

:func:`workspace_view` is what the review page mounts: the workspace's
stores and an empty root. When the record arrives, ``assets/review-ui.js``
publishes its frozen structure (dimension definitions and the MCA matrix)
to ``rv-ws-shape`` and :func:`workspace_body` draws every view from it: the
hub (the two component cards and the memo panel) and each component's open
view (back row, header and card frames). Only one view shows at a time,
chosen by review-ui.js from the opened component. The regions that show
live state are filled by :mod:`pcn_clone.app.review.workspace.render` as
states change.
"""

from __future__ import annotations

from collections.abc import Sequence

from dash import dcc, html
from dash.development.base_component import Component

from pcn_clone.app.a11y import data
from pcn_clone.app.review.workspace.config import client_config
from pcn_clone.app.review.workspace.finding_card import finding_card
from pcn_clone.app.review.workspace.hub import (
    FINDINGS_TITLE,
    SCORES_TITLE,
    back_row,
    findings_blurb,
    hub_card,
    scores_blurb,
    view_header,
)
from pcn_clone.app.review.workspace.ids import (
    CONFIG,
    EDITING,
    PROGRESS,
    REGION,
    ROOT,
    SHAPE,
    ViewKey,
)
from pcn_clone.app.review.workspace.memo_panel import memo_panel
from pcn_clone.app.review.workspace.records import JsonObject, as_list, as_object
from pcn_clone.app.review.workspace.score_card import score_card


def workspace_view() -> list[Component]:
    """The workspace as the review page mounts it: its configuration and
    render stores and the root its views are drawn into."""
    return [
        dcc.Store(id=CONFIG, data=client_config()),
        dcc.Store(id=SHAPE, storage_type="memory"),
        dcc.Store(id=PROGRESS, storage_type="memory"),
        dcc.Store(id=EDITING, storage_type="memory"),
        html.Div(id=ROOT, className="rv-root"),
    ]


def _view(
    view: ViewKey,
    title: str,
    blurb: str,
    cards: Sequence[Component],
) -> html.Div:
    return html.Div(
        className=f"rv-view rv-view-{view}",
        children=[
            back_row(view),
            view_header(view, title, blurb),
            html.Div(list(cards), className="rv-cards"),
        ],
    )


def workspace_body(shape: JsonObject) -> html.Div:
    """Every view of the workspace for the record structure ``shape``:
    ``{key, dimensionDefs, mca: {matrix} | None}``."""
    definitions = [as_object(d) for d in as_list(shape.get("dimensionDefs"))]
    matrix = as_object(as_object(shape.get("mca")).get("matrix"))
    hub_slots: list[Component] = [
        html.Div(hub_card("findings", FINDINGS_TITLE), className="rv-hub-slot")
    ]
    views: list[Component] = [
        _view(
            "findings",
            FINDINGS_TITLE,
            findings_blurb(len(definitions)),
            [finding_card(definition) for definition in definitions],
        )
    ]
    if matrix:
        criteria = [as_object(c) for c in as_list(matrix.get("criteria"))]
        scale = [as_object(entry) for entry in as_list(matrix.get("scale"))]
        hub_slots.append(
            html.Div(hub_card("scores", SCORES_TITLE), className="rv-hub-slot")
        )
        views.append(
            _view(
                "scores",
                SCORES_TITLE,
                scores_blurb(len(criteria), scale),
                [
                    *(score_card(criterion) for criterion in criteria),
                    html.Div(id={"type": REGION, "view": "scores", "slot": "summary"}),
                ],
            )
        )
    hub = html.Div(
        className="rv-view rv-view-hub",
        children=[
            html.Div(
                [*hub_slots, html.Div(memo_panel(), className="rv-hub-wide")],
                className="rv-hub-grid",
            ),
        ],
    )
    return html.Div(
        [hub, *views],
        className="rv-workspace",
        **data(rv_shape=str(shape.get("key", ""))),
    )
