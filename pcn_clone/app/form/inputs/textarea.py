"""The ``textarea`` kind: one multi-line answer (also every field that
declares no input)."""

from __future__ import annotations

from dash import html

from pcn_clone.app.a11y import aria
from pcn_clone.app.form.ids import title_id
from pcn_clone.app.form.inputs.controls import binding, textarea
from pcn_clone.content.models import TemplateField


def textarea_input(field: TemplateField) -> html.Textarea:
    """A five-line textarea in the global field style, named by the field's
    heading."""
    return textarea(
        "dash-textarea pf-textarea",
        5,
        id=f"pf-input-{field.id}",
        placeholder="Write your answer here…",
        **aria(labelledby=title_id(field.id)),
        **binding(field.id, []),
    )
