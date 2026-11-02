"""The workspace's callbacks, registered once when this package is imported.

Clientside (``dash_clientside.pcnReviewUi`` in ``assets/review-ui.js``):

- ``sessionChanged``: the session's record, summary state or completion
  changed. The script publishes the record's frozen structure to
  ``rv-ws-shape`` unless the store already holds it, and a progress
  snapshot to ``rv-ws-progress`` once the cards are in the page.
- ``viewChanged``: the opened component changed; the script shows its view
  (or the hub) and scrolls to the top.

Server:

- ``render_workspace`` draws every view from ``rv-ws-shape``, once per
  record load.
- ``render_progress`` redraws, from ``rv-ws-progress``, the card regions
  the snapshot names, every component region and the memo panel's regions.
  Every other region is left as it is.
- ``render_editors`` draws, from ``rv-ws-editing``, the editors the
  reviewer has just opened and clears those just closed; an open editor is
  never redrawn.
"""

from __future__ import annotations

from typing import Any

from dash import (
    ALL,
    ClientsideFunction,
    Input,
    Output,
    State,
    callback,
    clientside_callback,
    ctx,
    no_update,
)

from pcn_clone.app.review.workspace.ids import (
    COMPLETION,
    CONFIG,
    EDITING,
    EDITOR,
    ITEM_FOOT,
    ITEM_TOP,
    MEMO,
    PROGRESS,
    RECORD,
    REGION,
    ROOT,
    SHAPE,
    SUMMARY_STATE,
    VIEW,
)
from pcn_clone.app.review.workspace.layout import workspace_body
from pcn_clone.app.review.workspace.records import as_object
from pcn_clone.app.review.workspace.render import (
    editor_regions,
    item_regions,
    memo_regions,
    read_progress,
    view_regions,
)


@callback(Output(ROOT, "children"), Input(SHAPE, "data"), prevent_initial_call=True)
def render_workspace(shape: Any) -> Any:
    """Every view of the workspace for the published record structure."""
    if not as_object(shape).get("key"):
        return no_update
    return workspace_body(as_object(shape))


@callback(
    Output({"type": ITEM_TOP, "kind": ALL, "item": ALL}, "children"),
    Output({"type": ITEM_FOOT, "kind": ALL, "item": ALL}, "children"),
    Output({"type": REGION, "view": ALL, "slot": ALL}, "children"),
    Output({"type": MEMO, "slot": ALL}, "children"),
    Input(PROGRESS, "data"),
    prevent_initial_call=True,
)
def render_progress(
    payload: Any,
) -> tuple[list[Any], list[Any], list[Any], list[Any]]:
    """The live regions for one progress snapshot."""
    progress = read_progress(payload)
    tops, foots, regions_out, memo = ctx.outputs_list
    regions = {
        (entry["id"]["kind"], entry["id"]["item"]): item_regions(
            progress, entry["id"]["kind"], entry["id"]["item"]
        )
        for entry in tops
    }

    def column(entries: list[dict[str, Any]], index: int) -> list[Any]:
        drawn = [regions.get((e["id"]["kind"], e["id"]["item"])) for e in entries]
        return [no_update if d is None else d[index] for d in drawn]

    region_content = view_regions(progress)
    count, readiness = memo_regions(progress)
    memo_content = {"count": count, "readiness": readiness}
    return (
        column(tops, 0),
        column(foots, 1),
        [
            region_content.get((entry["id"]["view"], entry["id"]["slot"]), no_update)
            for entry in regions_out
        ],
        [memo_content.get(entry["id"]["slot"], no_update) for entry in memo],
    )


@callback(
    Output({"type": EDITOR, "kind": ALL, "item": ALL}, "children"),
    Input(EDITING, "data"),
    prevent_initial_call=True,
)
def render_editors(request: Any) -> list[Any]:
    """Draw the editors just opened and clear those just closed; every other
    editor slot, an open editor included, is left as it is."""
    regions = editor_regions(request)
    return [
        regions.get((entry["id"]["kind"], entry["id"]["item"]), no_update)
        for entry in ctx.outputs_list
    ]


clientside_callback(
    ClientsideFunction(namespace="pcnReviewUi", function_name="sessionChanged"),
    Output(SHAPE, "data"),
    Input(RECORD, "data"),
    Input(SUMMARY_STATE, "data"),
    Input(COMPLETION, "data"),
    State(CONFIG, "data"),
    State(SHAPE, "data"),
)

clientside_callback(
    ClientsideFunction(namespace="pcnReviewUi", function_name="viewChanged"),
    Input(VIEW, "data"),
    State(CONFIG, "data"),
)
