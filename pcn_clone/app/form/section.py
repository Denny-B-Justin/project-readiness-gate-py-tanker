"""One template section: the "SECTION N" eyebrow, the evaluation tally, the
numbered title and the field cards.

The section's ``section-<id>`` anchor is what the jump menu scrolls to and
the scroll-spy watches; its heading takes the focus after a jump. The tally
opens with every field "not evaluated"; ``assets/form.js`` redraws it as
fields are evaluated.
"""

from __future__ import annotations

from dash import html

from pcn_clone.app.a11y import aria
from pcn_clone.app.form.field_card import field_card
from pcn_clone.app.form.ids import TALLY, anchor_id, section_id
from pcn_clone.content.models import CriteriaSet, Section, Template


def idle_tally(count: int) -> list[html.Span]:
    """The tally of a section none of whose ``count`` fields is evaluated."""
    return [
        html.Span(
            [
                html.Span(className="pf-tally-dot", **aria(hidden="true")),
                f"{count} not evaluated",
            ],
            className="pf-tally-item is-idle",
        )
    ]


def section_block(
    section: Section, criteria: CriteriaSet, template: Template
) -> html.Section:
    """The section with a card per field. Raises ``LookupError`` when the
    criteria set has no rubric for one of its fields."""
    cards = []
    for field in section.fields:
        rubric = criteria.get(section.id, field.id)
        if rubric is None:
            raise LookupError(
                f'Criteria set "{criteria.id}" has no rubric for '
                f'"{section.id}/{field.id}".'
            )
        cards.append(field_card(field, rubric, template))
    return html.Section(
        id=anchor_id(section.id),
        className="pf-section",
        children=[
            html.Header(
                className="pf-section-head",
                children=[
                    html.Div(
                        className="pf-section-meta",
                        children=[
                            html.P(f"Section {section.number}", className="pf-eyebrow"),
                            html.Div(
                                idle_tally(len(section.fields)),
                                id=section_id(TALLY, section.id),
                                className="pf-tally",
                            ),
                        ],
                    ),
                    html.H2(
                        f"{section.number}. {section.title}",
                        className="pf-section-title",
                        tabIndex="-1",
                    ),
                ],
            ),
            html.Div(cards, className="pf-fields"),
        ],
    )
