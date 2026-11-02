"""Not found: shown for an unknown ``page`` or a page missing its id.

The router (``pcn_clone.app.routing``) falls back to this page.
"""

from __future__ import annotations

from dash import dcc, html

from pcn_clone.app.icons import icon
from pcn_clone.app.routing import HOME, page_url


def layout() -> html.Div:
    """The not-found page, with a link back to Home."""
    return html.Div(
        html.Div(
            [
                html.Span(icon("file-text", 26), className="empty-state-icon"),
                html.H1("Page not found", className="empty-state-title"),
                html.P(
                    "The page you asked for doesn’t exist or has moved.",  # noqa: RUF001
                    className="empty-state-text",
                ),
                html.Div(
                    dcc.Link(
                        "Back to Home",
                        href=page_url(HOME),
                        className="btn btn-secondary btn-md",
                    ),
                    className="empty-state-actions",
                ),
            ],
            className="empty-state",
        ),
        className="page",
    )
