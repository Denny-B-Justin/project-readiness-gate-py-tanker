"""The sticky bar under the suite header on a review page.

Left: the breadcrumb, "Assessment" back to the list, then the project's
title and, while a workspace component is open, that component's title (the
project crumb then becomes the way back to the hub). Right: the assessment
details popover and the status line, which ``review.js`` keeps current: the
drafting progress while the run streams, then the first reason the review
is not yet complete, or the ready line.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import dash_mantine_components as dmc
from dash import dcc, html
from dash.development.base_component import Component

from pcn_clone.app.a11y import aria, data
from pcn_clone.app.icons import icon
from pcn_clone.app.review import ids
from pcn_clone.app.routing import page_url

DETAILS_TITLE = "Assessment details"
DETAILS_LEDE = "What this Concept Note was assessed against."

PROVENANCE_FIELDS = (
    "id",
    "projectTitle",
    "templateId",
    "templateLabel",
    "templateVersion",
    "sourceProjectTemplateVersion",
    "assessmentSetId",
    "assessmentSetVersion",
    "mcaSetId",
    "mcaSetVersion",
    "model",
    "submitted",
)
"""What the review gate passes on from the record: its identity, title and
provenance, with ``submitted`` already formatted in the browser's time."""


def crumbs(title: str) -> list[Component]:
    """The breadcrumb trail for the project called ``title``. On the hub the
    project crumb is its title; while a component is open (``rv-part``) it
    becomes a button back to the hub and the component's title follows."""
    return [
        dcc.Link("Assessment", href=page_url("assess"), className="pf-crumb-link"),
        icon("chevron-right", 15, class_name="pf-crumb-sep"),
        html.Span(
            title,
            id=ids.CRUMB_TITLE,
            className="pf-crumb-title",
            **aria(current="page"),
        ),
        html.Button(
            title,
            id=ids.CRUMB_BACK,
            type="button",
            hidden=True,
            className="rv-ctx-back",
        ),
        html.Span(
            id=ids.CRUMB_TAIL,
            hidden=True,
            className="rv-ctx-tail",
            children=[
                icon("chevron-right", 15, class_name="pf-crumb-sep"),
                html.Span(id=ids.CRUMB_PART, **aria(current="page")),
            ],
        ),
    ]


def _row(term: str, value: str, detail: str | None = None) -> html.Div:
    description: list[Component | str] = [value]
    if detail:
        description.append(html.Span(detail, className="rv-prov-id"))
    return html.Div(
        className="rv-prov-row",
        children=[html.Dt(term), html.Dd(description)],
    )


def provenance_rows(review: Mapping[str, Any]) -> list[html.Div]:
    """Template, assessment criteria, prioritisation criteria (when the
    review has an MCA set), model and submitted time."""
    text = {key: str(review.get(key, "")) for key in PROVENANCE_FIELDS}
    rows = [
        _row(
            "Template",
            f"{text['templateLabel']} v{text['templateVersion']}",
            text["templateId"],
        ),
        _row(
            "Assessment criteria",
            f"v{text['assessmentSetVersion']}",
            text["assessmentSetId"],
        ),
    ]
    if review.get("mcaSetId"):
        rows.append(
            _row(
                "Prioritisation criteria (MCA)",
                f"v{text['mcaSetVersion']}",
                text["mcaSetId"],
            )
        )
    rows += [_row("Model", text["model"]), _row("Submitted", text["submitted"])]
    return rows


def drift_note(review: Mapping[str, Any]) -> html.P | None:
    """The note shown when the project was created against another template
    version than the one it was assessed against."""
    source = str(review.get("sourceProjectTemplateVersion", ""))
    assessed = str(review.get("templateVersion", ""))
    if source == assessed:
        return None
    return html.P(
        f"This project was created against template v{source}; it was "
        f"assessed against v{assessed}, the version live at submission.",
        className="rv-prov-note",
    )


def provenance(review: Mapping[str, Any]) -> dmc.Popover:
    """The assessment details popover and its trigger."""
    return dmc.Popover(
        position="bottom-end",
        width=320,
        classNames={"dropdown": "rv-prov"},
        children=[
            dmc.PopoverTarget(
                html.Button(
                    icon("info", 17),
                    id=ids.DETAILS,
                    type="button",
                    className="icon-btn icon-btn-ghost rv-prov-trigger",
                    **aria(label=DETAILS_TITLE),
                )
            ),
            dmc.PopoverDropdown(
                [
                    html.Div(
                        className="rv-prov-head",
                        children=[
                            html.P(DETAILS_TITLE, className="rv-prov-eyebrow"),
                            html.P(DETAILS_LEDE, className="rv-prov-lede"),
                        ],
                    ),
                    html.Dl(provenance_rows(review), className="rv-prov-rows"),
                    drift_note(review),
                ]
            ),
        ],
    )


def context_bar(review: Mapping[str, Any]) -> html.Div:
    """The bar for the review whose gate fields are ``review``."""
    return html.Div(
        className="pf-bar rv-ctx",
        **data(sticky_chrome=""),
        children=html.Div(
            className="pf-bar-inner rv-ctx-inner",
            children=[
                html.Nav(
                    crumbs(str(review.get("projectTitle", ""))),
                    className="pf-bar-start",
                    **aria(label="Breadcrumb"),
                ),
                html.Div(
                    className="rv-ctx-end",
                    children=[
                        provenance(review),
                        html.P(
                            id=ids.STATUS,
                            role="status",
                            className="rv-ctx-status",
                            **aria(live="polite"),
                        ),
                    ],
                ),
            ],
        ),
    )
