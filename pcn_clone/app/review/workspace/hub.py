"""The two-component navigation: each component of the assessment (the
qualitative findings, the prioritisation scoring) is one openable card on
the hub with its own progress and item list, and opens into a focused view
headed by a back row and the component's header.

While a component's drafts stream in, its card is dashed, its meter counts
drafts with animated stripes, a drafting pill says how many are left, and
the call to action invites reviewing them as they arrive; afterwards the
meter counts decisions. Each item shows its live status, with a green tick
once the reviewer has dealt with it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dash import html
from dash.development.base_component import Component

from pcn_clone.app.a11y import aria, data
from pcn_clone.app.icons import icon
from pcn_clone.app.review.workspace.ids import REGION, ViewKey
from pcn_clone.app.review.workspace.pills import (
    band_pill,
    done_tick,
    drafting_pill,
    failed_mark,
    score_pill,
    verdict_pill,
)
from pcn_clone.app.review.workspace.records import (
    JsonObject,
    as_object,
    is_decided,
    state_of,
    status_of,
)
from pcn_clone.app.review.workspace.summary_state import (
    McaSummaryState,
    effective_score,
)


@dataclass(frozen=True, slots=True)
class HubItem:
    """One row of a hub card's item list."""

    id: str
    label: str
    status: Component
    done: bool


@dataclass(frozen=True, slots=True)
class HubPart:
    """One component of the assessment, as the hub presents it."""

    key: ViewKey
    title: str
    blurb: str
    done: int
    total: int
    done_label: str
    cta: str
    loading: bool
    items: tuple[HubItem, ...]
    headline: Component | None = None
    title_tag: Component | None = None

    @property
    def trail(self) -> str:
        """The progress line, e.g. "2 of 5 decided"."""
        return f"{self.done} of {self.total} {self.done_label}"

    @property
    def aside(self) -> Component | None:
        """What the open view's header shows on the right."""
        return self.headline if self.headline is not None else self.title_tag


FINDINGS_TITLE = "Assessment findings"
SCORES_TITLE = "Prioritisation scoring"


def findings_blurb(count: int) -> str:
    return f"{count} qualitative dimensions evaluated for your review"


def scores_blurb(count: int, scale: Sequence[Mapping[str, Any]]) -> str:
    low, high = scale[0].get("value"), scale[-1].get("value")
    return f"{count} weighted criteria scored {low}–{high} against their descriptors"


def _unfinished_mark(state: JsonObject) -> Component:
    """A hub item that has no result yet, or failed."""
    if status_of(state) == "error":
        return failed_mark(small=True)
    return drafting_pill(small=True)


def _cta(loading: bool, drafted: int, decided: int, total: int, noun: str) -> str:
    if loading:
        return "Review as they arrive" if drafted > 0 else "Open component"
    return f"Review {noun}" if decided < total else f"Revisit {noun}"


def findings_part(
    definitions: Sequence[JsonObject], dimensions: Mapping[str, Any]
) -> HubPart:
    """The findings component over the record's dimension states."""
    states = [state_of(dimensions, str(d.get("id"))) for d in definitions]
    total = len(states)
    decided = sum(is_decided(state) for state in states)
    drafted = sum(status_of(state) != "pending" for state in states)
    loading = drafted < total
    items = tuple(
        HubItem(
            id=str(definition.get("id")),
            label=str(definition.get("label", "")),
            status=(
                verdict_pill(
                    str(as_object(state.get("finding")).get("verdict", "")), small=True
                )
                if status_of(state) == "ok"
                else _unfinished_mark(state)
            ),
            done=is_decided(state),
        )
        for definition, state in zip(definitions, states, strict=True)
    )
    return HubPart(
        key="findings",
        title=FINDINGS_TITLE,
        blurb=findings_blurb(len(definitions)),
        done=drafted if loading else decided,
        total=total,
        done_label="drafted" if loading else "decided",
        cta=_cta(loading, drafted, decided, total, "findings"),
        loading=loading,
        items=items,
        headline=(
            drafting_pill(f"{total - drafted} of {total} still drafting")
            if loading
            else None
        ),
    )


