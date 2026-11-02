"""What ``assets/review-ui.js`` needs to drive the workspace.

The script reads from the configuration built here the component ids it
writes to or finds, the session's store and browser API names, each view's
title (for the open view it publishes) and the view each kind of item is
reviewed in, and the text it shows that is also rendered on this side, so
each is defined once.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from pcn_clone.app.review.workspace import ids, messages
from pcn_clone.app.review.workspace.hub import FINDINGS_TITLE, SCORES_TITLE
from pcn_clone.app.review.workspace.records import LOCATION, LOCATION_MISSING


@cache
def client_config() -> dict[str, Any]:
    """The ``rv-ws-config`` store's data (cached; do not mutate)."""
    return {
        "ids": {
            "root": ids.ROOT,
            "view": ids.VIEW,
            "shape": ids.SHAPE,
            "progress": ids.PROGRESS,
            "editing": ids.EDITING,
            "summary": ids.SUMMARY,
            "autosave": ids.AUTOSAVE,
        },
        "api": ids.SESSION_API,
        "views": {"findings": FINDINGS_TITLE, "scores": SCORES_TITLE},
        "viewOfKind": ids.VIEW_OF_KIND,
        "messages": {
            "autosaveIdle": messages.AUTOSAVE_IDLE,
            "autosaveSaved": messages.AUTOSAVE_SAVED,
            "autosaveFailed": messages.AUTOSAVE_FAILED,
            "citationsOne": messages.CITATIONS_ONE,
            "citationsMany": messages.CITATIONS_MANY,
            "curatedQuote": messages.CURATED_QUOTE,
            "curatedNote": messages.CURATED_NOTE,
            "saving": messages.SAVING,
            "saveEdit": messages.SAVE_EDIT,
            "saveScore": messages.SAVE_SCORE,
            "location": LOCATION,
            "locationMissing": LOCATION_MISSING,
        },
    }
