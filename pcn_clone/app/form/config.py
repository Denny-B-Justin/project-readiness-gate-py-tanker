"""What the browser needs to own a project's answers.

``assets/form.js`` holds the answers. It reads from the configuration built
here the blank default of every field, the facts its live calculations
need (worksheet sums and categories, scenario rows and gate, static-table
gate column and inert value, group labels for staleness signatures), where
each field's readiness is decided, the component ids it updates and the
text it shows, so each of those is defined once, on this side.
"""

from __future__ import annotations

from functools import cache
from typing import Any, Final

from pcn_clone.app.form import ids, messages
from pcn_clone.app.form.verdicts import VERDICTS
from pcn_clone.content import load_template
from pcn_clone.content.models import (
    GroupInput,
    ListInput,
    ScenarioComparisonInput,
    StaticTableInput,
    Template,
    TemplateField,
    WorksheetInput,
)
from pcn_clone.core.static_table import STATIC_TABLE_INERT_VALUE
from pcn_clone.core.worksheet import category_options, required_cost_control_ids

LOCAL_READINESS_KINDS: Final = frozenset({"text", "textarea", "group"})
"""Kinds whose readiness is completeness alone (non-blank text, every group
control filled), decided in the browser as the proposer types; the
validator-backed kinds ask the server."""


def field_default(field: TemplateField) -> Any:
    """The blank answer of one field, in its stored shape: ``""`` for text,
    a control-id record for a group, ``[]`` for a list, and the empty
    composite record for a worksheet, scenario comparison or static table."""
    field_input = field.input
    if isinstance(field_input, GroupInput):
        return {control.id: "" for control in field_input.fields}
    if isinstance(field_input, ListInput):
        return []
    if isinstance(field_input, WorksheetInput):
        return {"componentCosts": {}, "narratives": {}}
    if isinstance(field_input, ScenarioComparisonInput):
        return {"applicability": {}, "rows": {}, "narratives": {}}
    if isinstance(field_input, StaticTableInput):
        return {"rows": {}}
    return ""


def _kind_config(field: TemplateField, template: Template) -> dict[str, Any]:
    field_input = field.input
    if isinstance(field_input, GroupInput | ListInput):
        return {
            "controls": [
                {"id": control.id, "label": control.label, "type": control.type}
                for control in field_input.fields
            ]
        }
    if isinstance(field_input, WorksheetInput):
        source = field_input.row_source
        source_field = template.get_field(source.section_id, source.field_id)
        return {
            "rowSource": {
                "sectionId": source.section_id,
                "fieldId": source.field_id,
                "labelControlId": source.label_control_id,
                "startDateControlId": source.start_date_control_id,
                "number": source_field.number if source_field else None,
            },
            "sum": list(field_input.row_total.sum),
            "requiredSpan": len(required_cost_control_ids(field_input)),
            "groupBy": field_input.summary.group_by,
            "categories": [
                {"value": option.value, "label": option.label}
                for option in category_options(field_input)
            ],
            "includeTotalRow": field_input.summary.include_total_row,
        }
    if isinstance(field_input, ScenarioComparisonInput):
        gate = field_input.applicability
        return {
            "gate": (
                None
                if gate is None
                else {"id": gate.id, "activeValue": gate.active_value}
            ),
            "columns": [column.id for column in field_input.columns],
            "enteredRows": [row.id for row in field_input.entered_rows],
            "computedRows": [
                {"id": row.id, "subtract": list(row.subtract)}
                for row in field_input.computed_rows
            ],
        }
    if isinstance(field_input, StaticTableInput):
        required = field_input.required_columns or []
        return {
            "rows": [row.id for row in field_input.rows],
            "columns": [
                {"id": column.id, "type": column.type} for column in field_input.columns
            ],
            "gateColumn": required[0] if required else None,
            "inertValue": STATIC_TABLE_INERT_VALUE,
        }
    return {}


def client_ids() -> dict[str, str]:
    """The component ids (and id prefixes) form.js reads or updates."""
    return {
        "root": ids.ROOT,
        "formValues": ids.FORM_VALUES,
        "autosave": ids.AUTOSAVE,
        "notesDialog": ids.NOTES_DIALOG,
        "backToTop": ids.BACK_TO_TOP,
        "jumpTrigger": ids.JUMP_TRIGGER,
        "jumpNumber": ids.JUMP_NUMBER,
        "jumpTitle": ids.JUMP_TITLE,
        "jumpItem": ids.JUMP_ITEM,
        "tally": ids.TALLY,
        "status": ids.STATUS,
        "evaluate": ids.EVALUATE,
        "evaluateRequest": ids.EVALUATE_REQUEST,
        "evaluation": ids.EVALUATION,
        "evaluating": ids.EVALUATING,
        "readinessRequest": ids.READINESS_REQUEST,
        "anchorPrefix": ids.anchor_id(""),
    }


def client_messages() -> dict[str, str]:
    """The text form.js shows that is also rendered on this side."""
    return {
        "transportFailure": messages.TRANSPORT_FAILURE,
        "evaluate": messages.EVALUATE_LABEL,
        "autosaveIdle": messages.AUTOSAVE_IDLE,
        "jumpCurrent": messages.JUMP_CURRENT,
        "fieldAction": messages.FIELD_ACTION,
    }


@cache
def client_config() -> dict[str, Any]:
    """The ``pf-config`` store's data (cached; do not mutate): the component
    ids and shared text; the verdict labels and pill classes; the sections
    in order with their field ids; and per field its section, number, title,
    kind, where its readiness is decided, blank default and kind-specific
    facts."""
    template = load_template()
    return {
        "ids": client_ids(),
        "messages": client_messages(),
        "verdicts": VERDICTS,
        "sections": [
            {
                "id": section.id,
                "number": section.number,
                "title": section.title,
                "fieldIds": [field.id for field in section.fields],
            }
            for section in template.sections
        ],
        "fields": {
            field.id: {
                "id": field.id,
                "sectionId": section.id,
                "number": field.number,
                "title": field.title,
                "kind": field.kind,
                "readiness": (
                    "local" if field.kind in LOCAL_READINESS_KINDS else "server"
                ),
                "default": field_default(field),
                **_kind_config(field, template),
            }
            for section, field in template.iter_fields()
        },
    }