def scores_part(
    matrix: JsonObject,
    states: Mapping[str, JsonObject],
    summary: McaSummaryState,
) -> HubPart:
    """The scoring component over the record's criterion states, keyed in
    matrix order; its title carries the band once the summary is
    computable."""
    criteria = [as_object(c) for c in matrix.get("criteria", [])]
    scale = [as_object(entry) for entry in matrix.get("scale", [])]
    total = len(criteria)
    ordered = [state_of(states, str(c.get("id"))) for c in criteria]
    decided = sum(is_decided(state) for state in ordered)
    drafted = sum(status_of(state) != "pending" for state in ordered)
    loading = drafted < total
    items = tuple(
        HubItem(
            id=str(criterion.get("id")),
            label=str(criterion.get("label", "")),
            status=(
                score_pill(effective_score(state), scale, small=True)
                if status_of(state) == "ok"
                else _unfinished_mark(state)
            ),
            done=is_decided(state),
        )
        for criterion, state in zip(criteria, ordered, strict=True)
    )
    band = (
        band_pill(summary.summary.band.label, small=True)
        if summary.summary is not None
        else None
    )
    return HubPart(
        key="scores",
        title=SCORES_TITLE,
        blurb=scores_blurb(total, scale),
        done=drafted if loading else decided,
        total=total,
        done_label="drafted" if loading else "endorsed",
        cta=_cta(loading, drafted, decided, total, "scores"),
        loading=loading,
        items=items,
        headline=(
            drafting_pill(f"{total - drafted} of {total} still drafting")
            if loading
            else None
        ),
        title_tag=band,
    )


def meter(done: int, total: int, label: str, *, loading: bool) -> list[Component]:
    """The thin progress meter and its mono caption; striped while loading."""
    percent = (done / total) * 100 if total > 0 else 0
    caption = f"{done} of {total} {label}"
    return [
        html.Div(
            role="img",
            className="rv-meter",
            **aria(label=caption),
            children=html.Div(
                className="rv-meter-fill is-loading" if loading else "rv-meter-fill",
                style={"width": f"{percent:g}%"},
            ),
        ),
        html.P(caption, className="rv-meter-caption"),
    ]


def hub_card(view: ViewKey, title: str) -> html.Button:
    """One view as an openable card, drawn once; what it shows is the
    ``hub`` region within, redrawn as states change, so the button (and the
    focus on it) survives every redraw."""
    return html.Button(
        type="button",
        className="rv-hub-card",
        **aria(label=f"Open {title}"),
        **data(rv_open=view),
        children=html.Div(
            id={"type": REGION, "view": view, "slot": "hub"},
            className="rv-hub-region",
        ),
    )


def hub_card_content(part: HubPart) -> html.Div:
    """What a view's hub card shows: title, blurb, live headline and meter,
    the item list with each item's status, and the call to action. Marked
    ``is-loading`` while drafts stream in."""
    head: list[Component] = [
        html.Div(
            className="rv-hub-title-row",
            children=[
                html.H2(part.title, className="rv-hub-title"),
                *(
                    [html.Span(part.title_tag, className="rv-hub-tag")]
                    if part.title_tag
                    else []
                ),
            ],
        ),
        html.P(part.blurb, className="rv-hub-blurb"),
    ]
    if part.headline is not None:
        head.append(html.Div(part.headline, className="rv-hub-headline"))
    head += meter(part.done, part.total, part.done_label, loading=part.loading)
    return html.Div(
        className="rv-hub-content is-loading" if part.loading else "rv-hub-content",
        children=[
            html.Div(head, className="rv-hub-head"),
            html.Ul(
                className="rv-hub-items",
                children=[
                    html.Li(
                        className="rv-hub-item",
                        children=[
                            html.Span(item.label, className="rv-hub-item-label"),
                            html.Span(
                                [item.status, *(done_tick() if item.done else [])],
                                className="rv-hub-item-status",
                            ),
                        ],
                    )
                    for item in part.items
                ],
            ),
            html.Div(
                className="rv-hub-foot",
                children=html.Span(
                    [part.cta, icon("chevron-right", 15, weight="bold")],
                    className="rv-hub-cta",
                ),
            ),
        ],
    )


def back_row(view: ViewKey) -> html.Div:
    """The back-to-hub button and the component's progress trail."""
    return html.Div(
        className="rv-back-row",
        children=[
            html.Button(
                [icon("arrow-left", 15), "All components"],
                type="button",
                className="rv-back",
                **data(rv_close=""),
            ),
            html.Span(
                id={"type": REGION, "view": view, "slot": "trail"}, className="rv-trail"
            ),
        ],
    )


def view_header(view: ViewKey, title: str, blurb: str) -> html.Div:
    """The open component's heading block, its live aside on the right."""
    return html.Div(
        className="rv-view-head",
        children=[
            html.Div(
                className="rv-view-names",
                children=[
                    html.H2(title, className="rv-view-title"),
                    html.P(blurb, className="rv-view-blurb"),
                ],
            ),
            html.Div(
                id={"type": REGION, "view": view, "slot": "aside"},
                className="rv-view-aside",
            ),
        ],
    )
