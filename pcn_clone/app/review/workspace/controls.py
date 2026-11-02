"""Buttons and native-control slots inside the workspace's cards.

``assets/review-ui.js`` handles every card button through one listener,
by the button's ``data-rv-action``. Native inputs are declared as slots: a
``display: contents`` span whose ``data-rv-input`` holds the input's
attributes as JSON, which review-ui.js turns into an ``<input>`` once the
cards are in the page (``dash.html`` has no input element, and an input's
value or checked state belongs to the browser).
"""

from __future__ import annotations

import json

from dash import html

from pcn_clone.app.a11y import data


def action_button(
    label: str,
    action: str | None,
    variant: str = "btn-primary",
    *,
    class_name: str = "",
    disabled: bool = False,
) -> html.Button:
    """A small card button; review-ui.js acts on it by ``action`` (none for
    a placeholder button that never acts)."""
    attributes = data(rv_action=action) if action else {}
    return html.Button(
        label,
        type="button",
        disabled=disabled,
        className=f"btn btn-sm {variant} {class_name}".rstrip(),
        **attributes,
    )


def input_slot(**attributes: str) -> html.Span:
    """A slot review-ui.js fills with an ``<input>`` carrying
    ``attributes`` (``class_`` gives its ``class``)."""
    declared = {name.rstrip("_"): value for name, value in attributes.items()}
    return html.Span(
        className="rv-slot",
        **data(rv_input=json.dumps(declared, separators=(",", ":"))),
    )
