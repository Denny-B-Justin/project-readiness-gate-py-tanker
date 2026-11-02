"""One criterion's drafted score, decided in place.

The card shows the score as it will stand in the memo: the reviewer's
adjustment where adjusted (its rationale and its own basis; the superseded
AI justification stays in the record), the AI draft otherwise. The body
argues the score: the justification, the basis (verified citations, or a
"Scored on absent evidence" notice when the submission is silent, which by
invariant sits at the scale floor) and the scoring guide, every descriptor
with the score's highlighted. Decisions are accept or adjust; there is no
dismiss, since every criterion carries weight. A note rides on an
acceptance only (an adjustment's rationale is its note).

Adjusting turns the card into the form: the score as a 1–N chooser with
the AI's draft tagged, the AI justification kept in view, and the
rationale written beneath. A changed score needs a rationale and owns its
basis: documented citations curated from the record's snapshot, or "not
evidenced", selectable only at the scale minimum (raising the score off the
floor falls back to documented). ``assets/review-ui.js`` owns the form's
draft and saves an unchanged score as an acceptance.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

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
from pcn_clone.app.review.workspace.messages import SAVE_SCORE
from pcn_clone.app.review.workspace.pills import (
    drafting_pill,
    failed_mark,
    scale_label,
    score_pill,
    sk_lines,
    weight_badge,
)
from pcn_clone.app.review.workspace.records import (
    FieldIndex,
    JsonObject,
    as_list,
    as_object,
    disposition_of,
    status_of,
)
from pcn_clone.app.review.workspace.summary_state import effective_score

Scale = Sequence[Mapping[str, Any]]

INVALID_RESULT = (
    "The score returned for this criterion was internally inconsistent and "
    "was not kept — an application defect, not something a retry can fix. "
    "Completed scores remain readable; please report this."
)

MOVED_ON = (
    "This criterion can no longer be scored: the platform has moved on since "
    "this Concept Note was submitted (its template, prioritisation criteria, "
    "model, or scoring protocol changed). Completed scores remain readable. To "
    "score against the current configuration, submit the project again from "
    "its editor."
)

NOTE_PLACEHOLDER = "Anything worth recording about this score."


def score_card(criterion: JsonObject) -> html.Section:
    """The frame of one criterion's card."""
    return card_frame(
        "criterion",
        str(criterion.get("id", "")),
        str(criterion.get("label", "")),
        note_placeholder=NOTE_PLACEHOLDER,
    )


def score_top(
    criterion: JsonObject,
    scale: Scale,
    state: JsonObject,
    fields: FieldIndex,
    key: str,
) -> html.Div:
    """The card's header and body for ``state``."""
    status = status_of(state)
    title = str(criterion.get("label", ""))
    description = str(criterion.get("description", ""))
    weight = weight_badge(criterion.get("weight", ""))
    if status == "pending":
        return card_top(
            status,
            key,
            title,
            description,
            [weight, drafting_pill("Drafting score")],
            _pending_body(),
        )
    if status == "error":
        return card_top(
            status,
            key,
            title,
            description,
            [weight, failed_mark()],
            error_body(state, INVALID_RESULT, MOVED_ON),
        )
    score = effective_score(state)
    return card_top(
        status,
        key,
        title,
        description,
        [weight, score_pill(score, scale)],
        _score_body(criterion, scale, state, fields),
    )


def score_foot(scale: Scale, state: JsonObject) -> html.Footer | None:
    """The card's decision footer; none until the score has arrived."""
    if status_of(state) != "ok":
        return None
    disposition = disposition_of(state)
    if disposition is None:
        return decision_footer(
            [
                action_button("Accept score", "accept"),
                action_button("Adjust…", "edit", "btn-secondary"),
            ]
        )
    draft = as_object(state.get("scoreFinding")).get("score")
    buttons: list[Component] = []
    if disposition.get("kind") == "adjusted":
        final = disposition.get("finalScore")
        text = (
            f"Adjusted by you — {final} ({_label(scale, final)}) replaces the AI's "
            f"draft of {draft}"
        )
        buttons.append(action_button("Adjust again", "edit", "btn-ghost"))
    else:
        text = f"Accepted as drafted — {draft} ({_label(scale, draft)})"
        if not disposition.get("note"):
            buttons.append(add_note_button())
        buttons.append(action_button("Adjust…", "edit", "btn-ghost"))
    buttons.append(action_button("Change", "change", "btn-ghost"))
    return decided_footer(text, buttons)


