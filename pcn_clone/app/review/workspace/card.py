"""The parts finding cards and score cards share.

A card is drawn once per record load as a frame of regions:

- the *top* (``ITEM_TOP``): the header and body for the item's current
  state, redrawn whenever that state changes; its root carries
  ``data-rv-status`` and ``data-rv-key``, the state it shows;
- the *note* area: the decision note's textarea, shown by review-ui.js
  while a decision carries a note or one is being added, saved on blur;
- the *foot* (``ITEM_FOOT``): the decision footer, redrawn with the top;
- the *editor* slot (``EDITOR``): the in-place form, drawn when the
  reviewer opens it and cleared when it closes, shown instead of the view
  meanwhile; its controls belong to review-ui.js.

The note area sits outside every redrawn region, and an editor is drawn
once per opening and never redrawn while open, so no callback re-renders an
ancestor of a control in use.
"""

from __future__ import annotations

from collections.abc import Sequence

from dash import html
from dash.development.base_component import Component

from pcn_clone.app.a11y import aria, data
from pcn_clone.app.icons import icon
from pcn_clone.app.review.workspace.controls import action_button, input_slot
from pcn_clone.app.review.workspace.ids import (
    EDITOR,
    ITEM_FOOT,
    ITEM_TOP,
    ItemKind,
    anchor_id,
    control_id,
)
from pcn_clone.app.review.workspace.records import JsonObject, as_object


def card_frame(
    kind: ItemKind,
    item: str,
    label: str,
    *,
    note_placeholder: str,
) -> html.Section:
    """The card for one item: its redrawn top and foot around the note
    area, and the slot its editor is drawn into."""
    note_control = control_id(kind, item, "note")
    return html.Section(
        id=anchor_id(kind, item),
        className="rv-card",
        **aria(label=label),
        **data(rv_card=item, rv_kind=kind),
        children=[
            html.Div(
                className="rv-card-view",
                children=[
                    html.Div(
                        id={"type": ITEM_TOP, "kind": kind, "item": item},
                        className="rv-item-top",
                    ),
                    html.Div(
                        className="rv-note",
                        children=[
                            html.Label(
                                "Note recorded with your decision",
                                htmlFor=note_control,
                                className="rv-editor-label",
                            ),
                            html.Textarea(
                                id=note_control,
                                className="rv-note-input",
                                placeholder=note_placeholder,
                                **data(rv_note=""),
                            ),
                        ],
                    ),
                    html.Div(
                        id={"type": ITEM_FOOT, "kind": kind, "item": item},
                        className="rv-item-foot",
                    ),
                ],
            ),
            html.Div(
                id={"type": EDITOR, "kind": kind, "item": item},
                className="rv-card-edit-slot",
            ),
        ],
    )


def card_top(
    status: str,
    key: str,
    title: str,
    description: str,
    marks: Sequence[Component],
    body: Component,
) -> html.Div:
    """A card's header (title, description, status marks) and body for the
    item's ``status``; ``key`` names the state drawn."""
    return html.Div(
        className="rv-top",
        **data(rv_status=status, rv_key=key),
        children=[
            html.Header(
                className="rv-card-head",
                children=[
                    html.Div(
                        className="rv-card-names",
                        children=[
                            html.H3(title, className="rv-card-title"),
                            html.P(description, className="rv-card-desc"),
                        ],
                    ),
                    html.Div(list(marks), className="rv-card-marks"),
                ],
            ),
            body,
        ],
    )


def pending_actions(labels: Sequence[tuple[str, str]], message: str) -> html.Div:
    """The decision strip of an item still drafting: its buttons, disabled,
    and what will arrive."""
    return html.Div(
        className="rv-pending-actions",
        children=[
            html.Div(
                [
                    action_button(label, None, variant, disabled=True)
                    for label, variant in labels
                ],
                className="rv-actions",
                **aria(hidden="true"),
            ),
            html.P(message, className="rv-pending-note"),
        ],
    )


def error_body(state: JsonObject, invalid_result: str, moved_on: str) -> html.Div:
    """A failed item: a retryable failure's message and Retry; a terminal
    one explained, with its message beneath and no Retry, since a retry
    cannot succeed."""
    error = as_object(state.get("error"))
    message = str(state.get("errorMessage", ""))
    if error.get("kind") != "terminal":
        return html.Div(
            className="rv-card-body",
            children=[
                html.P(message, className="rv-error-text"),
                action_button("Retry", "retry", "btn-secondary", class_name="rv-retry"),
            ],
        )
    explanation = invalid_result if error.get("code") == "invalid_result" else moved_on
    return html.Div(
        className="rv-card-body",
        children=[
            html.P(explanation, className="rv-error-text"),
            html.P(message, className="rv-error-detail"),
        ],
    )


def decision_footer(buttons: Sequence[Component]) -> html.Footer:
    """The footer of an undecided item: "Your decision" and its buttons."""
    return html.Footer(
        className="rv-card-foot",
        children=[
            html.Span("Your decision", className="rv-foot-label"),
            html.Div(list(buttons), className="rv-actions"),
        ],
    )


def decided_footer(
    text: str, buttons: Sequence[Component], *, dismissed: bool = False
) -> html.Footer:
    """The footer of a decided item: the decision in one line and what can
    still be done with it."""
    mark = icon("close" if dismissed else "check", 11, weight="bold")
    return html.Footer(
        className="rv-card-foot",
        children=[
            html.Span(
                [html.Span(mark, className="rv-decided-mark"), text],
                className="rv-decided is-dismissed" if dismissed else "rv-decided",
            ),
            html.Div(list(buttons), className="rv-actions"),
        ],
    )


def add_note_button() -> html.Button:
    """Opens the note area; review-ui.js hides it while the note shows."""
    return action_button("Add note", "add-note", "btn-ghost")


def radio_slot(name: str, value: str) -> html.Span:
    """A slot for one visually hidden radio of a chooser."""
    return input_slot(type="radio", name=name, value=value, class_="sr-only")


def editor_frame(
    kind: ItemKind,
    head: Component,
    body: Sequence[Component],
    hint: str | Sequence[Component],
    save: Component,
) -> html.Div:
    """A card as its form: the tinted head, the body, and a footer with
    what saving does beside Save and Cancel. One fieldset holds it all, so
    disabling it locks every control while a save is in flight. Hidden
    until the reviewer edits."""
    return html.Div(
        className="rv-card-edit",
        **data(rv_editor=kind),
        children=html.Fieldset(
            className="rv-editor",
            children=[
                head,
                html.Div(list(body), className="rv-editor-body"),
                html.Footer(
                    className="rv-editor-foot",
                    children=[
                        html.Span(
                            hint if isinstance(hint, str) else list(hint),
                            className="rv-editor-hint",
                        ),
                        html.Div(
                            [save, action_button("Cancel", "cancel-edit", "btn-ghost")],
                            className="rv-actions",
                        ),
                    ],
                ),
            ],
        ),
    )
