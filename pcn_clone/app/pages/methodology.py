"""The methodology page: how the Readiness Gate works and who governs it.

A static long-form page. Dark bands carry the hero and the two section
introductions (agency configuration, the reviewer's first pass); light
sections carry cards, the two workflow diagrams and the closing outcome
panel. Styles live in ``assets/pages.css`` under the ``meth-`` prefix.

The content is a snapshot of the reference application's page as of
26 August 2026.
"""

from dataclasses import dataclass
from typing import Literal

import dash
from dash import html
from dash.development.base_component import Component

from pcn_clone.app.a11y import aria
from pcn_clone.app.icons import IconName, icon

Verdict = Literal["pass", "notClear", "fail"]

READINESS_DIAGRAM = "methodology/readiness_gate_diagram.png"
CALIBRATION_DIAGRAM = "methodology/calibration_cycle_diagram.png"
"""Diagram paths inside ``assets/``; ``dash.get_asset_url`` makes them URLs."""


@dataclass(frozen=True)
class Role:
    """A user group with its responsibilities."""

    label: str
    icon: IconName
    title: str
    body: str
    actions: tuple[str, ...]


@dataclass(frozen=True)
class ConfigBlock:
    """One input the central PIM agency configures."""

    n: str
    icon: IconName
    title: str
    body: str
    examples: tuple[str, ...]


@dataclass(frozen=True)
class Step:
    """One numbered step of the proponent workflow."""

    n: str
    title: str
    body: str


@dataclass(frozen=True)
class VerdictEntry:
    """What a field-level readiness verdict means."""

    verdict: Verdict
    title: str
    detail: str


@dataclass(frozen=True)
class ReviewComponent:
    """One component of the reviewer's first-pass assessment."""

    label: str
    icon: IconName
    title: str
    body: str
    items: tuple[str, ...]


@dataclass(frozen=True)
class Principle:
    """An operating principle of the Readiness Gate."""

    icon: IconName
    title: str
    body: str


ROLES: tuple[Role, ...] = (
    Role(
        label="Project preparation",
        icon="user",
        title="Project proponents",
        body=(
            "Line ministries, sub-national governments, state-owned enterprises, "
            "and other project sponsors prepare structured submissions with "
            "guidance available before formal review."
        ),
        actions=(
            "Complete country forms and templates",
            "Review field guidance and assessment criteria",
            "Evaluate, revise, and strengthen responses",
            "Generate a report or submit through existing channels",
        ),
    ),
    Role(
        label="Standards and governance",
        icon="layers",
        title="Central PIM agency",
        body=(
            "The responsible agency defines what a strong submission looks like "
            "and retains control over the standards, calibration process, and "
            "final review decision."
        ),
        actions=(
            "Configure templates, guidance, and criteria",
            "Provide policy and methodological context",
            "Test feedback against reference examples",
            "Approve the configuration for use",
            "Review the first-pass assessment and decide each finding",
        ),
    ),
)

CONFIG_BLOCKS: tuple[ConfigBlock, ...] = (
    ConfigBlock(
        n="01",
        icon="template",
        title="Country form or template",
        body=(
            "The structured form proponents complete. A country can use an "
            "existing concept note, screening form, feasibility template, or the "
            "global template as a starting point."
        ),
        examples=("Sections", "Fields", "Country terminology"),
    ),
    ConfigBlock(
        n="02",
        icon="criteria",
        title="Assessment criteria",
        body=(
            "Explicit standards defining what a sufficient, incomplete, weak, or "
            "unclear response looks like for each field."
        ),
        examples=("Per-field criteria", "Expected evidence", "Readiness threshold"),
    ),
    ConfigBlock(
        n="03",
        icon="sliders",
        title="Field guidance",
        body=(
            "Practical instructions that explain what information is expected "
            "before a response is submitted for evaluation."
        ),
        examples=("Question intent", "Required detail", "Common omissions"),
    ),
    ConfigBlock(
        n="04",
        icon="inject",
        title="Policy and methodology context",
        body=(
            "The rules and supporting material used to interpret a response in the "
            "relevant institutional context."
        ),
        examples=("PIM policy", "Methodologies", "Sector guidance"),
    ),
    ConfigBlock(
        n="05",
        icon="sparkle",
        title="Reference examples",
        body=(
            "Previously assessed strong, weak, and unclear responses that allow "
            "the agency to test whether the AI applies its standards consistently."
        ),
        examples=("Expected verdict", "Reviewer explanation", "Calibration set"),
    ),
)

