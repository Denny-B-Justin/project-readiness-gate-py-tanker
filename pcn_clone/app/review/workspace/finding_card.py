"""One dimension's finding, decided in place.

The card shows the finding as it will stand in the memo: the reviewer's
correction where edited (the record keeps the AI draft as the audit trail,
reachable through "Edit again"), the AI draft otherwise. The decision is a
single footer line once made; a note on it is opt-in.

States: drafting (the institutional half, skeleton lines where the model's
text will land, the decision strip disabled); failed (Retry only when a
retry can succeed); drafted and undecided (Accept, Edit…, Dismiss); and
decided (accepted, edited or dismissed, with Change and, for an edit, Edit
again). Editing turns the card into the form: the verdict as a segmented
chooser under the title, the text edited where it is read, the evidence
curated in the tray it is read in. ``assets/review-ui.js`` owns the form's
values and saves an edit that changes nothing as an acceptance.
"""

from __future__ import annotations

from collections.abc import Sequence

from dash import html
from dash.development.base_component import Component

from pcn_clone.app.a11y import aria, data
from pcn_clone.app.review.workspace.card import (
    add_note_button,
    card_frame,
    card_top,
    decided_footer,
    decision_footer,
    editor_frame,
    error_body,
    pending_actions,
    radio_slot,
)
from pcn_clone.app.review.workspace.controls import action_button
from pcn_clone.app.review.workspace.evidence import (
    citation_list,
    curated_list,
    disclosure,
    evidence_editor,
    evidence_tray,
)
from pcn_clone.app.review.workspace.ids import control_id
from pcn_clone.app.review.workspace.messages import SAVE_EDIT
from pcn_clone.app.review.workspace.pills import (
    VERDICT_LABELS,
    drafting_pill,
    failed_mark,
    sk_lines,
    verdict_pill,
)
from pcn_clone.app.review.workspace.records import (
    FieldIndex,
    JsonObject,
    as_list,
    as_object,
    disposition_of,
    status_of,
)

INVALID_RESULT = (
    "The result returned for this dimension was internally inconsistent and "
    "was not kept — an application defect, not something a retry can fix. "
    "Completed findings remain readable; please report this."
)

MOVED_ON = (
    "This dimension can no longer be assessed: the platform has moved on "
    "since this Concept Note was submitted (its template, criteria, model, or "
    "assessor protocol changed). Completed findings remain readable. To assess "
    "against the current configuration, submit the project again from its "
    "editor."
)

NOTE_PLACEHOLDER = "Anything worth recording about this decision."


def finding_card(definition: JsonObject) -> html.Section:
    """The frame of one dimension's card."""
    return card_frame(
        "dimension",
        str(definition.get("id", "")),
        str(definition.get("label", "")),
        note_placeholder=NOTE_PLACEHOLDER,
    )


def finding_top(
    definition: JsonObject, state: JsonObject, fields: FieldIndex, key: str
) -> html.Div:
    """The card's header and body for ``state``."""
    status = status_of(state)
    title = str(definition.get("label", ""))
    description = str(definition.get("description", ""))
    if status == "pending":
        return card_top(
            status,
            key,
            title,
            description,
            [drafting_pill("Drafting verdict")],
            _pending_body(),
        )
    if status == "error":
        return card_top(
            status,
            key,
            title,
            description,
            [failed_mark()],
            error_body(state, INVALID_RESULT, MOVED_ON),
        )
    finding = as_object(state.get("finding"))
    disposition = disposition_of(state)
    edited = (
        disposition if disposition and disposition.get("kind") == "edited" else None
    )
    verdict = edited.get("finalVerdict") if edited else finding.get("verdict")
    return card_top(
        status,
        key,
        title,
        description,
        [verdict_pill(str(verdict))],
        _finding_body(finding, edited, fields),
    )


def finding_foot(state: JsonObject) -> html.Footer | None:
    """The card's decision footer; none until the finding has arrived."""
    if status_of(state) != "ok":
        return None
    disposition = disposition_of(state)
    if disposition is None:
        return decision_footer(
            [
                action_button("Accept", "accept"),
                action_button("Edit…", "edit", "btn-secondary"),
                action_button("Dismiss", "dismiss", "btn-ghost"),
            ]
        )
    kind = disposition.get("kind")
    buttons: list[Component] = []
    if not disposition.get("note"):
        buttons.append(add_note_button())
    if kind == "edited":
        buttons.append(action_button("Edit again", "edit", "btn-ghost"))
    buttons.append(action_button("Change", "change", "btn-ghost"))
    if kind == "dismissed":
        return decided_footer("Dismissed — not in the memo", buttons, dismissed=True)
    text = "Edited by you" if kind == "edited" else "Accepted as drafted"
    return decided_footer(text, buttons)