def score_reference(state: JsonObject, fields: FieldIndex) -> html.Div | None:
    """What the editor shows while the score is unchanged: the AI draft's
    citations, read-only, or its absent-evidence notice; none before the
    draft exists."""
    if status_of(state) != "ok":
        return None
    basis = as_object(as_object(state.get("scoreFinding")).get("basis"))
    if basis.get("kind") == "not_evidenced":
        return html.Div(not_evidenced_notice())
    refs = [as_object(ref) for ref in as_list(basis.get("evidence"))]
    return html.Div(evidence_tray(len(refs), citation_list(refs, fields)))


def _label(scale: Scale, value: Any) -> str:
    return scale_label(scale, value) or str(value)


def _pending_body() -> html.Div:
    return html.Div(
        className="rv-card-body",
        children=[
            html.P("Why this score", className="rv-section-label"),
            sk_lines(["100%", "88%", "46%"]),
            pending_actions(
                [("Accept score", "btn-primary"), ("Adjust…", "btn-secondary")],
                "One of the descriptors will be selected, with the justification "
                "that supports it.",
            ),
        ],
    )


def _score_body(
    criterion: JsonObject, scale: Scale, state: JsonObject, fields: FieldIndex
) -> html.Div:
    finding = as_object(state.get("scoreFinding"))
    disposition = disposition_of(state)
    adjusted = (
        disposition if disposition and disposition.get("kind") == "adjusted" else None
    )
    owner = adjusted if adjusted is not None else finding
    basis = as_object(owner.get("basis"))
    text = adjusted.get("rationale") if adjusted else finding.get("justification")
    children: list[Component] = [
        html.P(
            "Your justification" if adjusted else "Why this score",
            className="rv-section-label",
        ),
        html.P(str(text or ""), className="rv-prose"),
    ]
    if basis.get("kind") == "documented":
        refs = [as_object(ref) for ref in as_list(basis.get("evidence"))]
        listing = (
            curated_list(refs, fields) if adjusted else citation_list(refs, fields)
        )
        children.append(evidence_tray(len(refs), listing))
    else:
        children.append(not_evidenced_notice())
    children.append(scoring_guide(criterion, scale, effective_score(state)))
    return html.Div(children, className="rv-card-body")


def not_evidenced_notice() -> html.Div:
    """The silence notice: a score at the floor with nothing to cite."""
    return html.Div(
        className="rv-silence",
        children=[
            html.P("Scored on absent evidence", className="rv-silence-title"),
            html.P(
                "The submission is silent on this criterion, so the score sits at "
                "the scale floor. No citation accompanies it — a quote can verify "
                "present text, not prove absence."
            ),
        ],
    )


def scoring_guide(criterion: JsonObject, scale: Scale, score: Any) -> html.Details:
    """Every descriptor for the criterion, ``score``'s highlighted."""
    descriptors = as_object(criterion.get("descriptors"))
    rows = [
        html.Li(
            className="rv-guide-row is-current"
            if entry.get("value") == score
            else "rv-guide-row",
            children=[
                html.Span(str(entry.get("value", "")), className="rv-guide-value"),
                html.Span(
                    className="rv-guide-text",
                    children=[
                        html.Span(
                            str(entry.get("label", "")), className="rv-guide-label"
                        ),
                        html.Span(
                            str(descriptors.get(str(entry.get("value")), "")),
                            className="rv-guide-descriptor",
                        ),
                    ],
                ),
            ],
        )
        for entry in scale
    ]
    return disclosure(
        "Scoring guide",
        html.Span(
            f"All {len(scale)} descriptors for this criterion",
            className="rv-tray-detail",
        ),
        html.Ol(rows, className="rv-guide"),
        class_name="rv-guide-tray",
    )


def scale_choice(name: str, scale: Scale) -> html.Div:
    """The 1–N score chooser; review-ui.js checks the draft's score and tags
    the AI's."""
    return html.Div(
        role="radiogroup",
        className="rv-choice",
        **aria(label="Endorsed score"),
        **data(rv_choice="score"),
        children=[
            html.Label(
                className="rv-choice-option is-scale",
                **data(rv_value=str(entry.get("value", ""))),
                children=[
                    radio_slot(name, str(entry.get("value", ""))),
                    html.Span(str(entry.get("value", "")), className="rv-choice-num"),
                    str(entry.get("label", "")),
                    html.Span("AI", className="rv-ai-tag"),
                ],
            )
            for entry in scale
        ],
    )


