"""The suite header: the chrome above every page.

A sticky dark bar with the PIM-PAM logo and the top-level pages. From 48rem
up the links sit inline beside the logo; below it they move to a second,
horizontally scrollable row. The link of the page in view (or of the page it
belongs to: a project under Projects, a review under Assessment) is marked
``.active`` (and ``aria-current="page"``) by a clientside callback on the
router's page state, so the header itself never re-renders on navigation.
"""

from __future__ import annotations

from typing import Any, Final, Literal

import dash
from dash import ALL, Dash, Input, Output, dcc, html

from pcn_clone.app.a11y import aria
from pcn_clone.app.routing import HOME, STATE_ID, page_url

LOGO_HREF: Final = "https://pim-pam.net/"

NAV_LINKS: Final[tuple[tuple[str, str], ...]] = (
    ("Home", HOME),
    ("Projects", "projects"),
    ("Assessment", "assess"),
    ("Release Notes", "release-notes"),
    ("Methodology", "methodology"),
)
"""Top-level pages as ``(label, page name)``, in header order."""

NavRow = Literal["main", "compact"]

_MARK_ACTIVE_LINKS: Final = """
function (state) {
    const current = (state && state.nav) || null;
    const isActive = (href) => href === current;
    document.querySelectorAll(".suite-header a.suite-link").forEach((link) => {
        if (isActive(link.getAttribute("href"))) {
            link.setAttribute("aria-current", "page");
        } else {
            link.removeAttribute("aria-current");
        }
    });
    return dash_clientside.callback_context.outputs_list.map((output) =>
        isActive(output.id.href) ? "suite-link active" : "suite-link"
    );
}
"""


def _nav(row: NavRow, class_name: str, label: str) -> html.Nav:
    """One ``.suite-link`` per page, each keyed by href and row."""
    links = [
        dcc.Link(
            text,
            href=page_url(page),
            id={"type": "suite-link", "href": page_url(page), "row": row},
            className="suite-link",
        )
        for text, page in NAV_LINKS
    ]
    return html.Nav(links, className=class_name, **aria(label=label))


def shell_header() -> html.Header:
    """Return the suite header.

    The header carries ``data-sticky-chrome`` so sticky bars further down the
    page can measure the chrome they must clear.
    """
    logo = html.A(
        html.Img(
            src=dash.get_asset_url("logo/pimpam_logo.png"),
            alt="PIM-PAM",
            width=520,
            height=134,
        ),
        href=LOGO_HREF,
        target="_blank",
        rel="noopener noreferrer",
        className="suite-logo",
        **aria(label="PIM-PAM home"),
    )
    sticky_chrome: dict[str, Any] = {"data-sticky-chrome": ""}
    return html.Header(
        [
            html.Div(
                html.Div(
                    [logo, _nav("main", "suite-nav", "Primary")],
                    className="suite-header-start",
                ),
                className="suite-header-row",
            ),
            _nav("compact", "suite-nav-compact", "Primary (compact)"),
        ],
        className="suite-header",
        **sticky_chrome,
    )


def register_shell_callbacks(app: Dash) -> None:
    """Mark the header link for the page in view whenever the router shows a
    page."""
    app.clientside_callback(
        _MARK_ACTIVE_LINKS,
        Output({"type": "suite-link", "href": ALL, "row": ALL}, "className"),
        Input(STATE_ID, "data"),
    )
