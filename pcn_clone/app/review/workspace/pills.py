"""The workspace's small status marks: verdict, score, band, drafting and
queued pills, the weight badge, the decided tick and skeleton lines.

A finding's verdict reads in the reviewer's vocabulary (Inadequate,
Concerns, Adequate), not the proposer's; a score reads as its value in a
solid square beside its scale label; the priority band is the one solid
blue mark, so the derived headline reads differently from every per-item
pill.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from dash import html
from dash.development.base_component import Component

from pcn_clone.app.a11y import aria
from pcn_clone.app.icons import icon

VERDICT_LABELS: Final[dict[str, str]] = {
    "fail": "Inadequate",
    "notClear": "Concerns",
    "pass": "Adequate",
}
"""Reviewer-facing verdict labels, worst first: the editor's chooser order,
so the leftmost option is the one that stops a proposal."""

VERDICT_PILLS: Final[dict[str, str]] = {
    "fail": "pill-fail",
    "notClear": "pill-nc",
    "pass": "pill-pass",
}


def verdict_label(verdict: str) -> str:
    """The reviewer's label for ``verdict``."""
    return VERDICT_LABELS.get(verdict, verdict)


def verdict_pill(verdict: str, *, small: bool = False) -> html.Span:
    """A finding's verdict as a tinted pill with its leading dot."""
    size = " pill-sm" if small else ""
    tone = VERDICT_PILLS.get(verdict, "pill-muted")
    return html.Span(
        [
            html.Span(className="pill-dot", **aria(hidden="true")),
            verdict_label(verdict),
        ],
        className=f"pill {tone}{size}",
    )


def scale_label(scale: Sequence[Mapping[str, Any]], value: Any) -> str | None:
    """The scale's label for ``value``, or None when it is off the scale."""
    return next((str(e["label"]) for e in scale if e.get("value") == value), None)


def score_pill(
    value: Any, scale: Sequence[Mapping[str, Any]], *, small: bool = False
) -> html.Span:
    """A score: its value in a solid square, then its scale label."""
    label = scale_label(scale, value)
    return html.Span(
        [html.Span(str(value), className="rv-score-num"), *([label] if label else [])],
        className="rv-score-pill is-sm" if small else "rv-score-pill",
    )


def band_pill(label: str, *, small: bool = False) -> html.Span:
    """The computed priority band, "<label> priority"."""
    return html.Span(
        f"{label} priority", className="rv-band-pill is-sm" if small else "rv-band-pill"
    )


def spinner(size: int) -> html.Span:
    """The brand spin ring at ``size`` pixels."""
    return html.Span(
        className="spinner",
        style={"--spinner-size": f"{size}px"},
        **aria(hidden="true"),
    )


def drafting_pill(label: str = "Drafting…", *, small: bool = False) -> html.Span:
    """The model is still writing this item."""
    return html.Span(
        [spinner(10 if small else 12), label],
        className="rv-drafting-pill is-sm" if small else "rv-drafting-pill",
    )


def queued_pill(label: str) -> html.Span:
    """A dashed, muted count pill for a surface still waiting on the run."""
    return html.Span(label, className="rv-queued-pill")


def failed_mark(*, small: bool = False) -> html.Span:
    """An item whose run failed."""
    if small:
        return html.Span("Failed", className="rv-failed is-sm")
    return html.Span([icon("alert-triangle", 14), "Failed"], className="rv-failed")


def weight_badge(weight: Any) -> html.Span:
    """A criterion's weight, in mono."""
    return html.Span(f"weight {weight}", className="rv-weight")


def done_tick() -> list[Component]:
    """The green tick beside a decided item, named for assistive tech."""
    return [
        icon("check", 14, weight="bold", class_name="rv-tick"),
        html.Span("Decided", className="sr-only"),
    ]


def sk_lines(widths: Sequence[str]) -> html.Div:
    """Shimmering placeholder lines where model text has not arrived."""
    return html.Div(
        [html.Span(className="rv-sk", style={"width": width}) for width in widths],
        className="rv-sk-lines",
        **aria(hidden="true"),
    )
