"""The proposer workspace for one project, as the project gate renders it.

Everything the template determines (the sections, field cards and dialogs)
is built once per process and shared by every project's workspace; only the
project stores and the context bar's title are built per project. The
answers themselves never reach the server's layout: form.js restores them
from the browser's draft.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from dash import dcc, html
from dash.development.base_component import Component

from pcn_clone.app.form.config import client_config
from pcn_clone.app.form.context_bar import back_to_top, context_bar
from pcn_clone.app.form.dialogs import notes_dialog
from pcn_clone.app.form.ids import (
    CONFIG,
    FORM_VALUES,
    NAV,
    PROJECT,
    READINESS,
    READINESS_REQUEST,
    ROOT,
    SUBMIT_REQUEST,
    SUBMIT_SNAPSHOT,
)
from pcn_clone.app.form.section import section_block
from pcn_clone.content import load_criteria, load_template


@cache
def template_body() -> tuple[Component, ...]:
    """The template-derived part of every workspace (shared; do not mutate):
    the sections with their field cards, the back-to-top button and the
    review-notes dialog."""
    template = load_template()
    criteria = load_criteria()
    return (
        html.Div(
            [section_block(s, criteria, template) for s in template.sections],
            className="pf-main",
        ),
        back_to_top(),
        notes_dialog(),
    )


def form_view(project: dict[str, Any]) -> list[Component]:
    """The workspace for ``project`` (its ``id`` and ``title``): the
    project, configuration, answer, readiness and Submit stores, the
    location Submit opens the review through, the context bar and the
    template body.

    ``form-values`` opens empty; ``assets/form.js`` fills it with the saved
    draft over the blank defaults once the workspace mounts.
    """
    title = str(project.get("title", ""))
    return [
        dcc.Store(id=PROJECT, data={"id": str(project.get("id", "")), "title": title}),
        dcc.Store(id=CONFIG, data=client_config()),
        dcc.Store(id=FORM_VALUES, storage_type="memory"),
        dcc.Store(id=READINESS_REQUEST, storage_type="memory"),
        dcc.Store(id=READINESS, storage_type="memory"),
        dcc.Store(id=SUBMIT_REQUEST, storage_type="memory"),
        dcc.Store(id=SUBMIT_SNAPSHOT, storage_type="memory"),
        dcc.Location(id=NAV, refresh="callback-nav"),
        html.Div(
            id=ROOT,
            className="pf-root",
            children=[context_bar(title, load_template().sections), *template_body()],
        ),
    ]