PROPONENT_WORKFLOW: tuple[Step, ...] = (
    Step(
        n="01",
        title="Select a template",
        body=(
            "The proposer starts a project using the relevant country form or the "
            "global Concept Note template."
        ),
    ),
    Step(
        n="02",
        title="Complete the structured form",
        body=(
            "The submission is organised into clear sections and fields so the "
            "user can work through requirements systematically."
        ),
    ),
    Step(
        n="03",
        title="Review guidance and criteria",
        body=(
            "Before answering, the proposer can see what information is expected "
            "and how the response will be assessed."
        ),
    ),
    Step(
        n="04",
        title="Evaluate a response",
        body=(
            "The answer is assessed against the relevant template, guidance, "
            "criteria, and supporting policy or methodology context."
        ),
    ),
    Step(
        n="05",
        title="Strengthen and resubmit",
        body=(
            "The proposer reviews the readiness result, improves the response, "
            "and re-runs the evaluation where needed."
        ),
    ),
    Step(
        n="06",
        title="Generate a report or submit",
        body=(
            "The completed workspace can produce a structured report for an "
            "existing PIMIS, formal review channel, or other government process. "
            "Submission then triggers the automatic first-pass assessment for the "
            "reviewer."
        ),
    ),
)

VERDICT_LABELS: dict[Verdict, str] = {
    "pass": "Pass",
    "notClear": "Not Clear",
    "fail": "Fail",
}

VERDICT_CLASSES: dict[Verdict, str] = {
    "pass": "meth-verdict--pass",
    "notClear": "meth-verdict--nc",
    "fail": "meth-verdict--fail",
}

VERDICT_PILLS: dict[Verdict, str] = {
    "pass": "pill pill-pass",
    "notClear": "pill pill-nc",
    "fail": "pill pill-fail",
}

VERDICTS: tuple[VerdictEntry, ...] = (
    VerdictEntry(
        verdict="pass",
        title="Meets the configured readiness criteria",
        detail=(
            "The response contains the information and evidence expected for this "
            "field. A Pass is a preparation signal, not project approval."
        ),
    ),
    VerdictEntry(
        verdict="notClear",
        title="The available information is ambiguous",
        detail=(
            "The response may contain relevant material, but it is not yet clear "
            "enough to determine whether all criteria are satisfied."
        ),
    ),
    VerdictEntry(
        verdict="fail",
        title="Does not yet meet one or more criteria",
        detail=(
            "Required information is missing, insufficiently supported, or "
            "inconsistent. The feedback identifies what should be strengthened."
        ),
    ),
)

REVIEW_COMPONENTS: tuple[ReviewComponent, ...] = (
    ReviewComponent(
        label="Document assessment",
        icon="criteria",
        title="Assessment findings",
        body=(
            "Screens the submitted document across five properties. Each finding "
            "is presented with its reasoning and quotes drawn from the submission "
            "itself."
        ),
        items=(
            "Completeness & conformity",
            "Internal coherence",
            "Evidence quality",
            "Cost realism",
            "Risk & deliverability",
        ),
    ),
    ReviewComponent(
        label="Relative priority",
        icon="sliders",
        title="Prioritisation scoring",
        body=(
            "Scores the project against four criteria set by the agency, producing "
            "an overall priority signal to inform selection discussions."
        ),
        items=(
            "Urgency and criticality",
            "Expected economic and development impact",
            "Environmental impact",
            "Fiscal affordability and sustainability",
        ),
    ),
)

