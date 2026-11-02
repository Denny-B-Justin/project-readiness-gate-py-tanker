"""Query routing in a real browser: every page is opened at the root address
by its query string, directly or through a link, and keeps its title and
current header link across reloads; the Projects and Assessment tables open
a record from its title (a ``dcc.Link``) and from the rest of its row (the
row-click handler), and Back and Forward return to each; ``new=1`` opens the
create dialog once; unknown pages and missing ids show the not-found page."""

from __future__ import annotations

import json

import pytest

from pcn_clone.app.routing import page_url
from tests.browser.harness import Page
from tests.browser.projects_steps import LIST_READY, open_projects, seed
from tests.browser.review_steps import INPUT, ON_REVIEW_URL, wait_idle

CURRENT_LINKS = """(() => {
  const links = [...document.querySelectorAll(".suite-header a.suite-link")];
  return {
    current: links.filter((a) => a.getAttribute("aria-current") === "page")
      .map((a) => a.textContent),
    active: links.filter((a) => a.classList.contains("active"))
      .map((a) => a.textContent),
  };
})()"""
"""The header links marked current (``aria-current``) and styled active."""

ON_PROJECT_PAGE = "!!document.querySelector('.pf-crumb-title')"
ON_REVIEW_PAGE = "!!document.querySelector('.rv-workspace')"
ASSESS_READY = "!!document.querySelector('#assess-rows tr.row-link')"


def wait_title(page: Page, title: str) -> None:
    page.wait_for(f"document.title === {json.dumps(title)}")


def current_links(page: Page, label: str | None) -> None:
    """Wait until exactly the header link ``label`` (in both rows) is
    current, or none when ``label`` is ``None``."""
    labels = [label, label] if label else []
    expected = json.dumps({"current": labels, "active": labels}, separators=(",", ":"))
    page.wait_for(f"JSON.stringify({CURRENT_LINKS}) === {json.dumps(expected)}")


def back(page: Page) -> None:
    page.js("history.back()")


def forward(page: Page) -> None:
    page.js("history.forward()")


def at(search: str) -> str:
    """An expression true while the address is the root with ``search``."""
    return f"location.pathname === '/' && location.search === {json.dumps(search)}"


@pytest.mark.parametrize(
    ("url", "title", "link", "ready"),
    [
        ("/", "Readiness Gate — PIM-PAM", "Home", ".home"),
        ("/?page=home", "Readiness Gate — PIM-PAM", "Home", ".home"),
        ("/?page=projects", "Projects — PIM-PAM", "Projects", "#projects-empty"),
        ("/?page=assess", "Assessment — PIM-PAM", "Assessment", "#assess-empty"),
        (
            "/?page=release-notes",
            "Release Notes — PIM-PAM",
            "Release Notes",
            ".rn-page",
        ),
        ("/?page=methodology", "Methodology — PIM-PAM", "Methodology", ".meth-page"),
        ("/?page=nowhere", "Page not found — PIM-PAM", None, ".empty-state"),
        ("/?page=project", "Page not found — PIM-PAM", None, ".empty-state"),
        (
            "/?page=review&project_id=x",
            "Page not found — PIM-PAM",
            None,
            ".empty-state",
        ),
        (
            "/?page=project&project_id=nowhere",
            "Concept Note — PIM-PAM",
            "Projects",
            ".pj-gate-missing",
        ),
        (
            "/?page=review&review_id=nowhere",
            "Assessment — PIM-PAM",
            "Assessment",
            ".pj-gate-missing",
        ),
    ],
)
def test_a_direct_link_and_its_reload_show_the_page(
    page: Page, url: str, title: str, link: str | None, ready: str
) -> None:
    present = f"!!document.querySelector({json.dumps(ready)})"
    page.goto(url, ready=present)
    wait_title(page, title)
    current_links(page, link)

    page.reload(ready=present)
    wait_title(page, title)
    current_links(page, link)


