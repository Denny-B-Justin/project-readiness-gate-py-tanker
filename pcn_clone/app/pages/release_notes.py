"""The release notes page: the suite changelog, most recent first.

A dark hero pairs the introduction with a version-anatomy diagram
(``v MAJOR.MINOR.PATCH.stage``, each segment coloured by its release type)
and a legend of the release types; the changelog below lists every release
with its date, version tag, title, type badges and description. Styles live
in ``assets/pages.css`` under the ``rn-`` prefix; the release-type colours
come from the ``--major-*``, ``--minor-*``, ``--patch-*`` and ``--op-*``
brand tokens.

The content is a snapshot of the reference application's page as of
26 August 2026.
"""

from dataclasses import dataclass
from typing import Literal

from dash import html
from dash.development.base_component import Component

ReleaseType = Literal["major", "minor", "patch", "op"]


@dataclass(frozen=True)
class TypeInfo:
    """How a release type is labelled and described."""

    label: str
    desc: str


@dataclass(frozen=True)
class Release:
    """One changelog entry."""

    date: str
    version: str
    types: tuple[ReleaseType, ...]
    title: str
    body: str


TYPES: dict[ReleaseType, TypeInfo] = {
    "major": TypeInfo("Major", "Significant updates to the platform"),
    "minor": TypeInfo("Minor", "Minor changes to UI / UX"),
    "patch": TypeInfo("Patch", "Smaller bug fixes"),
    "op": TypeInfo("Operational pre-release", "Pre-release / testing version"),
}

TYPE_ORDER: tuple[ReleaseType, ...] = ("major", "minor", "patch", "op")

ANATOMY_SEGMENTS: dict[ReleaseType, str] = {
    "major": "1",
    "minor": "0",
    "patch": "0",
    "op": "beta",
}

RELEASES: tuple[Release, ...] = (
    Release(
        date="Aug 25 2026",
        version="v2.2.1.beta",
        types=("patch",),
        title="Template-neutral building blocks",
        body=(
            "A maintenance release. Reworked internal components that had grown "
            "coupled to the original global model PCN into template-neutral, "
            "reusable building blocks, in line with the application's "
            "composability approach to template building. The building blocks also "
            "gained new properties so their labels and descriptions are defined by "
            "the template itself rather than fixed in code."
        ),
    ),
    Release(
        date="Aug 17 2026",
        version="v2.2.0.beta",
        types=("minor", "patch"),
        title="Assessment workspace redesign",
        body=(
            "Rebuilt the assessment workspace. One long scroll becomes a hub with "
            "two openable components — Assessment findings and Prioritisation "
            "scoring — each with progress meters and live status. Findings and "
            "scores now show the content as it will stand in the memo, and editing "
            "happens in the card itself. The nine model calls in a review run now "
            "fan out over HTTP and run in parallel instead of serially. Assessment "
            "also moves into the suite header, reachable from any page."
        ),
    ),
    Release(
        date="Aug 7 2026",
        version="v2.1.0.beta",
        types=("minor",),
        title="Multi-criteria analysis scoring",
        body=(
            "Added multi-criteria analysis to the assessment module. Projects are "
            "scored 1–5 against four weighted criteria — urgency and criticality "
            "(30), expected economic and development impact (30), environmental "
            "impact (20), and fiscal affordability and sustainability (20) — "
            "producing a weighted total, a normalised score, and a priority band. "
            "Each drafted score cites verified evidence or is explicitly marked as "
            "scored on absent evidence. Reviewers accept or adjust every score with "
            "a rationale, and the endorsed result carries into the assessment memo."
        ),
    ),
    Release(
        date="Jul 30 2026",
        version="v2.0.0.beta",
        types=("major",),
        title="Assessment reviewer module",
        body=(
            "Added the reviewer module — the central PIM agency view. A proposer "
            "submits their Project Concept Note for review and the module drafts an "
            "assessment across five core properties: completeness and conformity, "
            "internal coherence, evidence quality, cost realism, and risk and "
            "deliverability. Each finding carries a verdict, its reasoning, and "
            "verified quotes from the submission. The reviewer accepts, edits, or "
            "dismisses every finding, writes a summary, and exports a branded "
            "assessment memo. Export stays blocked until every finding is decided."
        ),
    ),
    Release(
        date="Jul 20 2026",
        version="v1.4.0.beta",
        types=("minor",),
        title="North Macedonia PCN template",
        body=(
            "Added the first country-specific template: the North Macedonia Project "
            "Concept Note, authored from official country PCN material across seven "
            "sections. It sits alongside the global template when starting a new "
            "project and is evaluated against its own dedicated set of quality and "
            "conformity criteria — demonstrating how the module adapts to a "
            "country's requirements without changes to the application itself."
        ),
    ),
    Release(
        date="Jul 16 2026",
        version="v1.3.0.beta",
        types=("minor", "patch"),
        title="New template building blocks & interface refinements",
        body=(
            "Introduced three new structured input building blocks for templates: "
            "an option appraisal for comparing project alternatives, a financial "
            "matrix for structured cost and financing tables, and periodic amounts "
            "for per-period figures with automatic totals. Each is a reusable, "
            "template-driven control with its own validation and PDF-export "
            "rendering, available to any current or future template. The editor "
            "was also refined — the last-saved indicator now sits in the utility "
            "bar next to Export, improving UX."
        ),
    ),
    Release(
        date="Jul 13 2026",
        version="v1.2.0.beta",
        types=("minor",),
        title="Downloadable PDF exports",
        body=(
            "Added downloadable, branded PDF exports as a core application output, "
            "giving users a polished, shareable record of their current Project "
            "Concept Note. Each export is generated in a dedicated web worker, "
            "keeping document rendering responsive and separate from the form."
        ),
    ),
    Release(
        date="Jul 7 2026",
        version="v1.1.0.beta",
        types=("minor",),
        title="Default supported projects",
        body=(
            "Added default supported projects as a guided example for new Concept "
            "Notes. They help users see the template structure, understand the "
            "expected level of detail, and work through a practical example before "
            "starting their own submission."
        ),
    ),
    Release(
        date="Jun 8 2026",
        version="v1.0.0.beta",
        types=("op",),
        title="Initial Beta Release",
        body=(
            "The PIM PCN evaluation module is now available as an operational "
            "pre-release. Proposers can complete a structured Project Concept Note "
            "using the global template across all six sections and receive "
            "AI-assisted, per-field feedback against quality and conformity "
            "criteria — helping strengthen submissions before they reach a human "
            "reviewer."
        ),
    ),
)


