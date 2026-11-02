"""The field dialogs: guidance, assessment criteria and review notes.

Guidance and criteria are static per field, so each field renders its own
pair, opened from its header pills. The review notes depend on the latest
evaluation, so one shared dialog serves every field and ``assets/form.js``
fills its heading and body when a verdict pill is clicked.

Each dialog's heading is an icon tile beside the dialog name and the field
it concerns ("1.1 Project title"); a visually hidden dash separates number
and title in the dialog's accessible name. None has a close button, as
Escape and a click outside close them. A dialog is not described by its
whole body: form.js removes the description Mantine points at the body.
"""

from __future__ import annotations

from typing import Any

import dash_mantine_components as dmc
from dash import html
from dash.development.base_component import Component

from pcn_clone.app.form.ids import (
    CRITERIA_DIALOG,
    GUIDANCE_DIALOG,
    NOTES_DIALOG,
    field_id,
)
from pcn_clone.app.form.verdicts import VERDICTS, verdict_pill
from pcn_clone.app.icons import IconName, icon
from pcn_clone.content.models import FieldCriteria, TemplateField

CLASS_NAMES: dict[str, str] = {
    "content": "pf-dialog",
    "header": "pf-dialog-header",
    "title": "pf-dialog-heading",
}


def dialog_heading(
    icon_name: IconName, tone: str, title: str, field: TemplateField
) -> list[Component]:
    """An icon tile in ``tone`` (``blue`` or ``slate``), the dialog's name
    and the field's number and title beneath it."""
    return [
        html.Span(icon(icon_name, 16), className=f"pf-dialog-icon is-{tone}"),
        html.Span(
            className="pf-dialog-names",
            children=[
                html.Span(title, className="pf-dialog-title"),
                html.Span(
                    [
                        html.Span(
                            [field.number, html.Span(" — ", className="sr-only")],
                            className="pf-dialog-number",
                        ),
                        field.title,
                    ],
                    className="pf-dialog-field",
                ),
            ],
        ),
    ]


def _dialog(
    dialog_id: Any, title: list[Component], body: Component, **props: Any
) -> dmc.Modal:
    return dmc.Modal(
        id=dialog_id,
        opened=False,
        withCloseButton=False,
        title=title,
        classNames=CLASS_NAMES,
        children=body,
        **props,
    )


def guidance_dialog(field: TemplateField) -> dmc.Modal:
    """The field's guidance prose, line breaks kept."""
    return _dialog(
        field_id(GUIDANCE_DIALOG, field.id),
        dialog_heading("info", "blue", "Field guidance", field),
        html.P(field.guidance, className="pf-dialog-prose"),
    )


def criteria_dialog(field: TemplateField, criteria: FieldCriteria) -> dmc.Modal:
    """The field's rubric: what a Pass, a Not Clear and a Fail each mean."""
    descriptors = {
        "pass": criteria.verdicts.pass_,
        "notClear": criteria.verdicts.not_clear,
        "fail": criteria.verdicts.fail,
    }
    items: list[Component] = []
    for verdict in VERDICTS:
        items.append(html.Dt(verdict_pill(verdict)))
        items.append(html.Dd(descriptors[verdict]))
    return _dialog(
        field_id(CRITERIA_DIALOG, field.id),
        dialog_heading("criteria", "slate", "Assessment criteria", field),
        html.Dl(items, className="pf-rubric"),
    )


def notes_dialog() -> dmc.Modal:
    """The shared review-notes dialog, filled by form.js when opened."""
    return dmc.Modal(
        id=NOTES_DIALOG,
        opened=False,
        withCloseButton=False,
        size=560,
        title=[],
        classNames={**CLASS_NAMES, "content": "pf-dialog pf-notes-dialog"},
        children=[],
    )
