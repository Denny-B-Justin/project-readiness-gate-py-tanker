"""The ``worksheet`` kind: the cost table whose rows come from a list field.

``assets/form.js`` draws one row per item of the source list (keyed by the
item's ``_rowId``), labelled by the item and captioned with the calendar
years its cells cover; a row without a start date is disabled and left out
of every total. Row totals, the category summary and its total row are
computed in the browser with the same rules as ``pcn_clone.core.worksheet``.
With no source items the worksheet shows only a hint pointing back to the
source field.
"""

from __future__ import annotations

from dash import html

from pcn_clone.app.a11y import aria, data
from pcn_clone.app.form.ids import title_id
from pcn_clone.app.form.inputs.controls import (
    input_slot,
    prototype_binding,
    select,
)
from pcn_clone.app.form.inputs.narratives import narrative_fields
from pcn_clone.app.icons import icon
from pcn_clone.content.models import (
    ListInput,
    Template,
    TemplateField,
    WorksheetInput,
)
from pcn_clone.core.worksheet import category_options, row_control_label


def _row_noun(field_input: WorksheetInput, source: TemplateField | None) -> str:
    """The source list's label control label (for example "Component")."""
    if source is not None and isinstance(source.input, ListInput):
        label_id = field_input.row_source.label_control_id
        for control in source.input.fields:
            if control.id == label_id:
                return control.label
    return "Item"


def _subhead(title: str, note: str) -> html.Div:
    return html.Div(
        className="pf-subhead",
        children=[
            html.Span(title, className="pf-subhead-title"),
            html.Span(note, className="pf-subhead-note"),
        ],
    )


def _prototype(field_input: WorksheetInput, source_ref: str) -> html.Div:
    group_by = field_input.summary.group_by
    category = row_control_label(field_input, group_by)
    cost_cells = [
        html.Td(
            input_slot(
                "number",
                "pf-num",
                min="0",
                step="any",
                inputmode="decimal",
                placeholder="—",
                **prototype_binding(
                    control_id, row_control_label(field_input, control_id)
                ),
            ),
            className="pf-num-cell",
        )
        for control_id in field_input.row_total.sum
    ]
    row = html.Tr(
        [
            html.Th(
                scope="row",
                children=[
                    html.Span(className="pf-ws-row-label"),
                    html.Span(className="pf-ws-row-years mono"),
                    html.Span(
                        f"Add a start date in {source_ref} to enter costs",
                        role="alert",
                        className="pf-ws-row-warning",
                    ),
                ],
            ),
            *cost_cells,
            html.Td(className="pf-ws-row-total", **data(pf_total="")),
            html.Td(
                select(
                    category_options(field_input),
                    "pf-cell pf-ws-category",
                    **prototype_binding(group_by, category),
                ),
            ),
        ]
    )
    return html.Div(
        html.Table(html.Tbody(row)),
        hidden=True,
        **data(pf_prototype=""),
    )


def _summary(field: TemplateField, field_input: WorksheetInput) -> html.Div:
    category = row_control_label(field_input, field_input.summary.group_by)
    columns = field_input.row_total.sum

    def figures(key: str) -> list[html.Td]:
        return [
            *(html.Td(**data(pf_sum=f"{key}|{column}")) for column in columns),
            html.Td(className="pf-ws-sum-total", **data(pf_sum=f"{key}|")),
        ]

    rows = [
        html.Tr([html.Th(option.label, scope="row"), *figures(option.value)])
        for option in category_options(field_input)
    ]
    if field_input.summary.include_total_row:
        rows.append(
            html.Tr(
                [html.Th("Total", scope="row"), *figures("")],
                className="pf-ws-total-row",
            )
        )
    return html.Div(
        className="pf-table-wrap",
        children=html.Table(
            className="pf-table pf-ws-summary",
            children=[
                html.Thead(
                    html.Tr(
                        [
                            html.Th(category, scope="col"),
                            *(
                                html.Th(row_control_label(field_input, c), scope="col")
                                for c in columns
                            ),
                            html.Th(field_input.row_total.label, scope="col"),
                        ]
                    )
                ),
                html.Tbody(rows, **data(pf_summary=field.id)),
            ],
        ),
    )


def _breakdown(
    field: TemplateField,
    field_input: WorksheetInput,
    source: TemplateField | None,
    source_ref: str,
) -> html.Div:
    """The itemised table: headers here, rows drawn by form.js."""
    noun = html.Th(
        scope="col",
        children=[
            _row_noun(field_input, source),
            html.Span(
                f"from {source.number}" if source else "carried over",
                title=f"Carried over from {source_ref}",
                className="pf-ws-from mono",
            ),
        ],
    )
    costs = [
        html.Th(
            row_control_label(field_input, c), scope="col", className="pf-ws-cost-head"
        )
        for c in field_input.row_total.sum
    ]
    category = row_control_label(field_input, field_input.summary.group_by)
    return html.Div(
        className="pf-table-wrap",
        children=html.Table(
            className="pf-table pf-ws-table",
            children=[
                html.Thead(
                    html.Tr(
                        [
                            noun,
                            *costs,
                            html.Th(
                                field_input.row_total.label,
                                scope="col",
                                className="pf-ws-total-head",
                            ),
                            html.Th(
                                category, scope="col", className="pf-ws-category-head"
                            ),
                        ]
                    )
                ),
                html.Tbody(**data(pf_rows=field.id)),
            ],
        ),
    )


def worksheet_input(
    field: TemplateField, field_input: WorksheetInput, template: Template
) -> html.Div:
    """The breakdown, the category summary, the narratives, the empty-state
    hint and the hidden row prototype."""
    source_spec = field_input.row_source
    source = template.get_field(source_spec.section_id, source_spec.field_id)
    source_ref = f"section {source.number}" if source else "the source section"
    source_label = (
        f"Section {source.number} — {source.title}" if source else "the source section"
    )
    category = row_control_label(field_input, field_input.summary.group_by)
    return html.Div(
        role="group",
        className="pf-worksheet",
        **aria(labelledby=title_id(field.id)),
        **data(pf_worksheet=field.id),
        children=[
            html.Div(
                className="pf-ws-empty",
                children=[
                    icon("info", 16),
                    html.Span(
                        [
                            "Add items in ",
                            html.Strong(source_label),
                            ". They carry over here automatically.",
                        ]
                    ),
                ],
            ),
            html.Div(
                className="pf-ws-body",
                children=[
                    html.P(
                        [
                            "Amounts in ",
                            html.Strong("’000"),  # noqa: RUF001
                            ". Year cells are anchored to each row’s start "  # noqa: RUF001
                            f"date in {source_ref}.",
                        ],
                        className="pf-caption",
                    ),
                    _subhead(
                        "Itemised breakdown",
                        f"Rows carry over from {source_ref}; totals calculate "
                        "automatically.",
                    ),
                    _breakdown(field, field_input, source, source_ref),
                    _subhead(
                        f"{category} summary",
                        "Aggregated automatically from the category assigned to "
                        "each row above.",
                    ),
                    _summary(field, field_input),
                    narrative_fields(field.id, field_input.narrative_fields),
                ],
            ),
            _prototype(field_input, source_ref),
        ],
    )
