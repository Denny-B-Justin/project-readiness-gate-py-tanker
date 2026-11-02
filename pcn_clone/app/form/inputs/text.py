"""The ``text`` kind: one single-line answer."""

from __future__ import annotations

from dash import html

from pcn_clone.app.form.ids import title_id
from pcn_clone.app.form.inputs.controls import binding, input_slot
from pcn_clone.content.models import TemplateField


def text_input(field: TemplateField) -> html.Span:
    """A text box named by the field's heading."""
    return input_slot(
        "text",
        "pf-input",
        id=f"pf-input-{field.id}",
        aria_labelledby=title_id(field.id),
        placeholder="Type your answer…",
        autocomplete="off",
        **binding(field.id, []),
    )
