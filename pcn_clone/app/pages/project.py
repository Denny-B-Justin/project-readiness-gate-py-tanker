"""``?page=project&project_id=…``: the proposer workspace for one Concept
Note, behind the project gate.

The server cannot see the browser's project store, so the page is gated (see
``pcn_clone.app.gate``): it opens in a checking state and renders the
workspace (``pcn_clone.app.form``) only when this device holds a record with
that id for this template; otherwise it shows a not-found panel. Nothing
that writes to the store mounts before the gate reports the project exists.
"""

from __future__ import annotations

from dash import dcc, html
from dash.development.base_component import Component

from pcn_clone.app.form import form_view
from pcn_clone.app.gate import gate_container, register_gate
from pcn_clone.app.projects_data import template_meta
from pcn_clone.app.routing import page_url


def gate_panel(*children: Component, state: str) -> html.Div:
    """A centred panel for the gate's checking and not-found states."""
    return html.Div(className=f"pj-gate pj-gate-{state}", children=list(children))


def checking_panel() -> html.Div:
    """The quiet state shown while the store is being read."""
    return gate_panel(
        html.P("Loading your Concept Note…", className="pj-gate-quiet"),
        state="checking",
    )


def not_found_panel() -> html.Div:
    """The state for a project this device does not hold."""
    return gate_panel(
        html.Div(
            className="card pj-gate-card",
            children=[
                html.P(
                    "This Concept Note couldn’t be found.",  # noqa: RUF001
                    className="pj-gate-title",
                ),
                html.P(
                    "It may have been deleted, or the link points to a project "
                    "that doesn’t exist on this device.",  # noqa: RUF001
                    className="pj-gate-text",
                ),
                dcc.Link(
                    "← Back to Projects",
                    href=page_url("projects"),
                    className="pj-gate-link",
                ),
            ],
        ),
        state="missing",
    )


def layout(project_id: str | None = None) -> Component:
    """The gated project page; it opens in the checking state."""
    return gate_container(
        "project",
        record_type="project",
        record_id=project_id,
        expect={"templateId": template_meta()["templateId"]},
        fields=["id", "title"],
        checking=checking_panel(),
    )


render_gate = register_gate(
    "project",
    found=form_view,
    missing=not_found_panel,
    checking=checking_panel,
)
