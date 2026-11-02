"""Home: the proposer's landing page.

A dark "Readiness gate" masthead with the screening illustration and, below
a rule, links to the three video guides, a three-step "How it works" explainer (Draft,
Evaluate, Strengthen), and a "Get started" call to action into Projects or a
new Concept Note. Styles live in ``assets/home.css`` under the ``home-``
prefix.
"""

from __future__ import annotations

from typing import Final, NamedTuple

import dash
from dash import dcc, html

from pcn_clone.app.icons import IconName, icon
from pcn_clone.app.routing import page_url


class VideoGuide(NamedTuple):
    """One video guide linked from the masthead."""

    title: str
    url: str
    duration: str
    """Length of the video; update it with ``url``."""


VIDEO_GUIDES: Final = (
    VideoGuide("Product walkthrough", "https://vimeo.com/1228876110", "2:08"),
    VideoGuide("Drafting a Concept Note", "https://vimeo.com/1228873814", "1:56"),
    VideoGuide("Reviewing a Concept Note", "https://vimeo.com/1229071373", "2:03"),
)


class Step(NamedTuple):
    """One card of the "How it works" explainer."""

    number: str
    icon: IconName
    title: str
    body: str


STEPS: Final = (
    Step(
        "01",
        "doc-check",
        "Draft",
        "Fill out the structured Concept Note, section by section, in a single"
        " digital template.",
    ),
    Step(
        "02",
        "sparkle",
        "Evaluate",
        "Each field is screened against configurable quality and conformity criteria"
        " as you write.",
    ),
    Step(
        "03",
        "check",
        "Strengthen",
        "Get clear, immediate feedback on what's missing or weak — and improve"
        " it before human review.",
    ),
)


def _masthead() -> html.Section:
    copy = html.Div(
        [
            html.Div(
                html.Span("Project Concept Notes", className="home-kicker"),
                className="home-kicker-row",
            ),
            html.H1("Readiness gate", className="home-title"),
            html.P(
                "The screening step every Concept Note passes through before human"
                " review. Draft, evaluate against the quality criteria, and"
                " strengthen each note until it’s ready.",  # noqa: RUF001
                className="home-lede",
            ),
        ],
        className="home-masthead-copy",
    )
    visual = html.Div(
        html.Img(
            src=dash.get_asset_url("home/masthead.svg"),
            alt=(
                "A Concept Note screened against its criteria: one criterion fails,"
                " three are not yet clear and two pass."
            ),
            width=290,
            height=210,
        ),
        className="home-masthead-visual",
    )
    return html.Section(
        html.Div([copy, visual, _video_guides()], className="home-masthead-inner"),
        className="home-masthead",
    )


def _video_guide(guide: VideoGuide) -> html.Li:
    return html.Li(
        html.A(
            [
                html.Span(icon("play", 14), className="home-guide-play"),
                html.Span(
                    [
                        html.Span(guide.title, className="home-guide-title"),
                        html.Span(" (opens in a new tab)", className="sr-only"),
                        html.Span(guide.duration, className="home-guide-time"),
                    ],
                    className="home-guide-copy",
                ),
            ],
            href=guide.url,
            target="_blank",
            rel="noopener noreferrer",
            className="home-guide",
        )
    )


def _video_guides() -> html.Div:
    return html.Div(
        [
            html.H2("Video guides", className="home-kicker home-guides-title"),
            html.Ul(
                [_video_guide(guide) for guide in VIDEO_GUIDES],
                className="home-guides-list",
            ),
        ],
        className="home-guides",
    )


def _step_card(step: Step) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Span(icon(step.icon, 20), className="home-step-icon"),
                    html.Span(step.number, className="home-step-number"),
                ],
                className="home-step-top",
            ),
            html.H3(step.title, className="home-step-title"),
            html.P(step.body, className="home-step-body"),
        ],
        className="card home-step",
    )


def _how_it_works() -> html.Section:
    return html.Section(
        [
            html.Div(
                [
                    html.Div(
                        html.Span("How it works", className="home-kicker"),
                        className="home-kicker-row",
                    ),
                    html.H2(
                        "Stronger submissions, before they reach a reviewer",
                        className="home-section-title",
                    ),
                ],
                className="home-section-head",
            ),
            html.Div([_step_card(step) for step in STEPS], className="home-steps"),
        ],
        className="home-section home-how",
    )


def _get_started() -> html.Section:
    return html.Section(
        html.Div(
            [
                html.Span(className="home-cta-accent"),
                html.Div(
                    [
                        html.Div(icon("doc-check", 24), className="home-cta-icon"),
                        html.Div(
                            [
                                html.Span(
                                    "Get started", className="eyebrow home-cta-eyebrow"
                                ),
                                html.H3(
                                    "Ready to start a Concept Note?",
                                    className="home-cta-title",
                                ),
                                html.P(
                                    "Pick up an existing draft or begin a new one"
                                    " from the PCN template.",
                                    className="home-cta-text",
                                ),
                            ],
                            className="home-cta-copy",
                        ),
                    ],
                    className="home-cta-lead",
                ),
                html.Div(
                    [
                        dcc.Link(
                            [
                                "View your projects",
                                icon("chevron-right", 15, weight="bold"),
                            ],
                            href=page_url("projects"),
                            className="btn btn-secondary home-cta-btn",
                        ),
                        dcc.Link(
                            [icon("plus", 15, weight="bold"), "New Concept Note"],
                            href=page_url("projects", new="1"),
                            className="btn btn-primary home-cta-btn",
                        ),
                    ],
                    className="home-cta-actions",
                ),
            ],
            className="home-cta",
        ),
        className="home-section home-get-started",
    )


def layout() -> html.Div:
    """The Home page."""
    return html.Div([_masthead(), _how_it_works(), _get_started()], className="home")
