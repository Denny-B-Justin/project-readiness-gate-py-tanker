"""The ``list`` kind: repeatable items as table rows.

Columns come from the list's controls, so two lists differ only by their
controls. The rows themselves are drawn by ``assets/form.js``, one copy of
the hidden prototype row per item, keyed by the item's durable ``_rowId``;
each cell's accessible name pairs its column with the item number ("Risk
factor for Item 2"). With no items the table gives way to "No items added
yet." The add button appends a blank item.
"""

from __future__ import annotations

from dash import html
from dash.development.base_component import Component

from pcn_clone.app.a11y import aria, data
from pcn_clone.app.form.ids import title_id
from pcn_clone.app.form.inputs.controls import (
    input_slot,
    prototype_binding,
    select,
    textarea,
)
from pcn_clone.app.icons import icon
from pcn_clone.content.models import Control, ListInput, TemplateField

COLUMN_WIDTHS: dict[str, dict[str, str]] = {
    "month": {"width": "150px"},
    "select": {"width": "144px"},
    "number": {"width": "100px"},
    "textarea": {"width": "auto", "minWidth": "220px"},
    "text": {"width": "auto", "minWidth": "180px"},
}
"""Column sizing by control type: fixed for selects, months and numbers;
text columns share the rest."""


def _cell_control(control: Control) -> Component:
    bound = prototype_binding(control.id, control.label)
    if control.type == "select":
        return select(control.options, "pf-cell pf-cell-select", **bound)
    if control.type == "textarea":
        return textarea("pf-cell-textarea", 2, **bound)
    return input_slot(control.type, "pf-cell", **bound)


def _prototype(field_input: ListInput) -> html.Div:
    row = html.Tr(
        [
            *(html.Td(_cell_control(control)) for control in field_input.fields),
            html.Td(
                html.Button(
                    icon("trash", 14),
                    type="button",
                    className="icon-btn icon-btn-sm pf-row-remove",
                    **data(pf_remove=""),
                ),
                className="pf-cell-action",
            ),
        ]
    )
    return html.Div(
        html.Table(html.Tbody(row)),
        hidden=True,
        **data(pf_prototype=""),
    )


def list_input(field: TemplateField, field_input: ListInput) -> html.Div:
    """The items table (or its empty state), the add button and the hidden
    row prototype."""
    columns = [html.Col(style=COLUMN_WIDTHS[c.type]) for c in field_input.fields]
    headers = [html.Th(c.label, scope="col") for c in field_input.fields]
    return html.Div(
        role="group",
        className="pf-list",
        **aria(labelledby=title_id(field.id)),
        **data(pf_list=field.id),
        children=[
            html.P("No items added yet.", className="pf-list-empty"),
            html.Div(
                className="pf-table-wrap pf-list-table",
                children=html.Table(
                    className="pf-table pf-list-grid",
                    children=[
                        html.Colgroup([*columns, html.Col(style={"width": "44px"})]),
                        html.Thead(
                            html.Tr(
                                [
                                    *headers,
                                    html.Th(
                                        html.Span("Actions", className="sr-only"),
                                        scope="col",
                                    ),
                                ]
                            )
                        ),
                        html.Tbody(**data(pf_rows=field.id)),
                    ],
                ),
            ),
            html.Button(
                [icon("plus", 15), field_input.add_item_label or "Add item"],
                type="button",
                className="pf-add-item",
                **data(pf_add=field.id),
            ),
            _prototype(field_input),
        ],
    )
