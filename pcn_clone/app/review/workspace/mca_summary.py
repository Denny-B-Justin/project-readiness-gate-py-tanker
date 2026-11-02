"""The weighted priority summary under the open scoring component.

While any criterion is still drafting or failed, the summary shows its
institutional half only: criteria, weights, the table's arithmetic and the
band thresholds, with each arrived draft's score and no weighted points,
total, percent or band (a partial sum is a wrong number, not a preview).
Once every draft exists it is **provisional**, computed over the drafts
and the reviewer's adjustments; once every score is decided it is
**final**, the computation the memo carries. Every number comes from
``compute_mca_summary`` through :mod:`.summary_state`; this module only
renders. The normalised score sits on a gauge against the matrix's own
band thresholds.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from dash import html
from dash.development.base_component import Component

from pcn_clone.app.a11y import aria
from pcn_clone.app.review.workspace.pills import band_pill, queued_pill
from pcn_clone.app.review.workspace.records import (
    JsonObject,
    as_object,
    disposition_of,
    status_of,
)
from pcn_clone.app.review.workspace.summary_state import McaSummaryState, percent_text
from pcn_clone.content.models import McaBand, McaMatrix
from pcn_clone.core.jsstr import number_to_string

TITLE = "Prioritisation score"

DESCRIPTION = (
    "Weighted points are the endorsed score times the criterion weight. The "
    "weights, the thresholds, and this arithmetic are institutional data — the "
    "model contributes none of it."
)

PROVISIONAL_NOTE = (
    "Provisional — computed over the drafted scores; it becomes final when "
    "every score carries your decision. The memo carries only the final "
    "computation."
)

FINAL_NOTE = "Every criterion is endorsed — this is the score the memo carries."


def _number(value: float) -> str:
    return number_to_string(value)


def _head() -> html.Thead:
    return html.Thead(
        html.Tr(
            [
                html.Th("Assessment criterion"),
                html.Th("Weight", className="is-number"),
                html.Th("Score", className="is-number"),
                html.Th("Weighted points", className="is-number"),
            ]
        )
    )


def _row(label: str, note: str, tone: str, cells: Sequence[str], muted: str) -> html.Tr:
    return html.Tr(
        className=muted,
        children=[
            html.Th(
                [label, html.Span(note, className=f"rv-row-note {tone}".rstrip())],
                scope="row",
            ),
            *(html.Td(cell, className="is-number") for cell in cells),
        ],
    )


def _foot(total: str, percent: str) -> html.Tfoot:
    return html.Tfoot(
        [
            html.Tr(
                [
                    html.Th("Total score (weighted points)", scope="row"),
                    html.Td(),
                    html.Td(),
                    html.Td(total, className="is-total"),
                ]
            ),
            html.Tr(
                [
                    html.Th("Normalised score (% of maximum)", scope="row"),
                    html.Td(),
                    html.Td(),
                    html.Td(percent, className="is-total"),
                ]
            ),
        ]
    )


def band_gauge(bands: Sequence[McaBand], fill_percent: float) -> html.Div:
    """The gauge: the fill, and each band threshold above zero as a
    labelled tick (the zero band is the floor)."""
    children: list[Component] = []
    if fill_percent > 0:
        width = max(0.0, min(100.0, fill_percent))
        children.append(
            html.Div(className="rv-gauge-fill", style={"width": f"{width:g}%"})
        )
    for band in bands:
        if band.min_percent_of_maximum > 0:
            threshold = _number(band.min_percent_of_maximum)
            children.append(
                html.Span(
                    html.Span(f"{band.label} {threshold}", className="rv-gauge-label"),
                    className="rv-gauge-tick",
                    style={"left": f"{threshold}%"},
                )
            )
    return html.Div(children, className="rv-gauge")


def _panel(
    head_mark: Component, body: list[Component], *, pending: bool
) -> html.Section:
    return html.Section(
        className="rv-summary is-pending" if pending else "rv-summary",
        **aria(label=TITLE),
        children=[
            html.Header(
                className="rv-card-head",
                children=[
                    html.Div(
                        className="rv-card-names",
                        children=[
                            html.H3(TITLE, className="rv-card-title"),
                            html.P(DESCRIPTION, className="rv-card-desc"),
                        ],
                    ),
                    html.Div(head_mark, className="rv-card-marks"),
                ],
            ),
            html.Div(body, className="rv-summary-body"),
        ],
    )


def mca_summary_panel(
    selected: McaSummaryState,
    matrix: McaMatrix,
    states: Mapping[str, JsonObject],
) -> html.Section:
    """The provisional or final summary; each row says whether its score
    carries the reviewer's decision."""
    summary = selected.summary
    if summary is None:
        raise ValueError("An unavailable summary has no panel; use pending_summary.")
    provisional = selected.state == "provisional"
    rows = []
    for row in summary.rows:
        disposition = disposition_of(states.get(row.criterion_id, {}))
        if disposition is None:
            note, tone, muted = (
                "Drafted — awaiting your decision",
                "is-drafted",
                "is-muted",
            )
        elif disposition.get("kind") == "adjusted":
            note, tone, muted = "Adjusted by you", "", ""
        else:
            note, tone, muted = "Accepted", "", ""
        cells = [_number(row.weight), _number(row.score), _number(row.weighted_points)]
        rows.append(_row(row.label, note, tone, cells, muted))
    mark = (
        html.Span("Provisional", className="rv-provisional")
        if provisional
        else html.Span(
            [html.Span(className="pill-dot", **aria(hidden="true")), "Endorsed"],
            className="pill pill-pass pill-sm",
        )
    )
    return _panel(
        mark,
        [
            html.Div(
                html.Table(
                    [
                        _head(),
                        html.Tbody(rows),
                        _foot(
                            f"{_number(summary.total_weighted_points)} / "
                            f"{_number(summary.max_weighted_points)}",
                            percent_text(summary.percent_of_maximum),
                        ),
                    ],
                    className="rv-summary-table",
                ),
                className="rv-table-scroll",
            ),
            html.Div(
                className="rv-band",
                children=[
                    band_gauge(matrix.bands, summary.percent_of_maximum),
                    html.Div(
                        className="rv-band-row",
                        children=[
                            band_pill(summary.band.label),
                            html.P(
                                PROVISIONAL_NOTE if provisional else FINAL_NOTE,
                                className="rv-band-note",
                            ),
                        ],
                    ),
                ],
            ),
        ],
        pending=False,
    )


