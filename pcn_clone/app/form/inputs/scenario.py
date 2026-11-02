"""The ``scenario_comparison`` kind: with/without rows across operating
years, the derived rows beneath them, an optional applicability gate and the
narratives.

The derived cells ("Difference", "Revenue") are computed in the browser by
``assets/form.js`` with the rules of ``pcn_clone.core.scenario``: a blank
cell is absent, not zero, so a derived cell shows "—" until both of its
source cells hold valid amounts. When the gate's answer is not its active
value the entered cells are disabled and every derived cell shows "—".
"""

from __future__ import annotations

from dash import html

from pcn_clone.app.a11y import aria, data
from pcn_clone.app.form.ids import title_id
from pcn_clone.app.form.inputs.controls import binding, input_slot, select
from pcn_clone.app.form.inputs.narratives import narrative_fields
from pcn_clone.content.models import ScenarioComparisonInput, TemplateField


def _gate(
    field: TemplateField, field_input: ScenarioComparisonInput
) -> html.Div | None:
    gate = field_input.applicability
    if gate is None:
        return None
    element_id = f"pf-input-{field.id}-applicability-{gate.id}"
    return html.Div(
        className="pf-gate",
        children=[
            html.Label(gate.label, htmlFor=element_id, className="pf-control-label"),
            select(
                gate.options,
                "pf-input pf-gate-select",
                id=element_id,
                **binding(field.id, ["applicability", gate.id]),
            ),
        ],
    )


def scenario_input(
    field: TemplateField, field_input: ScenarioComparisonInput
) -> html.Div:
    """The gate (when the field has one), the table and the narratives."""
    columns = field_input.columns
    entered = [
        html.Tr(
            [
                html.Th(row.label, scope="row"),
                *(
                    html.Td(
                        input_slot(
                            "number",
                            "pf-num",
                            step="any",
                            inputmode="decimal",
                            placeholder="—",
                            aria_label=f"{row.label} for {column.label}",
                            **binding(field.id, ["rows", row.id, column.id]),
                        ),
                        className="pf-num-cell",
                    )
                    for column in columns
                ),
            ]
        )
        for row in field_input.entered_rows
    ]
    computed = [
        html.Tr(
            [
                html.Th(row.label, scope="row"),
                *(
                    html.Td(**data(pf_computed=f"{row.id}|{column.id}"))
                    for column in columns
                ),
            ],
            className="pf-computed-row",
        )
        for row in field_input.computed_rows
    ]
    return html.Div(
        role="group",
        className="pf-scenario",
        **aria(labelledby=title_id(field.id)),
        **data(pf_scenario=field.id),
        children=[
            _gate(field, field_input),
            html.Div(
                className="pf-table-wrap",
                children=html.Table(
                    className="pf-table pf-scenario-table",
                    children=[
                        html.Colgroup(
                            [
                                html.Col(style={"width": "200px"}),
                                *(html.Col() for _ in columns),
                            ]
                        ),
                        html.Thead(
                            html.Tr(
                                [
                                    html.Th(scope="col"),
                                    *(
                                        html.Th(column.label, scope="col")
                                        for column in columns
                                    ),
                                ]
                            )
                        ),
                        html.Tbody([*entered, *computed]),
                    ],
                ),
            ),
            narrative_fields(field.id, field_input.narrative_fields),
        ],
    )
