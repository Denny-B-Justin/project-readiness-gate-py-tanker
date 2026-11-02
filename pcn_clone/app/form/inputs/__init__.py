"""The answer input of a field card, one module per input kind."""

from __future__ import annotations

from dash.development.base_component import Component

from pcn_clone.app.form.inputs.group import group_input
from pcn_clone.app.form.inputs.list_table import list_input
from pcn_clone.app.form.inputs.scenario import scenario_input
from pcn_clone.app.form.inputs.static_table import static_table_input
from pcn_clone.app.form.inputs.text import text_input
from pcn_clone.app.form.inputs.textarea import textarea_input
from pcn_clone.app.form.inputs.worksheet import worksheet_input
from pcn_clone.content.models import (
    GroupInput,
    ListInput,
    ScenarioComparisonInput,
    StaticTableInput,
    Template,
    TemplateField,
    TextInput,
    WorksheetInput,
)


def answer_input(field: TemplateField, template: Template) -> Component:
    """The input that collects ``field``'s answer, chosen by its kind; a
    field without an input is a textarea."""
    field_input = field.input
    if isinstance(field_input, TextInput):
        return text_input(field)
    if isinstance(field_input, GroupInput):
        return group_input(field, field_input)
    if isinstance(field_input, ListInput):
        return list_input(field, field_input)
    if isinstance(field_input, WorksheetInput):
        return worksheet_input(field, field_input, template)
    if isinstance(field_input, ScenarioComparisonInput):
        return scenario_input(field, field_input)
    if isinstance(field_input, StaticTableInput):
        return static_table_input(field, field_input)
    return textarea_input(field)


__all__ = ["answer_input"]
