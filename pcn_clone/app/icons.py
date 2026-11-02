"""The brand icon set as Dash components.

Each glyph is a 24px stroked SVG held in ``assets/icons.css`` and drawn as a
CSS mask over ``currentColor``, so an icon takes the colour of the text
around it and is sized by a single CSS variable.
"""

from __future__ import annotations

from typing import Any, Literal

from dash import html

from pcn_clone.app.a11y import aria

IconName = Literal[
    "alert-triangle",
    "arrow-left",
    "arrow-up",
    "bell",
    "blocks",
    "check",
    "chevron-down",
    "chevron-right",
    "circle-check",
    "close",
    "criteria",
    "doc-check",
    "dot",
    "download",
    "file-text",
    "globe",
    "info",
    "inject",
    "layers",
    "octagon-x",
    "play",
    "plus",
    "sliders",
    "sparkle",
    "template",
    "trash",
    "user",
]
"""Glyphs defined in ``assets/icons.css``."""

IconWeight = Literal["regular", "bold"]
"""Stroke weight: ``regular`` is 2 units, ``bold`` 2.6 (beside bold labels)."""


def icon(
    name: IconName,
    size: float = 16,
    *,
    weight: IconWeight = "regular",
    class_name: str = "",
) -> html.Span:
    """Return the ``name`` glyph as a decorative ``size``-pixel square.

    The span is ``aria-hidden``; give the surrounding control its accessible
    name. ``class_name`` adds classes alongside ``icon``.
    """
    attributes: dict[str, Any] = {"data-icon": name, **aria(hidden="true")}
    if weight == "bold":
        attributes["data-weight"] = "bold"
    return html.Span(
        className=f"icon {class_name}".rstrip(),
        style={"--icon-size": f"{size:g}px"},
        **attributes,
    )
