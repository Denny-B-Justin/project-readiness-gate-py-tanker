"""Evidence as both reviewer lenses show it: a verified citation, a
reviewer-curated reference, the collapsed tray they sit in, and the curation
editor.

A model citation shows its location, whether its quote was found verbatim
in the cited answer, the quote, and the answer as the assessor read it
behind a disclosure. A curated reference (the reviewer's own) shows its
location and its optional quote and note, and claims no verification.

The curation editor is drawn once per card and filled by
``assets/review-ui.js``, which owns the citations under edit: it draws each
kept citation from the editor's hidden row prototype, offers the record's
field snapshot in the picker (options valued by their index in it), and
reads the quote and note back when a citation is added.
"""

from __future__ import annotations

from collections.abc import Sequence

from dash import html
from dash.development.base_component import Component

from pcn_clone.app.a11y import data
from pcn_clone.app.icons import icon
from pcn_clone.app.review.workspace.controls import action_button, input_slot
from pcn_clone.app.review.workspace.ids import ItemKind, control_id
from pcn_clone.app.review.workspace.messages import (
    CURATED_NOTE,
    CURATED_QUOTE,
    citations,
)
from pcn_clone.app.review.workspace.records import (
    LOCATION,
    FieldIndex,
    JsonObject,
    location_label,
    ref_key,
)


def disclosure(
    label: str,
    detail: Component | str,
    body: Component | Sequence[Component],
    *,
    class_name: str = "",
) -> html.Details:
    """A collapsed tray: an uppercase label and its detail beside a chevron,
    the body underneath."""
    return html.Details(
        className=f"rv-tray {class_name}".rstrip(),
        children=[
            html.Summary(
                className="rv-tray-summary",
                children=[
                    html.Span(
                        [html.Span(label, className="rv-tray-label"), detail],
                        className="rv-tray-title",
                    ),
                    icon("chevron-down", 16, class_name="rv-tray-chevron"),
                ],
            ),
            html.Div(body, className="rv-tray-body"),
        ],
    )


def evidence_citation(citation: JsonObject, fields: FieldIndex) -> html.Li:
    """One engine-verified citation: location, verification, the quote, and
    the cited answer as assessed."""
    verified = citation.get("verified") is True
    field = fields.get(ref_key(citation))
    children: list[Component] = [
        html.Div(
            className="rv-citation-head",
            children=[
                html.Span(location_label(fields, citation), className="rv-location"),
                html.Span(
                    "Quote verified" if verified else "Quote not found verbatim",
                    className=(
                        "rv-quote-status is-verified"
                        if verified
                        else "rv-quote-status is-unverified"
                    ),
                ),
            ],
        ),
        html.Blockquote(f"“{citation.get('quote', '')}”", className="rv-quote"),
    ]
    if field is not None:
        children.append(
            html.Details(
                className="rv-answer",
                children=[
                    html.Summary("View the answer as assessed"),
                    html.Pre(str(field.get("serializedText", ""))),
                ],
            )
        )
    return html.Li(children, className="rv-citation")


def citation_list(refs: Sequence[JsonObject], fields: FieldIndex) -> html.Ul:
    """Verified citations, in the draft's order."""
    return html.Ul(
        [evidence_citation(ref, fields) for ref in refs],
        className="rv-citations",
    )


def curated_ref(location: str, ref: JsonObject) -> html.Div:
    """One reviewer-curated reference: location, optional quote and note."""
    children: list[Component] = [html.Span(location, className="rv-location")]
    if ref.get("quote"):
        quote = CURATED_QUOTE.format(quote=ref["quote"])
        children.append(html.Span(quote, className="rv-curated-quote"))
    if ref.get("note"):
        note = CURATED_NOTE.format(note=ref["note"])
        children.append(html.Span(note, className="rv-curated-note"))
    return html.Div(children, className="rv-curated")


def curated_list(refs: Sequence[JsonObject], fields: FieldIndex) -> html.Ul:
    """A recorded decision's curated references."""
    return html.Ul(
        [html.Li(curated_ref(location_label(fields, ref), ref)) for ref in refs],
        className="rv-curated-list",
    )


def evidence_tray(count: int, body: Component) -> html.Details:
    """The collapsed "Evidence · N citations" tray."""
    return disclosure(
        "Evidence",
        html.Span(citations(count), className="rv-tray-detail"),
        body,
    )


def _labelled(label: str, control_for: str, control: Component) -> list[Component]:
    return [
        html.Label(label, htmlFor=control_for, className="rv-editor-label"),
        control,
    ]


def evidence_editor(
    kind: ItemKind,
    item: str,
    fields: Sequence[JsonObject],
    *,
    empty_state: Component,
    note_placeholder: str,
) -> html.Div:
    """The curation editor: the kept citations (drawn by review-ui.js), the
    message shown when none is kept, and the add-citation picker over the
    record's field snapshot."""
    field_control = control_id(kind, item, "cite-field")
    quote_control = control_id(kind, item, "cite-quote")
    note_control = control_id(kind, item, "cite-note")
    options = [
        html.Option(
            LOCATION.format(
                section=field.get("sectionLabel", ""), field=field.get("fieldLabel", "")
            ),
            value=str(index),
        )
        for index, field in enumerate(fields)
    ]
    return html.Div(
        className="rv-evidence-editor",
        **data(rv_evidence=""),
        children=[
            html.Ul(className="rv-edit-list", **data(rv_list="")),
            html.Div(empty_state, hidden=True, **data(rv_empty="")),
            html.Div(
                className="rv-add-form",
                hidden=True,
                **data(rv_add_form=""),
                children=[
                    *_labelled(
                        "Cited answer",
                        field_control,
                        html.Select(
                            options, id=field_control, className="rv-editor-input"
                        ),
                    ),
                    *_labelled(
                        "Quote (optional)",
                        quote_control,
                        html.Textarea(
                            id=quote_control,
                            className="rv-editor-textarea is-short",
                            placeholder="An excerpt from the cited answer.",
                        ),
                    ),
                    *_labelled(
                        "Note (optional)",
                        note_control,
                        input_slot(
                            type="text",
                            id=note_control,
                            class_="rv-editor-input",
                            placeholder=note_placeholder,
                        ),
                    ),
                    html.Div(
                        className="rv-actions",
                        children=[
                            action_button(
                                "Add citation", "add-citation", "btn-secondary"
                            ),
                            action_button("Cancel", "cancel-add", "btn-ghost"),
                        ],
                    ),
                ],
            ),
            action_button(
                "Add evidence…", "open-add", "btn-ghost", class_name="rv-open-add"
            ),
            html.Div(
                hidden=True,
                **data(rv_prototype=""),
                children=html.Li(
                    className="rv-edit-row",
                    children=[
                        html.Div(
                            className="rv-curated",
                            children=[
                                html.Span(
                                    className="rv-location", **data(rv_fill="location")
                                ),
                                html.Span(
                                    className="rv-curated-quote",
                                    **data(rv_fill="quote"),
                                ),
                                html.Span(
                                    className="rv-curated-note", **data(rv_fill="note")
                                ),
                            ],
                        ),
                        action_button("Remove", "remove-citation", "btn-ghost"),
                    ],
                ),
            ),
        ],
    )