def test_the_header_links_keep_the_root_and_mark_the_page(page: Page) -> None:
    page.goto("/", ready="!!document.querySelector('.home')")
    for label, search, title in [
        ("Projects", "?page=projects", "Projects — PIM-PAM"),
        ("Assessment", "?page=assess", "Assessment — PIM-PAM"),
        ("Release Notes", "?page=release-notes", "Release Notes — PIM-PAM"),
        ("Methodology", "?page=methodology", "Methodology — PIM-PAM"),
        ("Home", "?page=home", "Readiness Gate — PIM-PAM"),
    ]:
        page.click(f".suite-nav a.suite-link[href={json.dumps(search)}]")
        page.wait_for(at(search))
        wait_title(page, title)
        current_links(page, label)

    back(page)
    page.wait_for(at("?page=methodology"))
    wait_title(page, "Methodology — PIM-PAM")
    current_links(page, "Methodology")


def test_the_not_found_page_links_home(page: Page) -> None:
    page.goto("/?page=nowhere", ready="!!document.querySelector('.empty-state')")
    page.click(".empty-state-actions a")
    page.wait_for(at("?page=home"))
    wait_title(page, "Readiness Gate — PIM-PAM")
    current_links(page, "Home")


def test_projects_open_from_title_and_row_with_back_and_forward(page: Page) -> None:
    project_id = seed(page, "Bridge Repair", ["Transport"])
    project = page_url("project", project_id=project_id)
    open_projects(page)

    for opener in (".cell-title", ".cell-strong"):
        page.click(f"#projects-rows tr:first-child {opener}")
        page.wait_for(at(project))
        page.wait_for(ON_PROJECT_PAGE)
        wait_title(page, "Concept Note — PIM-PAM")
        current_links(page, "Projects")

        back(page)
        page.wait_for(at("?page=projects"))
        page.wait_for(LIST_READY)
        wait_title(page, "Projects — PIM-PAM")
        assert page.js("document.querySelector('.pf-crumb-title')") is None

        forward(page)
        page.wait_for(at(project))
        page.wait_for(ON_PROJECT_PAGE)
        wait_title(page, "Concept Note — PIM-PAM")

        back(page)
        page.wait_for(at("?page=projects"))
        page.wait_for(LIST_READY)


def test_assessments_open_from_title_and_row_with_back_and_forward(
    page: Page,
) -> None:
    review_id = page.js(f"window.pcnReviews.createReview({json.dumps(INPUT)}).id")
    review = page_url("review", review_id=review_id)
    page.goto("/?page=assess", ready=ASSESS_READY)
    assert page.js("document.querySelector('#assess-rows a').getAttribute('href')") == (
        review
    )

    for opener in (".cell-title", ".as-progress"):
        page.click(f"#assess-rows tr.row-link {opener}")
        page.wait_for(at(review))
        page.wait_for(ON_REVIEW_PAGE)
        wait_title(page, "Assessment — PIM-PAM")
        current_links(page, "Assessment")

        back(page)
        page.wait_for(at("?page=assess"))
        page.wait_for(ASSESS_READY)
        assert page.js(ON_REVIEW_PAGE) is False

        forward(page)
        page.wait_for(at(review))
        page.wait_for(ON_REVIEW_PAGE)

        back(page)
        page.wait_for(at("?page=assess"))
        page.wait_for(ASSESS_READY)

    page.click("#assess-rows tr.row-link .cell-title")
    page.wait_for(ON_REVIEW_URL)
    wait_idle(page, review_id)


def test_new_concept_note_opens_the_dialog_once(page: Page) -> None:
    page.goto("/", ready="!!document.querySelector('.home')")
    page.click(".home-cta-actions a.btn-primary")

    page.wait_for(
        "!!document.querySelector('.mantine-Modal-content #projects-new-title')"
    )
    page.wait_for(at("?page=projects"))
    wait_title(page, "Projects — PIM-PAM")
    current_links(page, "Projects")

    page.reload(ready=LIST_READY)
    assert page.js("!!document.querySelector('.mantine-Modal-content')") is False

    back(page)
    page.wait_for(at(""))
    wait_title(page, "Readiness Gate — PIM-PAM")