PRINCIPLES: tuple[Principle, ...] = (
    Principle(
        icon="user",
        title="Human oversight",
        body=(
            "The Readiness Gate supports early preparation. It does not replace "
            "formal review, appraisal, or approval by responsible officials."
        ),
    ),
    Principle(
        icon="criteria",
        title="Country-owned standards",
        body=(
            "Feedback is grounded in the country's own forms, criteria, guidance, "
            "terminology, and policy context."
        ),
    ),
    Principle(
        icon="sparkle",
        title="Model agnostic",
        body=(
            "Different AI models can be tested and selected according to quality, "
            "cost, deployment, data governance, and trust requirements."
        ),
    ),
    Principle(
        icon="check",
        title="Explainable feedback",
        body=(
            "Every readiness result includes reasoning and practical suggestions, "
            "rather than an unexplained score."
        ),
    ),
)

OUTCOMES: tuple[str, ...] = (
    "Clearer expectations for project proponents",
    "Fewer avoidable clarification cycles",
    "More complete and better-structured submissions",
    "Reviews that start from a drafted assessment, not a blank page",
)

HERO_TAGS: tuple[str, ...] = ("Country-configurable", "AI-assisted", "Human-governed")


def _tile(name: IconName, size: float = 20, extra: str = "") -> html.Span:
    """A brand icon on a rounded blue-tint tile."""
    return html.Span(icon(name, size), className=f"meth-tile {extra}".strip())


def _check_list(items: tuple[str, ...], dark: bool = False) -> html.Ul:
    """A list whose items each lead with a check mark."""
    item_class = "meth-outcome" if dark else "meth-check-item"
    list_class = "meth-outcomes" if dark else "meth-check-list"
    return html.Ul(
        [
            html.Li([icon("check"), html.Span(item)], className=item_class)
            for item in items
        ],
        className=list_class,
    )


def _section_head(kicker: str, title: str, sub: str | None = None) -> html.Div:
    """Kicker, section title and an optional lede."""
    children: list[Component] = [
        html.Span(kicker, className="meth-kicker"),
        html.H2(title, className="meth-h2"),
    ]
    if sub:
        children.append(html.P(sub, className="meth-sub"))
    return html.Div(children, className="meth-head")


def _section(children: list[Component], spacing: str = "") -> html.Section:
    """A light, centred content section."""
    return html.Section(children, className=f"meth-section {spacing}".strip())


def _band(kicker: str, title: str, body: str) -> html.Section:
    """A full-bleed dark band that introduces the section after it."""
    return html.Section(
        html.Div(
            [
                html.Span(kicker, className="meth-band-kicker"),
                html.H2(title, className="meth-band-title"),
                html.P(body, className="meth-band-body"),
            ],
            className="meth-wrap",
        ),
        className="meth-band",
    )


def _diagram(asset: str, alt: str, width: int, height: int) -> html.Figure:
    """The ``asset`` diagram image framed on a white rounded panel."""
    return html.Figure(
        html.Img(
            src=dash.get_asset_url(asset),
            alt=alt,
            width=width,
            height=height,
            className="meth-figure-img",
        ),
        className="meth-figure",
    )


def _hero() -> html.Section:
    return html.Section(
        html.Div(
            [
                html.Span("Readiness Gate methodology", className="meth-hero-kicker"),
                html.H1(
                    "Stronger project submissions before formal review",
                    className="meth-hero-title",
                ),
                html.P(
                    "The Readiness Gate turns a country's existing forms, guidance, "
                    "and assessment criteria into a guided digital preparation "
                    "workspace. Project proponents receive structured, field-level "
                    "feedback before submission, while the central PIM agency "
                    "retains control over the standards and final review process. "
                    "When a submission is handed over, those same standards drive a "
                    "first-pass assessment for the reviewer.",
                    className="meth-hero-lede",
                ),
                html.Div(
                    [html.Span(tag, className="meth-hero-tag") for tag in HERO_TAGS],
                    className="meth-hero-tags",
                ),
            ],
            className="meth-wrap",
        ),
        className="meth-hero",
    )


