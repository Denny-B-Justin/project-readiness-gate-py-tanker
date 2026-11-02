"""What the workspace's live regions show, and the editors it draws.

``assets/review-ui.js`` publishes a progress snapshot to ``rv-ws-progress``
as results land, decisions change and the summary's completion moves:

``{dimensionDefs, dimensions, mca: {matrix, criteria} | None, fields,
render: {"dimension" | "criterion": {item id: key}}, summary, memo: {ready,
reasons} | None}``

where ``fields`` holds the snapshotted fields the items to draw cite, and
``render`` names the items whose card regions are stale, each with the key
of the state to draw (echoed into the drawn top, so the script can tell
what a card shows); a component's cards are named once its view has been
opened, and ``summary`` says whether the score summary is drawn yet. The
component regions (hub cards, trails, asides, the score summary) and the
memo panel's regions are drawn from every snapshot.

It asks for editors through ``rv-ws-editing``:

``{draw: [{kind, item, definition | criterion, state}], clear: [{kind,
item}], scale, fields}``

``draw`` names the editors opened but not drawn yet (a score editor with the
criterion's state, for the AI draft it shows), ``clear`` the editors closed
but still drawn, and ``fields`` the field snapshot the evidence picker
offers, with the text of the fields a drawn reference cites.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from dash import html
from dash.development.base_component import Component

from pcn_clone.app.review.workspace.endorsement import endorsement
from pcn_clone.app.review.workspace.finding_card import (
    finding_editor,
    finding_foot,
    finding_top,
)
from pcn_clone.app.review.workspace.hub import (
    HubPart,
    findings_part,
    hub_card_content,
    scores_part,
)
from pcn_clone.app.review.workspace.mca_summary import mca_summary
from pcn_clone.app.review.workspace.memo_panel import (
    completion_status,
    memo_readiness,
    sections_in,
)
from pcn_clone.app.review.workspace.records import (
    JsonObject,
    as_list,
    as_object,
    field_index,
    state_of,
    status_of,
)
from pcn_clone.app.review.workspace.score_card import (
    score_editor,
    score_foot,
    score_reference,
    score_top,
)
from pcn_clone.app.review.workspace.summary_state import (
    matrix_states,
    select_mca_summary_state,
)
from pcn_clone.content.models import McaMatrix

Regions = tuple[Component, Component | None]
"""An item's top and foot."""


@dataclass(frozen=True, slots=True)
class Progress:
    """One progress snapshot, read."""

    definitions: list[JsonObject]
    dimensions: JsonObject
    fields: dict[str, JsonObject]
    render: dict[str, dict[str, str]]
    memo: JsonObject | None
    summary: bool = False
    matrix_json: JsonObject = field(default_factory=dict)
    matrix: McaMatrix | None = None
    criteria: dict[str, JsonObject] = field(default_factory=dict)


def read_progress(payload: Any) -> Progress:
    """The snapshot ``payload``; the matrix is validated as content."""
    snapshot = as_object(payload)
    mca = as_object(snapshot.get("mca"))
    matrix_json = as_object(mca.get("matrix"))
    matrix = McaMatrix.model_validate(matrix_json) if matrix_json else None
    render = as_object(snapshot.get("render"))
    memo = snapshot.get("memo")
    return Progress(
        definitions=[as_object(d) for d in as_list(snapshot.get("dimensionDefs"))],
        dimensions=as_object(snapshot.get("dimensions")),
        fields=field_index(as_object(f) for f in as_list(snapshot.get("fields"))),
        render={
            kind: {str(item): str(key) for item, key in as_object(keys).items()}
            for kind, keys in render.items()
        },
        memo=memo if isinstance(memo, Mapping) else None,
        summary=snapshot.get("summary") is True,
        matrix_json=matrix_json,
        matrix=matrix,
        criteria=(
            matrix_states(matrix, as_object(mca.get("criteria"))) if matrix else {}
        ),
    )


def item_regions(progress: Progress, kind: str, item: str) -> Regions | None:
    """The regions of one card, or None when the snapshot does not ask for
    them."""
    key = progress.render.get(kind, {}).get(item)
    if key is None:
        return None
    if kind == "dimension":
        definition = next(
            (d for d in progress.definitions if str(d.get("id")) == item), None
        )
        if definition is None:
            return None
        state = state_of(progress.dimensions, item)
        top = finding_top(definition, state, progress.fields, key)
        return top, finding_foot(state)
    criterion = next(
        (
            as_object(c)
            for c in as_list(progress.matrix_json.get("criteria"))
            if str(as_object(c).get("id")) == item
        ),
        None,
    )
    if criterion is None:
        return None
    scale = [as_object(entry) for entry in as_list(progress.matrix_json.get("scale"))]
    state = state_of(progress.criteria, item)
    top = score_top(criterion, scale, state, progress.fields, key)
    return top, score_foot(scale, state)


def view_regions(progress: Progress) -> dict[tuple[str, str], Component | None]:
    """Each view's hub card, trail and aside, and (once asked for) the score
    summary, keyed ``(view, slot)``."""
    regions: dict[tuple[str, str], Component | None] = {}
    parts: list[HubPart] = [findings_part(progress.definitions, progress.dimensions)]
    if progress.matrix is not None:
        selected = select_mca_summary_state(progress.matrix, progress.criteria)
        parts.append(scores_part(progress.matrix_json, progress.criteria, selected))
        if progress.summary:
            regions[("scores", "summary")] = mca_summary(
                selected, progress.matrix, progress.criteria
            )
    for part in parts:
        regions[(part.key, "hub")] = hub_card_content(part)
        regions[(part.key, "trail")] = html.Span(part.trail)
        regions[(part.key, "aside")] = part.aside
    return regions


def memo_regions(progress: Progress) -> tuple[str, list[Component]]:
    """The locked panel's count, and the open panel's readiness: every
    blocking reason, or the ready line and what stands."""
    states = [
        state_of(progress.dimensions, str(d.get("id"))) for d in progress.definitions
    ]
    states += list(progress.criteria.values())
    done = sum(status_of(state) != "pending" for state in states)
    count = sections_in(done, len(states))
    memo = progress.memo
    if memo is None:
        return count, []
    has_mca = progress.matrix is not None
    if memo.get("ready") is not True:
        reasons = [str(reason) for reason in as_list(memo.get("reasons"))]
        return count, memo_readiness(reasons, has_mca=has_mca, completion=None)
    settled = endorsement(
        progress.definitions, progress.dimensions, progress.matrix, progress.criteria
    )
    return count, memo_readiness(
        [], has_mca=has_mca, completion=completion_status(settled)
    )


def editor_regions(payload: Any) -> dict[tuple[str, str], Component | None]:
    """The editors to draw and (as None) to clear, keyed ``(kind, item)``."""
    request = as_object(payload)
    fields = [as_object(f) for f in as_list(request.get("fields"))]
    index = field_index(fields)
    scale = [as_object(entry) for entry in as_list(request.get("scale"))]
    regions: dict[tuple[str, str], Component | None] = {
        (str(entry.get("kind")), str(entry.get("item"))): None
        for entry in map(as_object, as_list(request.get("clear")))
    }
    for entry in map(as_object, as_list(request.get("draw"))):
        kind, item = str(entry.get("kind")), str(entry.get("item"))
        if kind == "dimension":
            regions[(kind, item)] = finding_editor(
                as_object(entry.get("definition")), fields
            )
        else:
            reference = score_reference(as_object(entry.get("state")), index)
            regions[(kind, item)] = score_editor(
                as_object(entry.get("criterion")), scale, fields, reference
            )
    return regions
