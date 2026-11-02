"""The ``static_table`` kind: authored rows filled across typed columns.

When a row's gate column (the first required column) reads "No", the row is
inert: ``assets/form.js`` disables its other cells, except comment
textareas, and its selects show "n/a" instead of "—". Values stay in the
draft; the serializer leaves them out.
"""

from __future__ import annotations

from dash import html
from dash.development.base_component import Component

from pcn_clone.app.a11y import aria, data
from pcn_clone.app.form.ids import title_id
from pcn_clone.app.form.inputs.controls import (
    binding,
    input_slot,
    select,
    textarea,
)
from pcn_clone.content.models import (
    Control,
    StaticTableInput,
    StaticTableRow,
    TemplateField,
)


def _cell(field_id: str, row: StaticTableRow, column: Control) -> Component:
    label = f"{column.label} for {row.label}"
    attributes = {
        **aria(label=label),
        **binding(field_id, ["rows", row.id, column.id]),
    }
    if column.type == "select":
        return select(
            column.options, "pf-cell pf-cell-select", empty_label="—", **attributes
        )
    if column.type == "textarea":
        return textarea(
            "pf-cell-textarea pf-cell-comment",
            1,
            placeholder="Add a comment…",
            **attributes,
        )
    return input_slot(
        column.type,
        "pf-cell",
        aria_label=label,
        **binding(field_id, ["rows", row.id, column.id]),
    )


def static_table_input(field: TemplateField, field_input: StaticTableInput) -> html.Div:
    """The lead sentence and the table."""
    columns = field_input.columns
    return html.Div(
        role="group",
        className="pf-static",
        **aria(labelledby=title_id(field.id)),
        **data(pf_static=field.id),
        children=[
            html.P(
                [
                    "For each item, mark whether it is ",
                    html.Strong("required"),
                    ", its current ",
                    html.Strong("status"),
                    ", the ",
                    html.Strong("expected acquisition date"),
                    " for anything not yet available, and any clarifying comment.",
                ],
                className="pf-caption",
            ),
            html.Div(
                className="pf-table-wrap",
                children=html.Table(
                    className="pf-table pf-static-table",
                    children=[
                        html.Colgroup(
                            [
                                html.Col(style={"width": "240px"}),
                                *(html.Col() for _ in columns),
                            ]
                        ),
                        html.Thead(
                            html.Tr(
                                [
                                    html.Th("Description", scope="col"),
                                    *(
                                        html.Th(
                                            column.label,
                                            scope="col",
                                            className=(
                                                None
                                                if column.type == "textarea"
                                                else "pf-th-center"
                                            ),
                                        )
                                        for column in columns
                                    ),
                                ]
                            )
                        ),
                        html.Tbody(
                            [
                                html.Tr(
                                    [
                                        html.Th(row.label, scope="row"),
                                        *(
                                            html.Td(_cell(field.id, row, column))
                                            for column in columns
                                        ),
                                    ],
                                    **data(pf_row=row.id),
                                )
                                for row in field_input.rows
                            ]
                        ),
                    ],
                ),
            ),
        ],
    )
