"""What the browser needs to run review sessions.

``assets/review.js`` reads the component ids it updates, the text it shows,
the toast styles, the summary's save delay and the run's heartbeat from
the configuration built here, so each is defined once, on this side. The
configuration rides in the ``rv-config`` store of the app shell.

``PCN_REVIEW_HEARTBEAT_SECONDS`` (default 10) sets how often a run reports
that it is still working; a run silent for three of those is taken as lost
(its connection closed) and its items fail with a retryable transport
error.
"""

from __future__ import annotations

import math
import os
from typing import Any, Final

from pcn_clone.app.form.ids import AUTOSAVE, SUBMIT, SUBMIT_HINT
from pcn_clone.app.notify import TOAST_KINDS, TOASTS_ID
from pcn_clone.app.review import ids, messages

SUMMARY_SAVE_DELAY_MS: Final = 800
"""How long after the last keystroke the reviewer summary is saved."""

SUBMIT_TIMEOUT_MS: Final = 30_000
"""How long Submit waits for the intake snapshot before giving up."""

HEARTBEAT_ENV: Final = "PCN_REVIEW_HEARTBEAT_SECONDS"
DEFAULT_HEARTBEAT_SECONDS: Final = 10.0

STALE_HEARTBEATS: Final = 3
"""Heartbeats a run may miss before the browser takes it as lost."""


def heartbeat_seconds() -> float:
    """The run heartbeat interval from ``PCN_REVIEW_HEARTBEAT_SECONDS``.

    Raises ``ValueError`` naming the variable when it is not a finite number
    above 0.
    """
    raw = os.environ.get(HEARTBEAT_ENV, "").strip()
    if not raw:
        return DEFAULT_HEARTBEAT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{HEARTBEAT_ENV} must be a number, got {raw!r}.") from None
    if not (math.isfinite(value) and value > 0):
        raise ValueError(f"{HEARTBEAT_ENV} must be a finite number > 0, got {raw!r}.")
    return value


def client_config() -> dict[str, Any]:
    """The configuration ``review.js`` reads, as JSON-ready data."""
    return {
        "ids": {
            "launch": ids.LAUNCH,
            "record": ids.RECORD,
            "summary": ids.SUMMARY,
            "completion": ids.COMPLETION,
            "status": ids.STATUS,
            "listRefresh": ids.LIST_REFRESH,
            "submit": SUBMIT,
            "submitHint": SUBMIT_HINT,
            "autosave": AUTOSAVE,
            "toasts": TOASTS_ID,
        },
        "summarySaveDelayMs": SUMMARY_SAVE_DELAY_MS,
        "submitTimeoutMs": SUBMIT_TIMEOUT_MS,
        "heartbeatMs": round(heartbeat_seconds() * 1000),
        "staleHeartbeats": STALE_HEARTBEATS,
        "toastKinds": TOAST_KINDS,
        "messages": {
            "drafting": messages.DRAFTING,
            "ready": messages.READY,
            "reasons": {
                "dimensionsPending": messages.DIMENSIONS_PENDING,
                "criteriaPending": messages.CRITERIA_PENDING,
                "dimensionsRetryable": messages.DIMENSIONS_RETRYABLE,
                "criteriaRetryable": messages.CRITERIA_RETRYABLE,
                "dimensionsMovedOn": messages.DIMENSIONS_MOVED_ON,
                "criteriaMovedOn": messages.CRITERIA_MOVED_ON,
                "dimensionsInvalid": messages.DIMENSIONS_INVALID,
                "criteriaInvalid": messages.CRITERIA_INVALID,
                "dimensionsUndecided": messages.DIMENSIONS_UNDECIDED,
                "criteriaUndecided": messages.CRITERIA_UNDECIDED,
                "summaryBlank": messages.SUMMARY_BLANK,
                "summarySaveFailed": messages.SUMMARY_SAVE_FAILED,
                "summarySaving": messages.SUMMARY_SAVING,
            },
            "transportFailure": messages.TRANSPORT_FAILURE,
            "startFailure": messages.START_FAILURE,
            "invalidResult": messages.INVALID_RESULT,
            "resultNotSaved": messages.RESULT_NOT_SAVED,
            "superseded": messages.SUPERSEDED,
            "arrivedLate": messages.ARRIVED_LATE,
            "saveResultFailed": messages.SAVE_RESULT_FAILED,
            "inReview": messages.IN_REVIEW,
            "decisionMovedOn": messages.DECISION_MOVED_ON,
            "decisionNotSaved": messages.DECISION_NOT_SAVED,
            "decisionSaveFailed": messages.DECISION_SAVE_FAILED,
            "decisionInvalid": messages.DECISION_INVALID,
            "decisionStorage": messages.DECISION_STORAGE,
            "sessionState": messages.SESSION_STATE,
            "submitFailed": messages.SUBMIT_FAILED,
            "submitNoAnswer": messages.SUBMIT_NO_ANSWER,
            "draftNotRestored": messages.DRAFT_NOT_RESTORED,
            "projectGone": messages.PROJECT_GONE,
            "deleted": messages.DELETED,
            "deleteFailed": messages.DELETE_FAILED,
        },
    }