def basis_choice(name: str) -> html.Div:
    """Documented or not evidenced; review-ui.js disables the latter off the
    scale minimum."""
    return html.Div(
        role="radiogroup",
        className="rv-choice",
        **aria(label="Basis"),
        **data(rv_choice="basis"),
        children=[
            html.Label(
                [radio_slot(name, "documented"), "Documented"],
                className="rv-choice-option is-basis",
            ),
            html.Label(
                [radio_slot(name, "not_evidenced"), "Not evidenced"],
                className="rv-choice-option is-basis",
            ),
        ],
    )


def _when(state: str, *children: Component | str) -> html.Span:
    """Text review-ui.js shows only while the editor is ``changed`` or
    ``unchanged``."""
    return html.Span(list(children), **data(rv_when=state))


def _fill(name: str) -> html.Span:
    """A value review-ui.js writes from the draft or the AI finding."""
    return html.Span(**data(rv_fill=name))


RATIONALE_CHANGED = "Your rationale — required, it replaces the AI justification"
RATIONALE_UNCHANGED = "Your rationale — optional while the score is unchanged"
RATIONALE_MISSING = (
    "An adjusted score needs your rationale — it carries the score in the memo."
)
EVIDENCE_MISSING = (
    "A documented adjustment needs at least one citation — or, at the scale "
    "minimum, mark it not evidenced."
)
BASIS_NOTE = (
    "Not evidenced is available only at the scale minimum — silence cannot earn "
    "more than the floor."
)


def _basis_tray(item: str) -> html.Div:
    detail = html.Span(
        [
            html.Span(
                "Documented — your citations below replace the AI's",
                **data(rv_basis_is="documented"),
            ),
            html.Span(
                "Not evidenced — the submission is silent",
                **data(rv_basis_is="not_evidenced"),
            ),
        ],
        className="rv-tray-detail",
    )
    body = [
        basis_choice(control_id("criterion", item, "basis")),
        html.P(BASIS_NOTE, className="rv-basis-note"),
    ]
    return html.Div(
        disclosure("Basis", detail, body, class_name="is-editing"),
        **data(rv_when="changed"),
    )


def _basis_evidence(item: str, fields: Sequence[JsonObject]) -> html.Div:
    return html.Div(
        [
            html.Span("Evidence", className="rv-editor-label"),
            evidence_editor(
                "criterion",
                item,
                fields,
                empty_state=html.P(EVIDENCE_MISSING, className="rv-field-error"),
                note_placeholder="Why this answer supports your score.",
            ),
        ],
        className="rv-basis-evidence",
        **data(rv_when="documented"),
    )


def score_editor(
    criterion: JsonObject,
    scale: Scale,
    fields: Sequence[JsonObject],
    reference: Component | None,
) -> html.Div:
    """The card as the form over the record's field snapshot, with the AI
    draft's ``reference`` (:func:`score_reference`) shown while the score is
    unchanged."""
    item = str(criterion.get("id", ""))
    rationale = control_id("criterion", item, "rationale")
    head = [
        html.Div(
            className="rv-card-names",
            children=[
                html.H3(str(criterion.get("label", "")), className="rv-card-title"),
                html.P(str(criterion.get("description", "")), className="rv-card-desc"),
                scale_choice(control_id("criterion", item, "score"), scale),
            ],
        ),
        weight_badge(criterion.get("weight", "")),
    ]
    body = [
        html.Div(
            className="rv-ai-reference",
            children=[
                html.P(
                    ["AI justification for its draft of ", _fill("ai-score")],
                    className="rv-section-label",
                ),
                html.P(**data(rv_fill="ai-justification")),
            ],
        ),
        html.Label(
            [
                _when("changed", RATIONALE_CHANGED),
                _when("unchanged", RATIONALE_UNCHANGED),
            ],
            htmlFor=rationale,
            className="rv-editor-label",
        ),
        html.Textarea(
            id=rationale,
            className="rv-editor-text",
            placeholder="Why this score, against the descriptor you selected.",
            **data(rv_field="rationale"),
        ),
        html.P(
            RATIONALE_MISSING,
            className="rv-field-error",
            hidden=True,
            **data(rv_error="rationale"),
        ),
        _basis_tray(item),
        _basis_evidence(item, fields),
        html.Div(reference, className="rv-item-ref", **data(rv_when="unchanged")),
    ]
    hint = [
        _when(
            "changed",
            "Your score of ",
            _fill("score"),
            " replaces the AI draft of ",
            _fill("ai-score"),
            " in the memo.",
        ),
        _when(
            "unchanged",
            "Saving without a change endorses the AI's score of ",
            _fill("ai-score"),
            ".",
        ),
    ]
    return editor_frame(
        "criterion",
        html.Header(head, className="rv-editor-head is-split"),
        body,
        hint,
        action_button(SAVE_SCORE, "save-score"),
    )
