"""The sticky bar under the suite header, and the back-to-top button.

Left to right: a "Projects" breadcrumb back to the listing, the project's
title, and the jump menu naming the section in view; then the autosave line
and the Submit button (``pcn_clone.app.review.submit``), ``aria-disabled``
until the draft is restored into the form and ``aria-busy``, its glyph a
spinner, while the review is being created; its hidden description says
why it cannot be used when the draft could not be restored.
A 2.5 px progress fill along the bar's bottom edge tracks the page scroll
through the ``--scroll-progress`` variable. ``assets/form.js`` drives the
menu's current section, the autosave line, the progress fill and the
back-to-top button.
"""

from __future__ import annotations

from typing import Any

import dash_mantine_components as dmc
from dash import dcc, html

from pcn_clone.app.a11y import aria, data
from pcn_clone.app.form.ids import (
    AUTOSAVE,
    BACK_TO_TOP,
    JUMP_ITEM,
    JUMP_NUMBER,
    JUMP_TITLE,
    JUMP_TRIGGER,
    SUBMIT,
    SUBMIT_HINT,
    section_id,
)
from pcn_clone.app.form.messages import AUTOSAVE_IDLE, JUMP_CURRENT, JUMP_LABEL
from pcn_clone.app.icons import icon
from pcn_clone.app.routing import page_url
from pcn_clone.content.models import Section


def jump_label(section: Section) -> str:
    """The trigger's accessible name with ``section`` in view."""
    return JUMP_CURRENT.format(number=section.number, title=section.title)


def jump_item_props(active: bool) -> dict[str, Any]:
    """The props of one jump-menu row; the active row is tinted and ticked."""
    return {
        "className": "pf-jump-item is-active" if active else "pf-jump-item",
        "rightSection": icon("check", 15, weight="bold") if active else None,
    }


def jump_menu(sections: list[Section]) -> dmc.Menu:
    """The jump menu: its trigger shows the section in view; each row
    scrolls to its section."""
    first = sections[0]
    return dmc.Menu(
        width=335,
        offset=8,
        position="bottom-start",
        classNames={"dropdown": "pf-jump-menu", "label": "pf-jump-label"},
        children=[
            dmc.MenuTarget(
                html.Button(
                    id=JUMP_TRIGGER,
                    type="button",
                    className="pf-jump-trigger",
                    **aria(label=jump_label(first)),
                    children=[
                        html.Span(
                            first.number, id=JUMP_NUMBER, className="pf-jump-number"
                        ),
                        html.Span(
                            first.title, id=JUMP_TITLE, className="pf-jump-title"
                        ),
                        icon("chevron-down", 15, class_name="pf-jump-chevron"),
                    ],
                )
            ),
            dmc.MenuDropdown(
                [
                    dmc.MenuLabel(JUMP_LABEL),
                    *(
                        dmc.MenuItem(
                            section.title,
                            id=section_id(JUMP_ITEM, section.id),
                            leftSection=html.Span(
                                section.number, className="pf-jump-item-number"
                            ),
                            **jump_item_props(section is first),
                            **data(pf_jump=section.id),
                        )
                        for section in sections
                    ),
                ]
            ),
        ],
    )


def context_bar(title: str, sections: list[Section]) -> html.Div:
    """The bar for the project called ``title``."""
    return html.Div(
        className="pf-bar",
        **data(sticky_chrome=""),
        children=[
            html.Div(
                className="pf-bar-inner",
                children=[
                    html.Nav(
                        className="pf-bar-start",
                        **aria(label="Breadcrumb"),
                        children=[
                            dcc.Link(
                                "Projects",
                                href=page_url("projects"),
                                className="pf-crumb-link",
                            ),
                            icon("chevron-right", 15, class_name="pf-crumb-sep"),
                            html.Span(
                                title,
                                className="pf-crumb-title",
                                **aria(current="page"),
                            ),
                            icon("chevron-right", 15, class_name="pf-crumb-sep"),
                            jump_menu(sections),
                        ],
                    ),
                    html.Div(
                        className="pf-bar-end",
                        children=[
                            html.P(
                                AUTOSAVE_IDLE,
                                id=AUTOSAVE,
                                role="status",
                                className="pf-autosave",
                                **aria(live="polite"),
                            ),
                            html.Button(
                                [
                                    icon("doc-check", 13),
                                    html.Span(className="spinner pf-submit-spinner"),
                                    html.Span("Submit", className="pf-submit-label"),
                                ],
                                id=SUBMIT,
                                type="button",
                                className="btn btn-sm btn-primary pf-submit",
                                **aria(
                                    label="Submit for assessment",
                                    describedby=SUBMIT_HINT,
                                    disabled="true",
                                    busy="false",
                                ),
                            ),
                            html.Span(id=SUBMIT_HINT, className="sr-only"),
                        ],
                    ),
                ],
            ),
            html.Div(html.Div(className="pf-progress-fill"), className="pf-progress"),
        ],
    )


def back_to_top() -> html.Button:
    """The floating button that returns to the top; hidden (and out of the
    tab order) until the page has scrolled past one viewport."""
    return html.Button(
        icon("arrow-up", 20, weight="bold"),
        id=BACK_TO_TOP,
        type="button",
        tabIndex="-1",
        className="pf-back-to-top",
        **aria(label="Back to top", hidden="true"),
    )
