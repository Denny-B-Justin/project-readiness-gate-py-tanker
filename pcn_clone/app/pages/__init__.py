"""The app's pages and the table the router reads (see
:mod:`pcn_clone.app.routing`).

Each module here supplies a ``layout`` function and registers its own
callbacks when imported. This package imports every one, once, so their
callbacks register before the app serves its first request.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from pcn_clone.app.pages import (
    assess,
    home,
    methodology,
    not_found_404,
    project,
    projects,
    release_notes,
    review,
)
from pcn_clone.app.routing import HOME, Page

PAGES: Final[Mapping[str, Page]] = {
    HOME: Page(home.layout, "Readiness Gate — PIM-PAM", HOME),
    "projects": Page(
        projects.layout, "Projects — PIM-PAM", "projects", optional=("new",)
    ),
    "project": Page(
        project.layout,
        "Concept Note — PIM-PAM",
        "projects",
        required=("project_id",),
    ),
    "assess": Page(assess.layout, "Assessment — PIM-PAM", "assess"),
    "review": Page(
        review.layout, "Assessment — PIM-PAM", "assess", required=("review_id",)
    ),
    "release-notes": Page(
        release_notes.layout, "Release Notes — PIM-PAM", "release-notes"
    ),
    "methodology": Page(methodology.layout, "Methodology — PIM-PAM", "methodology"),
}
"""Every page by its ``page`` query value: layout, title, the header link it
belongs to (a project under Projects, a review under Assessment) and the
query parameters its layout takes."""

NOT_FOUND: Final = Page(not_found_404.layout, "Page not found — PIM-PAM", None)
"""Shown for an unknown page or a missing id."""