def _pending_body() -> html.Div:
    return html.Div(
        className="rv-card-body",
        children=[
            sk_lines(["100%", "97%", "91%", "58%"]),
            html.Div(
                className="rv-locating",
                children=[
                    html.Span("Evidence", className="rv-tray-label"),
                    html.Span(
                        "Locating citations in the submitted answers",
                        className="rv-tray-detail",
                    ),
                ],
            ),
            pending_actions(
                [
                    ("Accept", "btn-primary"),
                    ("Edit…", "btn-secondary"),
                    ("Dismiss", "btn-ghost"),
                ],
                "The verdict, reasoning, and citations arrive together — decisions "
                "open the moment they do.",
            ),
        ],
    )


def _finding_body(
    finding: JsonObject, edited: JsonObject | None, fields: FieldIndex
) -> html.Div:
    text = edited.get("finalText") if edited else finding.get("reasoning")
    children: list[Component] = [html.P(str(text or ""), className="rv-prose")]
    if edited is not None:
        refs = [as_object(ref) for ref in as_list(edited.get("evidence"))]
        if refs:
            children.append(evidence_tray(len(refs), curated_list(refs, fields)))
    else:
        refs = [as_object(ref) for ref in as_list(finding.get("evidence"))]
        if refs:
            children.append(evidence_tray(len(refs), citation_list(refs, fields)))
    questions = [str(q) for q in as_list(finding.get("questions"))]
    if questions:
        children.append(
            html.Div(
                className="rv-questions",
                children=[
                    html.H4("Questions for the proposer", className="rv-section-label"),
                    html.Ul([html.Li(question) for question in questions]),
                ],
            )
        )
    return html.Div(children, className="rv-card-body")


def verdict_choice(name: str) -> html.Div:
    """The segmented verdict chooser, worst first; review-ui.js checks the
    draft's verdict."""
    return html.Div(
        role="radiogroup",
        className="rv-choice",
        **aria(label="Final verdict"),
        **data(rv_choice="verdict"),
        children=[
            html.Label(
                className=f"rv-choice-option is-{verdict}",
                children=[
                    radio_slot(name, verdict),
                    html.Span(className="rv-choice-dot", **aria(hidden="true")),
                    label,
                ],
            )
            for verdict, label in VERDICT_LABELS.items()
        ],
    )


TEXT_MISSING = (
    "An edited finding needs its text — it replaces the AI draft in the memo."
)


def finding_editor(definition: JsonObject, fields: Sequence[JsonObject]) -> html.Div:
    """The card as the form: verdict chooser, finding text and the evidence
    curated inside its tray, over the record's field snapshot."""
    item = str(definition.get("id", ""))
    head = html.Header(
        className="rv-editor-head",
        children=[
            html.H3(str(definition.get("label", "")), className="rv-card-title"),
            html.P(str(definition.get("description", "")), className="rv-card-desc"),
            verdict_choice(control_id("dimension", item, "verdict")),
        ],
    )
    curation = evidence_editor(
        "dimension",
        item,
        fields,
        empty_state=html.P("No citations kept.", className="rv-empty-note"),
        note_placeholder="Why this answer supports your finding.",
    )
    body = [
        html.Textarea(
            id=control_id("dimension", item, "text"),
            className="rv-editor-text",
            placeholder="Your finding, in your words.",
            **aria(label="Finding text"),
            **data(rv_field="text"),
        ),
        html.P(
            TEXT_MISSING,
            className="rv-field-error",
            hidden=True,
            **data(rv_error="text"),
        ),
        disclosure(
            "Evidence",
            html.Span(
                [html.Span(**data(rv_fill="citations")), " — editable"],
                className="rv-tray-detail",
            ),
            curation,
            class_name="is-editing",
        ),
    ]
    return editor_frame(
        "dimension",
        head,
        body,
        "Your text replaces the AI draft in the memo.",
        action_button(SAVE_EDIT, "save-edit"),
    )
