"""The native controls every input kind is built from, and their binding.

Answers live in the browser (``assets/form.js``), so controls are plain,
uncontrolled HTML elements that Dash renders once and never updates. Each
bound control carries ``data-pf-field`` (the field id) and ``data-pf-path``
(a JSON array locating its value inside the field's answer; ``[]`` for a
plain text answer); form.js writes the stored value into it on load and
reads it back on every edit.

Inputs must be uncontrolled, with their values owned by the browser, and
months must use the native ``type="month"``: ``dcc.Input`` keeps its value
in Dash and has no month type, and ``dash.html`` has no ``Input``. So an
input is declared as a slot: a ``display: contents`` span whose
``data-pf-input`` attribute holds the input's attributes as JSON. form.js
creates the native ``<input>`` (text, month or number) inside it before
restoring values; where the browser has no month picker, a month input asks
for typed ``YYYY-MM``. No callback writes to an ancestor of a slot, so Dash
never re-renders one; an input that goes missing anyway is created again
with its value. Selects and textareas are Dash's own ``html.Select`` and
``html.Textarea``.

Rows that form.js repeats (list items, worksheet rows) are rendered once as
a hidden prototype; their controls carry ``data-pf-control`` (the control
id) and ``data-pf-label`` (its label, for per-row accessible names) instead
of a binding, which form.js adds to each copy.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Literal

from dash import html

from pcn_clone.app.a11y import data
from pcn_clone.content.models import SelectOption

InputType = Literal["text", "month", "number"]

Path = Sequence[str]
"""Where a control's value sits inside its field's answer."""


def binding(field_id: str, path: Path) -> dict[str, Any]:
    """The attributes that bind a control to ``path`` in a field's answer."""
    return data(
        pf_field=field_id, pf_path=json.dumps(list(path), separators=(",", ":"))
    )


def prototype_binding(control_id: str, label: str) -> dict[str, Any]:
    """The attributes of a control inside a repeated row's prototype."""
    return data(pf_control=control_id, pf_label=label)


def input_slot(
    input_type: InputType, class_name: str, **attributes: str | None
) -> html.Span:
    """A slot form.js fills with ``<input type=input_type>``. Keyword names
    are attribute names with ``_`` for ``-`` (``aria_label`` is
    ``aria-label``); ``None`` values are left out."""
    declared: dict[str, Any] = {"type": input_type, "class": class_name}
    for name, value in attributes.items():
        if value is not None:
            declared[name.replace("_", "-")] = value
    return html.Span(
        className="pf-slot",
        **data(pf_input=json.dumps(declared, separators=(",", ":"))),
    )


def select(
    options: Sequence[SelectOption],
    class_name: str,
    *,
    empty_label: str = "Select…",
    **attributes: Any,
) -> html.Select:
    """A select with a blank first option labelled ``empty_label``."""
    return html.Select(
        [
            html.Option(empty_label, value=""),
            *(html.Option(option.label, value=option.value) for option in options),
        ],
        className=class_name,
        **attributes,
    )


def textarea(class_name: str, rows: int, **attributes: Any) -> html.Textarea:
    """A textarea of ``rows`` lines."""
    return html.Textarea(className=class_name, rows=rows, **attributes)