def _why_it_exists() -> html.Section:
    return _section(
        [
            _section_head(
                "Why it exists",
                "Guidance before review, not only after submission",
                "In good-practice PIM systems, a concept note is reviewed at the "
                "pre-appraisal stage before resources are committed to full "
                "feasibility work. Yet project proponents often complete these "
                "forms without a clear view of the evidence, level of detail, or "
                "assessment standard expected. Reviewers then spend scarce expert "
                "time identifying avoidable gaps and requesting revisions.",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Span("Without the gate", className="meth-compare-tag"),
                            html.P(
                                "Requirements may be interpreted differently across "
                                "institutions. Submissions arrive incomplete or weakly "
                                "evidenced, and formal review begins with repeated "
                                "clarification cycles.",
                                className="meth-compare-body",
                            ),
                        ],
                        className="card meth-card-pad",
                    ),
                    html.Div(
                        [
                            html.Span(
                                "With the gate",
                                className="meth-compare-tag meth-compare-tag--with",
                            ),
                            html.P(
                                "Expectations are visible while the form is being "
                                "prepared. Users can identify gaps, improve responses, "
                                "and reach formal review with a stronger and more "
                                "consistent submission.",
                                className="meth-compare-body",
                            ),
                        ],
                        className="card meth-card-pad meth-card--accent",
                    ),
                ],
                className="meth-grid meth-grid--sm2",
            ),
        ]
    )


def _system_overview() -> html.Section:
    return _section(
        [
            _section_head(
                "How it fits",
                "A shared preparation environment for two connected user groups",
                "The Readiness Gate sits upstream of formal review. Proponents "
                "prepare and improve submissions in the web application, while the "
                "central PIM agency defines and calibrates the standards used by "
                "the tool.",
            ),
            _diagram(
                READINESS_DIAGRAM,
                "High-level Readiness Gate workflow between project proponents, the "
                "AI-powered workspace, and the central PIM agency",
                1183,
                412,
            ),
            html.Div(
                html.P(
                    "The readiness result supports preparation. It does not approve "
                    "the project or replace independent review by the responsible "
                    "institution.",
                    className="meth-note-body",
                ),
                className="meth-note",
            ),
        ]
    )


def _feature_card(
    label: str, icon: IconName, title: str, body: str, items: tuple[str, ...]
) -> html.Article:
    """A card with an icon tile, a label, a title, a body and a check list."""
    return html.Article(
        [
            html.Div(
                [_tile(icon), html.Span(label, className="meth-card-label")],
                className="meth-card-head",
            ),
            html.H3(title, className="meth-feature-title"),
            html.P(body, className="meth-feature-body"),
            _check_list(items),
        ],
        className="card meth-card-pad",
    )


def _roles() -> html.Section:
    return _section(
        [
            _section_head("Roles and responsibilities", "Who does what"),
            html.Div(
                [
                    _feature_card(r.label, r.icon, r.title, r.body, r.actions)
                    for r in ROLES
                ],
                className="meth-grid meth-grid--md2",
            ),
        ]
    )


def _agency_configuration() -> html.Section:
    return _band(
        "Agency configuration",
        "What the central PIM agency configures",
        "The tool begins with institutional rules rather than a generic AI "
        "judgement. These inputs establish the standard the AI is expected to "
        "follow.",
    )


