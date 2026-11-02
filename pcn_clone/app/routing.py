"""Query routing: every page is served at the app's root address and chosen
by its query string.

The app can be served under more than one root: on Posit Connect both the
content URL ``/content/<GUID>/`` and a vanity URL such as ``/<app-name>/``
reach it. So the router reads only the query string and ignores the
pathname, and page links are relative query URLs (``?page=projects``) that
resolve against whichever root the visitor arrived at. Assets, callbacks
and the WebSocket keep Dash's configured prefix
(``DASH_REQUESTS_PATHNAME_PREFIX``).

``page`` names the page (no ``page`` is Home), and a page that shows one
record takes its id as a further parameter: ``?page=project&project_id=…``,
``?page=review&review_id=…``. A layout receives only the parameters its
page declares. An unknown page, or one missing a required id, gets the
not-found page.

The page table lives in :mod:`pcn_clone.app.pages`, which imports every
page module; the router reads it through :func:`register_router`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final, NamedTuple
from urllib.parse import parse_qsl, urlencode

from dash import Dash, Input, Output
from dash.development.base_component import Component

PAGE_PARAM: Final = "page"
HOME: Final = "home"
"""The page shown when the query names none."""

LOCATION_ID: Final = "page-location"
"""The shell's ``dcc.Location``; its ``search`` drives the router."""

CONTENT_ID: Final = "page-content"
"""The element the selected page's layout is rendered into."""

STATE_ID: Final = "page-state"
"""The store holding the selected page's title and header link."""


class Page(NamedTuple):
    """One entry of the page table."""

    layout: Callable[..., Component]
    title: str
    """The document title while the page is shown."""
    section: str | None
    """The page whose header link is marked current, or ``None``."""
    required: tuple[str, ...] = ()
    """Query parameters the page needs; without one it is not found."""
    optional: tuple[str, ...] = ()
    """Further query parameters passed on when present."""


def page_url(page: str, **params: str) -> str:
    """The relative query URL of ``page`` with ``params``, for example
    ``page_url("project", project_id="a b")`` is
    ``"?page=project&project_id=a+b"``."""
    return "?" + urlencode({PAGE_PARAM: page, **params})


def query_params(search: str | None) -> dict[str, str]:
    """The parameters of a ``location.search`` string, the first value of
    each when one is repeated."""
    params: dict[str, str] = {}
    query = (search or "").removeprefix("?")
    for name, value in parse_qsl(query, keep_blank_values=True):
        params.setdefault(name, value)
    return params


def select(
    pages: Mapping[str, Page], not_found: Page, search: str | None
) -> tuple[Page, dict[str, str]]:
    """The page ``search`` selects and the parameters its layout takes:
    ``not_found`` (with none) for an unknown page or a missing or blank
    required parameter."""
    params = query_params(search)
    page = pages.get(params.get(PAGE_PARAM, HOME))
    if page is None or not all(params.get(name) for name in page.required):
        return not_found, {}
    accepted = (*page.required, *page.optional)
    return page, {name: params[name] for name in accepted if name in params}


def page_state(page: Page) -> dict[str, str | None]:
    """What the browser needs about the shown page: its title and the href
    of the header link to mark current."""
    return {
        "title": page.title,
        "nav": page_url(page.section) if page.section is not None else None,
    }


_SET_TITLE: Final = """
function (state) {
    if (state && state.title) document.title = state.title;
}
"""


def register_router(app: Dash, pages: Mapping[str, Page], not_found: Page) -> None:
    """Render the page the URL's query selects whenever it changes, and set
    the document title from it.

    The location sets its ``search`` when it mounts, which runs the router
    for the first page, so the initial call is skipped.
    """

    @app.callback(
        Output(CONTENT_ID, "children"),
        Output(STATE_ID, "data"),
        Input(LOCATION_ID, "search"),
        prevent_initial_call=True,
    )
    def route(search: str | None) -> tuple[Component, dict[str, Any]]:
        page, params = select(pages, not_found, search)
        return page.layout(**params), page_state(page)

    app.clientside_callback(_SET_TITLE, Input(STATE_ID, "data"))
