"""The query router: page URLs are relative and encoded, and a query string
selects its page and the parameters that page's layout takes, whatever else
it carries."""

from __future__ import annotations

import pytest

from pcn_clone.app.pages import NOT_FOUND, PAGES
from pcn_clone.app.routing import page_url, query_params, select

ODD_ID = "a b/c&d=e?f#g+h%ü"
"""An id with every character a query string treats specially."""


def test_page_url_is_a_relative_query_url() -> None:
    assert page_url("projects") == "?page=projects"
    assert page_url("projects", new="1") == "?page=projects&new=1"
    assert page_url("project", project_id="abc123") == (
        "?page=project&project_id=abc123"
    )


def test_page_url_encodes_ids_and_select_decodes_them() -> None:
    url = page_url("project", project_id=ODD_ID)

    assert url == "?page=project&project_id=a+b%2Fc%26d%3De%3Ff%23g%2Bh%25%C3%BC"
    assert select(PAGES, NOT_FOUND, url) == (PAGES["project"], {"project_id": ODD_ID})


@pytest.mark.parametrize(
    ("search", "page", "params"),
    [
        ("", "home", {}),
        ("?", "home", {}),
        (None, "home", {}),
        ("?page=home", "home", {}),
        ("?page=projects", "projects", {}),
        ("?page=projects&new=1", "projects", {"new": "1"}),
        ("?page=project&project_id=abc123", "project", {"project_id": "abc123"}),
        ("?page=assess", "assess", {}),
        ("?page=review&review_id=xyz789", "review", {"review_id": "xyz789"}),
        ("?page=release-notes", "release-notes", {}),
        ("?page=methodology", "methodology", {}),
    ],
)
def test_the_url_contract(
    search: str | None, page: str, params: dict[str, str]
) -> None:
    assert select(PAGES, NOT_FOUND, search) == (PAGES[page], params)


@pytest.mark.parametrize(
    "search",
    [
        "?page=nowhere",
        "?page=",
        "?page=Projects",
        "?page=project",
        "?page=project&project_id=",
        "?page=review",
        "?page=review&project_id=abc123",
    ],
)
def test_an_unknown_page_or_a_missing_id_is_not_found(search: str) -> None:
    assert select(PAGES, NOT_FOUND, search) == (NOT_FOUND, {})


def test_parameters_a_page_does_not_take_are_ignored() -> None:
    assert select(PAGES, NOT_FOUND, "?page=home&new=1&project_id=a") == (
        PAGES["home"],
        {},
    )
    assert select(PAGES, NOT_FOUND, "?new=1&view=compact&page=projects") == (
        PAGES["projects"],
        {"new": "1"},
    )
    assert select(PAGES, NOT_FOUND, "?page=project&project_id=a&review_id=b") == (
        PAGES["project"],
        {"project_id": "a"},
    )


def test_a_repeated_parameter_keeps_its_first_value() -> None:
    assert query_params("?page=assess&page=projects&x=") == {"page": "assess", "x": ""}
    assert select(PAGES, NOT_FOUND, "?page=assess&page=projects")[0] is PAGES["assess"]
