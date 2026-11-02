"""The narrative prompts under a worksheet or scenario comparison: each an
italic label beside its own textarea."""

from __future__ import annotations

from collections.abc import Sequence

from dash import html

from pcn_clone.app.form.inputs.controls import binding, textarea
from pcn_clone.content.models import Control


def narrative_fields(field_id: str, controls: Sequence[Control]) -> html.Div:
    """One labelled textarea per narrative control, bound to
    ``narratives.<control id>``."""
    return html.Div(
        className="pf-narratives",
        children=[
            html.Div(
                className="pf-narrative",
                children=[
                    html.Label(
                        control.label,
                        htmlFor=f"pf-input-{field_id}-narratives-{control.id}",
                        className="pf-narrative-label",
                    ),
                    textarea(
                        "pf-narrative-input",
                        3,
                        id=f"pf-input-{field_id}-narratives-{control.id}",
                        **binding(field_id, ["narratives", control.id]),
                    ),
                ],
            )
            for control in controls
        ],
    )