def pending_summary(
    matrix: McaMatrix, states: Mapping[str, JsonObject]
) -> html.Section:
    """The summary's institutional shell while scores are still drafting."""
    total = len(matrix.criteria)
    arrived = sum(status_of(states.get(c.id, {})) == "ok" for c in matrix.criteria)
    rows = []
    for criterion in matrix.criteria:
        state = states.get(criterion.id, {})
        status = status_of(state)
        if status == "ok":
            note, tone, muted = (
                "Drafted — awaiting your decision",
                "is-drafted",
                "is-muted",
            )
            score = _number(as_object(state.get("scoreFinding")).get("score", 0))
        elif status == "error":
            note, tone, muted, score = "Failed to score", "is-failed", "is-faint", "—"
        else:
            note, tone, muted, score = "Still drafting", "is-waiting", "is-faint", "—"
        rows.append(
            _row(
                criterion.label,
                note,
                tone,
                [_number(criterion.weight), score, "—"],
                muted,
            )
        )
    return _panel(
        queued_pill(f"{arrived} of {total} scores in"),
        [
            html.Div(
                html.Table(
                    [_head(), html.Tbody(rows), _foot("—", "—")],
                    className="rv-summary-table",
                ),
                className="rv-table-scroll",
            ),
            html.Div(
                className="rv-band",
                children=[
                    band_gauge(matrix.bands, 0),
                    html.Div(
                        className="rv-band-row",
                        children=[
                            html.Span("No band yet", className="rv-band-pending"),
                            html.P(
                                "The normalised score and its band are computed only "
                                "once every criterion carries a score. "
                                f"{arrived} of {total} have returned.",
                                className="rv-band-note",
                            ),
                        ],
                    ),
                ],
            ),
        ],
        pending=True,
    )


def mca_summary(
    selected: McaSummaryState, matrix: McaMatrix, states: Mapping[str, JsonObject]
) -> html.Section:
    """The summary in whichever of its three states ``selected`` is."""
    if selected.state == "unavailable":
        return pending_summary(matrix, states)
    return mca_summary_panel(selected, matrix, states)
