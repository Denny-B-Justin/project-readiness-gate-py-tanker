"""How each verdict is labelled and coloured, shared by the dialogs drawn
here and (through the client configuration) the footers form.js draws."""

from __future__ import annotations

from typing import Final, Literal, TypedDict

from dash import html

from pcn_clone.app.a11y import aria

VerdictName = Literal["pass", "notClear", "fail"]


class VerdictStyle(TypedDict):
    """A verdict's label and its pill variant class from ``brand.css``."""

    label: str
    pill: str


VERDICTS: Final[dict[VerdictName, VerdictStyle]] = {
    "pass": {"label": "Pass", "pill": "pill-pass"},
    "notClear": {"label": "Not Clear", "pill": "pill-nc"},
    "fail": {"label": "Fail", "pill": "pill-fail"},
}
"""Verdicts in rubric order: what to aim for first, the failure last."""


def verdict_pill(verdict: VerdictName, *, small: bool = False) -> html.Span:
    """The verdict as a tinted pill with its leading dot."""
    style = VERDICTS[verdict]
    size = " pill-sm" if small else ""
    return html.Span(
        [html.Span(className="pill-dot", **aria(hidden="true")), style["label"]],
        className=f"pill {style['pill']}{size} pf-verdict",
    )