def _configuration_blocks() -> html.Section:
    blocks = [
        html.Article(
            [
                html.Div(
                    [
                        _tile(b.icon, 21, "meth-tile--lg"),
                        html.Span(b.n, className="meth-config-n"),
                    ],
                    className="meth-config-lead",
                ),
                html.Div(
                    [
                        html.H3(b.title, className="meth-config-title"),
                        html.P(b.body, className="meth-config-body"),
                    ],
                    className="meth-config-main",
                ),
                html.Div(
                    [html.Span(e, className="meth-config-chip") for e in b.examples],
                    className="meth-config-examples",
                ),
            ],
            className="card meth-card-pad meth-config",
        )
        for b in CONFIG_BLOCKS
    ]
    return _section(
        [
            html.Div(blocks, className="meth-config-stack"),
            html.P(
                "Because the configuration is separate from the application "
                "workflow, forms and guidance can be updated as policy changes "
                "without redesigning the entire system.",
                className="meth-config-foot",
            ),
        ],
        "meth-section--after-band",
    )


def _proponent_workflow() -> html.Section:
    return _section(
        [
            _section_head(
                "Project preparation loop",
                "How proponents use the Readiness Gate",
                "The application gives users a structured path from an initial draft "
                "to a stronger submission ready for formal review.",
            ),
            html.Ol(
                [
                    html.Li(
                        [
                            html.Div(
                                [
                                    html.Span(s.n, className="meth-step-n"),
                                    html.H3(s.title, className="meth-step-title"),
                                ],
                                className="meth-step-head",
                            ),
                            html.P(s.body, className="meth-step-body"),
                        ],
                        className="card meth-card-pad-sm",
                    )
                    for s in PROPONENT_WORKFLOW
                ],
                className="meth-grid meth-grid--md2 meth-grid--tight meth-steps",
            ),
        ],
        "meth-section--spaced",
    )


def _verdict_pill(verdict: Verdict) -> html.Span:
    """The pass / not-clear / fail pill with its leading dot."""
    return html.Span(
        [
            html.Span(className="pill-dot", **aria(hidden="true")),
            VERDICT_LABELS[verdict],
        ],
        className=VERDICT_PILLS[verdict],
    )


def _verdicts() -> html.Section:
    return _section(
        [
            _section_head(
                "Readiness signals",
                "What each field result means",
                "Evaluation happens at field level so gaps are easy to locate and "
                "improve. Every result includes an explanation and practical next "
                "steps.",
            ),
            html.Div(
                [
                    html.Article(
                        [
                            html.Div(
                                _verdict_pill(v.verdict),
                                className="meth-verdict-head",
                            ),
                            html.Div(
                                [
                                    html.H3(v.title, className="meth-verdict-title"),
                                    html.P(v.detail, className="meth-verdict-detail"),
                                ],
                                className="meth-verdict-body",
                            ),
                        ],
                        className=f"card meth-verdict {VERDICT_CLASSES[v.verdict]}",
                    )
                    for v in VERDICTS
                ],
                className="meth-grid meth-grid--sm3",
            ),
        ]
    )


def _reviewer_assessment() -> html.Section:
    return _band(
        "After submission",
        "A first-pass assessment for the reviewer",
        "When a completed submission is handed over for review, the Readiness Gate "
        "automatically runs a first-pass assessment of the document, so review "
        "begins from a structured draft grounded in the agency's own standards.",
    )


def _reviewer_workspace() -> html.Section:
    return _section(
        [
            html.Div(
                [
                    _feature_card(c.label, c.icon, c.title, c.body, c.items)
                    for c in REVIEW_COMPONENTS
                ],
                className="meth-grid meth-grid--md2",
            ),
            html.Div(
                [
                    html.P(
                        "The first pass is a draft, not a decision. The reviewer "
                        "accepts, edits, or dismisses every finding and score, adds "
                        "supporting evidence, and records feedback and assessment "
                        "notes. Nothing is final until the reviewer has decided each "
                        "item.",
                        className="meth-prose-p",
                    ),
                    html.P(
                        "The completed review is exported as a structured assessment "
                        "memo that can be returned to the proponent for revision or "
                        "carried forward through the country's existing formal "
                        "channels. In many PIM systems, prioritisation scoring takes "
                        "place at a later stage, such as project selection; it is "
                        "included in the reviewer workspace to show how the same "
                        "assessment approach can support other PIM processes.",
                        className="meth-prose-p",
                    ),
                ],
                className="meth-prose",
            ),
        ],
        "meth-section--after-band",
    )


