"""The reviewer summary, and whether the assessment is complete.

The summary is the reviewer's own text, written against findings and
scores that have all returned: while anything is still drafting the panel
stays collapsed and locked, counting the sections in (failed items unlock
it; a failure is something to write about, not to wait behind). Once open,
the textarea autosaves through the review store (``assets/review-ui.js``
owns its value and save line) and the panel lists every reason the
assessment is not complete yet, in the order to deal with them. When none
is left it says so and states what stands: the findings endorsed and the
final prioritisation score.

Both variants are drawn once; review-ui.js shows the one that applies.
"""

from __future__ import annotations

from collections.abc import Sequence

from dash import html
from dash.development.base_component import Component

from pcn_clone.app.a11y import aria
from pcn_clone.app.icons import icon
from pcn_clone.app.review.workspace.endorsement import Endorsement
from pcn_clone.app.review.workspace.ids import (
    AUTOSAVE,
    MEMO,
    SUMMARY,
)
from pcn_clone.app.review.workspace.messages import AUTOSAVE_IDLE
from pcn_clone.app.review.workspace.pills import drafting_pill
from pcn_clone.app.review.workspace.summary_state import percent_text

READY_WITH_SCORES = (
    "Every finding is decided, every criterion score endorsed, and your summary "
    "is saved."
)
READY = "Every finding is decided and your summary is saved."

SUMMARY_PLACEHOLDER = "Write your review of the submitted PCN here."


def memo_panel() -> html.Div:
    """Both variants of the panel: locked while drafting, open after."""
    return html.Div(
        className="rv-memo",
        children=[
            html.Section(
                className="rv-memo-locked",
                **aria(label="Reviewer summary"),
                children=[
                    html.Div(
                        className="rv-memo-locked-text",
                        children=[
                            html.H2("Reviewer summary", className="rv-hub-title"),
                            html.P(
                                [
                                    "Opens for writing once the assessment findings "
                                    "and prioritisation scores have returned. ",
                                    html.Span(id={"type": MEMO, "slot": "count"}),
                                ],
                                className="rv-hub-blurb",
                            ),
                        ],
                    ),
                    html.Span(
                        drafting_pill("Waiting for assessment to complete"),
                        role="status",
                        className="rv-memo-waiting",
                        **aria(live="polite"),
                    ),
                ],
            ),
            html.Section(
                className="rv-memo-open",
                **aria(label="Reviewer summary and readiness"),
                children=[
                    html.Header(
                        className="rv-memo-head",
                        children=[
                            html.H2("Reviewer summary", className="rv-hub-title"),
                            html.P(
                                "Your written review of the submitted PCN.",
                                className="rv-card-desc",
                            ),
                        ],
                    ),
                    html.Div(
                        className="rv-memo-body",
                        children=[
                            html.Textarea(
                                id=SUMMARY,
                                className="rv-summary-input",
                                placeholder=SUMMARY_PLACEHOLDER,
                                **aria(label="Reviewer summary"),
                            ),
                            html.Div(
                                html.P(
                                    AUTOSAVE_IDLE,
                                    id=AUTOSAVE,
                                    role="status",
                                    className="rv-autosave",
                                    **aria(live="polite"),
                                ),
                                className="rv-autosave-row",
                            ),
                            html.Div(
                                className="rv-readiness",
                                children=[
                                    html.H3(
                                        "Assessment readiness",
                                        className="rv-section-label",
                                    ),
                                    html.Div(
                                        id={"type": MEMO, "slot": "readiness"},
                                        className="rv-readiness-body",
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def sections_in(done: int, total: int) -> str:
    """The locked panel's count of returned sections."""
    return f"{done} of {total} sections in."


def completion_status(settled: Endorsement) -> str:
    """What stands once the assessment is complete."""
    count = settled.standing
    text = f"{count} {'finding' if count == 1 else 'findings'} endorsed"
    if settled.dismissed:
        text += f", {settled.dismissed} dismissed"
    if settled.summary is not None:
        text += (
            f"; final prioritisation score "
            f"{percent_text(settled.summary.percent_of_maximum)} — "
            f"{settled.summary.band.label} priority"
        )
    return f"Assessment complete: {text}."


def memo_readiness(
    reasons: Sequence[str],
    *,
    has_mca: bool,
    completion: str | None,
) -> list[Component]:
    """Every blocking reason, or the ready line and the completion status."""
    if reasons:
        return [
            html.Ul([html.Li(reason) for reason in reasons], className="rv-reasons")
        ]
    children: list[Component] = [
        html.P(READY_WITH_SCORES if has_mca else READY, className="rv-ready")
    ]
    if completion is not None:
        children.append(
            html.P(
                [icon("circle-check", 15, weight="bold"), completion],
                role="status",
                className="rv-complete",
            )
        )
    return children
