"""The text the review session shows, defined once and shipped to
``review.js`` through the client configuration.

Templates name their values in braces (``{label}``, ``{n}``). A count
sentence is a ``(singular, plural)`` pair chosen by ``n``.
"""

from __future__ import annotations

from typing import Final

DRAFTING: Final = "Drafting all {total} sections in parallel — {returned} returned"
"""The status line while any item is still pending."""

READY: Final = "All sections decided — assessment complete"
"""The status line once nothing blocks completion."""

Plural = tuple[str, str]

DIMENSIONS_PENDING: Final[Plural] = (
    "{n} dimension is still being assessed.",
    "{n} dimensions are still being assessed.",
)
CRITERIA_PENDING: Final[Plural] = (
    "{n} criterion is still being scored.",
    "{n} criteria are still being scored.",
)
DIMENSIONS_RETRYABLE: Final[Plural] = (
    "{n} dimension failed — retry it above.",
    "{n} dimensions failed — retry them above.",
)
CRITERIA_RETRYABLE: Final[Plural] = (
    "{n} criterion failed to score — retry it above.",
    "{n} criteria failed to score — retry them above.",
)
DIMENSIONS_MOVED_ON: Final[Plural] = (
    "{n} dimension can no longer be assessed — submit the project again from "
    "its editor.",
    "{n} dimensions can no longer be assessed — submit the project again from "
    "its editor.",
)
CRITERIA_MOVED_ON: Final[Plural] = (
    "{n} criterion can no longer be scored — submit the project again from its editor.",
    "{n} criteria can no longer be scored — submit the project again from its editor.",
)
DIMENSIONS_INVALID: Final[Plural] = (
    "{n} dimension returned an internally inconsistent result — an application "
    "defect; please report it.",
    "{n} dimensions returned an internally inconsistent result — an application "
    "defect; please report it.",
)
CRITERIA_INVALID: Final[Plural] = (
    "{n} criterion returned an internally inconsistent score — an application "
    "defect; please report it.",
    "{n} criteria returned an internally inconsistent score — an application "
    "defect; please report it.",
)
DIMENSIONS_UNDECIDED: Final[Plural] = (
    "{n} finding awaits your decision.",
    "{n} findings await your decision.",
)
CRITERIA_UNDECIDED: Final[Plural] = (
    "{n} score awaits your decision.",
    "{n} scores await your decision.",
)
SUMMARY_BLANK: Final = "The reviewer summary has not been written yet."
SUMMARY_SAVE_FAILED: Final = (
    "The reviewer summary could not be saved on this device — check your "
    "browser's storage settings."
)
SUMMARY_SAVING: Final = "The reviewer summary is still saving."

# --- The run, per item kind ------------------------------------------------------

TRANSPORT_FAILURE: Final = {
    "dimension": "The assessment request could not be completed. Please try again.",
    "criterion": "The scoring request could not be completed. Please try again.",
}
"""An item's message when its call never completed."""

START_FAILURE: Final = {
    "dimension": "The assessment could not start: saving on this device failed.",
    "criterion": "The scoring could not start: saving on this device failed.",
}
"""An item's message when its launch could not be saved."""

INVALID_RESULT: Final = (
    "The returned result was internally inconsistent with this review and was "
    "not saved. This is an application defect."
)
"""An item's message when its result broke the record's invariants."""

RESULT_NOT_SAVED: Final = "The result could not be saved on this device."
"""An item's message when its result could not be stored."""

SUPERSEDED: Final = {
    "dimension": "A superseded result for “{label}” was discarded.",
    "criterion": "A superseded score for “{label}” was discarded.",
}
ARRIVED_LATE: Final = {
    "dimension": (
        "A result for “{label}” arrived after the session was {state} and was "
        "discarded."
    ),
    "criterion": (
        "A score for “{label}” arrived after the session was {state} and was discarded."
    ),
}
SAVE_RESULT_FAILED: Final = {
    "dimension": "Couldn’t save the result for “{label}”",  # noqa: RUF001
    "criterion": "Couldn’t save the score for “{label}”",  # noqa: RUF001
}

IN_REVIEW: Final = "In “{title}”"
"""The headline of a run's notice about a review not on screen; the notice
itself follows as the description."""

# --- Decisions -----------------------------------------------------------------

DECISION_MOVED_ON: Final = (
    "“{label}” had moved on — the view was refreshed; please decide again."
)
DECISION_NOT_SAVED: Final = (
    "Your decision on “{label}” was not saved: the session is {state}."
)
DECISION_SAVE_FAILED: Final = "Couldn’t save your decision on “{label}”"  # noqa: RUF001
DECISION_INVALID: Final = (
    "The decision is inconsistent with this review's record — an application "
    "defect; please report it."
)
DECISION_STORAGE: Final = "Saving on this device failed. Please try again."

SESSION_STATE: Final = {"missing": "deleted", "unreadable": "unreadable"}
"""How a dropped write names the session's state."""

# --- Submit and the list -------------------------------------------------------

SUBMIT_FAILED: Final = "Couldn’t submit for assessment"  # noqa: RUF001
SUBMIT_NO_ANSWER: Final = "The server did not answer. Please try again."
SUBMIT_UNEXPECTED: Final = "The Concept Note could not be frozen for review."
"""Submit's reason when building the snapshot failed unexpectedly."""
DRAFT_NOT_RESTORED: Final = (
    "Your saved draft couldn’t be restored, so this Concept Note can’t be "  # noqa: RUF001
    "submitted. Reload the page to try again."
)
"""Shown when the workspace never finished restoring the draft."""
PROJECT_GONE: Final = "This Concept Note is no longer stored on this device."
DELETED: Final = "Assessment session deleted"
DELETE_FAILED: Final = "Couldn’t delete the session"  # noqa: RUF001