def _calibration() -> html.Section:
    return _section(
        [
            _section_head(
                "Calibration and governance",
                "How the agency tests and approves the feedback",
                "Calibration gives the central PIM agency control over how the "
                "Readiness Gate applies its standards. The agency defines the "
                "country form, assessment criteria, guidance, supporting context, "
                "and reference examples that represent strong, weak, and unclear "
                "responses. The AI is then tested against examples that have already "
                "been assessed by experienced reviewers.",
            ),
            _diagram(
                CALIBRATION_DIAGRAM,
                "Calibration cycle showing agency inputs, AI testing, result "
                "comparison, review of differences, adjustment, and approval for use",
                845,
                248,
            ),
            html.Div(
                [
                    html.P(
                        "The tool compares the AI's decisions and explanations with "
                        "the agency's expected assessments. Where they differ, the "
                        "agency can review whether the criteria need to be clearer, "
                        "the guidance or reference examples should be revised, the "
                        "configuration should be adjusted, or a different AI model "
                        "should be tested. This cycle is repeated until the feedback "
                        "is sufficiently aligned with reviewer expectations and "
                        "approved for use with project proponents.",
                        className="meth-prose-p",
                    ),
                    html.P(
                        "Calibration does not transfer decision-making authority to "
                        "the AI. The central PIM agency remains responsible for "
                        "defining the standards, approving the configuration, and "
                        "carrying out final project review. The process can also be "
                        "repeated whenever forms, policies, guidance, or the selected "
                        "AI model change.",
                        className="meth-prose-p",
                    ),
                ],
                className="meth-prose",
            ),
        ],
        "meth-section--spaced",
    )


def _principles() -> html.Section:
    return _section(
        [
            _section_head(
                "Operating principles", "What the Readiness Gate is built on"
            ),
            html.Div(
                [
                    html.Article(
                        [
                            _tile(p.icon, extra="meth-tile--stacked"),
                            html.H3(p.title, className="meth-principle-title"),
                            html.P(p.body, className="meth-principle-body"),
                        ],
                        className="card meth-card-pad-sm",
                    )
                    for p in PRINCIPLES
                ],
                className="meth-grid meth-grid--sm2 meth-grid--lg4",
            ),
        ],
        "meth-section--spaced",
    )


def _outcome() -> html.Section:
    return _section(
        [
            html.Div(
                html.Div(
                    [
                        html.Div(
                            [
                                html.Span(
                                    "Intended outcome", className="meth-outcome-kicker"
                                ),
                                html.H2(
                                    "Better preparation, more valuable review",
                                    className="meth-outcome-title",
                                ),
                                html.P(
                                    "The goal is not to automate project approval. It "
                                    "is to improve the quality, speed, and consistency "
                                    "of what reaches human reviewers.",
                                    className="meth-outcome-body",
                                ),
                            ]
                        ),
                        _check_list(OUTCOMES, dark=True),
                    ],
                    className="meth-outcome-grid",
                ),
                className="meth-outcome-panel",
            )
        ],
        "meth-section--spaced",
    )


def layout() -> html.Div:
    """The full methodology page, from hero to intended outcome."""
    return html.Div(
        [
            _hero(),
            _why_it_exists(),
            _system_overview(),
            _roles(),
            _agency_configuration(),
            _configuration_blocks(),
            _proponent_workflow(),
            _verdicts(),
            _reviewer_assessment(),
            _reviewer_workspace(),
            _calibration(),
            _principles(),
            _outcome(),
        ],
        className="meth-page",
    )
