"""The ``group`` kind: a fixed set of labelled controls answered once, laid
out two to a row from the ``sm`` breakpoint."""

from __future__ import annotations

from dash import html
from dash.development.base_component import Component

from pcn_clone.app.a11y import aria
from pcn_clone.app.form.ids import title_id
from pcn_clone.app.form.inputs.controls import binding, input_slot, select, textarea
from pcn_clone.content.models import Control, GroupInput, TemplateField


def _control(field_id: str, control: Control) -> Component:
    element_id = f"pf-input-{field_id}-{control.id}"
    bound = binding(field_id, [control.id])
    if control.type == "select":
        return select(control.options, "pf-input", id=element_id, **bound)
    if control.type == "textarea":
        return textarea("dash-textarea pf-textarea", 4, id=element_id, **bound)
    return input_slot(control.type, "pf-input", id=element_id, **bound)


def group_input(field: TemplateField, field_input: GroupInput) -> html.Div:
    """Each control under its own label; the group is named by the field's
    heading."""
    return html.Div(
        role="group",
        className="pf-group",
        **aria(labelledby=title_id(field.id)),
        children=[
            html.Div(
                [
                    html.Label(
                        control.label,
                        htmlFor=f"pf-input-{field.id}-{control.id}",
                        className="pf-control-label",
                    ),
                    _control(field.id, control),
                ],
            )
            for control in field_input.fields
        ],
    )