def _type_badge(release_type: ReleaseType, dark: bool = False) -> html.Span:
    """A release-type pill; ``dark`` is the variant drawn on the hero."""
    variant = " rn-badge--dark" if dark else ""
    return html.Span(
        [html.Span(className="rn-badge-dot"), TYPES[release_type].label],
        className=f"rn-badge rn-badge--{release_type}{variant}",
    )


def _version_anatomy() -> html.Div:
    """``v 1.0.0.beta`` with per-segment colour, then the release-type legend."""
    digits: list[Component] = [html.Span("v", className="rn-anatomy-v")]
    for index, release_type in enumerate(TYPE_ORDER):
        digits.append(
            html.Span(
                ANATOMY_SEGMENTS[release_type],
                className=f"rn-anatomy-seg rn-anatomy-seg--{release_type}",
            )
        )
        if index < len(TYPE_ORDER) - 1:
            digits.append(html.Span(".", className="rn-anatomy-sep"))
    legend = [
        html.Div(
            [
                _type_badge(release_type, dark=True),
                html.Span(TYPES[release_type].desc, className="rn-legend-desc"),
            ],
            className="rn-legend-row",
        )
        for release_type in TYPE_ORDER
    ]
    return html.Div(
        [
            html.Div(digits, className="rn-anatomy-digits"),
            html.Div(legend, className="rn-legend"),
        ],
        className="rn-anatomy",
    )


def _hero() -> html.Section:
    return html.Section(
        html.Div(
            [
                html.Div(
                    [
                        html.Div(
                            html.Span(
                                "What\N{RIGHT SINGLE QUOTATION MARK}s new",
                                className="rn-hero-kicker",
                            ),
                            className="rn-hero-kicker-row",
                        ),
                        html.H1("Release notes", className="rn-hero-title"),
                        html.P(
                            "Every change to the PIM evaluation module is documented "
                            "here — a brief description of what changed and the date "
                            "it was made. We version each release and use GitHub as "
                            "the version-control system, so changes are tracked over "
                            "time and easy to roll back if needed.",
                            className="rn-hero-lede",
                        ),
                    ],
                    className="rn-hero-intro",
                ),
                _version_anatomy(),
            ],
            className="rn-hero-inner",
        ),
        className="rn-hero",
    )


def _entry(release: Release) -> html.Article:
    return html.Article(
        [
            html.Div(
                [
                    html.Span(release.date, className="rn-entry-date"),
                    html.Span(className="rn-entry-rule"),
                    html.Span(release.version, className="rn-entry-version"),
                ],
                className="rn-entry-meta",
            ),
            html.H2(release.title, className="rn-entry-title"),
            html.Div(
                [_type_badge(t) for t in release.types],
                className="rn-entry-badges",
            ),
            html.P(release.body, className="rn-entry-body"),
        ],
        className="rn-entry",
    )


def layout() -> html.Div:
    """The full release notes page: hero, then the changelog."""
    return html.Div(
        [
            _hero(),
            html.Section(
                html.Div([_entry(r) for r in RELEASES], className="rn-list"),
                className="rn-changelog",
            ),
        ],
        className="rn-page",
    )
