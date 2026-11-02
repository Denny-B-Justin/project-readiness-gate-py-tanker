"""One field card: its number and title, the guidance and criteria pills,
the answer input, the readiness panel and the footer.

The footer's left side (``pf-status``, a polite live region) shows the
field's evaluation state and its right side the Evaluate button;
``assets/form.js`` draws both as the state changes (idle, evaluating,
graded, stale, failed). Each button's accessible name includes the field's
number and title, so the 19 cards' buttons stay distinguishable.

The card also holds the field's evaluation stores (request, response and
running flag) and, for fields whose readiness the server decides, the panel
listing what to complete before evaluating.
"""

from __future__ import annotations

from dash import dcc, html
from dash.development.base_component import Component

from pcn_clone.app.a11y import aria, data
from pcn_clone.app.form.config import LOCAL_READINESS_KINDS
from pcn_clone.app.form.dialogs import criteria_dialog, guidance_dialog
from pcn_clone.app.form.ids import (
    CRITERIA_OPEN,
    EVALUATE,
    EVALUATE_REQUEST,
    EVALUATING,
    EVALUATION,
    GUIDANCE_OPEN,
    ISSUES,
    STATUS,
    field_id,
    title_id,
)
from pcn_clone.app.form.inputs import answer_input
from pcn_clone.app.form.messages import EVALUATE_LABEL, field_action
from pcn_clone.app.icons import IconName, icon
from pcn_clone.content.models import FieldCriteria, Template, TemplateField


def issues_panel(issues: list[str]) -> html.Div:
    """What to complete before the field can be evaluated."""
    return html.Div(
        className="pf-issues",
        children=[
            html.P("Complete the following before evaluating:"),
            html.Ul([html.Li(message) for message in issues]),
        ],
    )


def evaluate_button(field: TemplateField) -> html.Button:
    """The Evaluate button, disabled until the field's readiness is known."""
    return html.Button(
        [icon("sparkle", 15), EVALUATE_LABEL],
        id=field_id(EVALUATE, field.id),
        type="button",
        disabled=True,
        className="btn btn-md btn-primary",
        **aria(label=field_action(EVALUATE_LABEL, field.number, field.title)),
        **data(pf_evaluate=field.id),
    )


def _pill(
    kind: str, icon_name: IconName, label: str, field: TemplateField
) -> html.Button:
    return html.Button(
        [icon(icon_name, 14.5), label],
        id=field_id(kind, field.id),
        type="button",
        className="pill pill-neutral pill-button",
        **aria(label=field_action(label, field.number, field.title)),
    )


def _stores(field: TemplateField) -> list[Component]:
    return [
        dcc.Store(id=field_id(EVALUATE_REQUEST, field.id), storage_type="memory"),
        dcc.Store(id=field_id(EVALUATION, field.id), storage_type="memory"),
        dcc.Store(id=field_id(EVALUATING, field.id), storage_type="memory", data=False),
    ]


def field_card(
    field: TemplateField, criteria: FieldCriteria, template: Template
) -> html.Div:
    """The card for ``field``, with its dialogs and stores."""
    issues = (
        []
        if field.kind in LOCAL_READINESS_KINDS
        else [html.Div(id=field_id(ISSUES, field.id))]
    )
    return html.Div(
        className="card",
        **data(pf_card=field.id, pf_kind=field.kind),
        children=[
            html.Div(
                className="pf-card-head",
                children=[
                    html.Div(
                        className="pf-card-name",
                        children=[
                            html.Span(field.number, className="pf-card-number"),
                            html.H3(
                                field.title,
                                id=title_id(field.id),
                                className="pf-card-title",
                            ),
                        ],
                    ),
                    html.Div(
                        className="pf-card-pills",
                        children=[
                            _pill(GUIDANCE_OPEN, "info", "Field guidance", field),
                            _pill(
                                CRITERIA_OPEN, "criteria", "Assessment criteria", field
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(answer_input(field, template), className="pf-card-input"),
            *issues,
            html.Div(
                className="pf-card-foot",
                children=[
                    html.Div(
                        id=field_id(STATUS, field.id),
                        className="pf-status",
                        **aria(live="polite"),
                    ),
                    evaluate_button(field),
                ],
            ),
            *_stores(field),
            guidance_dialog(field),
            criteria_dialog(field, criteria),
        ],
    )
