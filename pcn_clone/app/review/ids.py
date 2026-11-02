"""Component ids of the review session and its run.

The run's two channels live in the app shell (``pcn_clone.app.review.run.
run_stores``), so a run keeps saving results while the reviewer is on
another page; the session stores and the context bar live on the review
page. Every review id starts with ``rv-``.

Each channel is a store whose ``data`` is a list that only ever grows or is
rewritten whole by its one writer, and is read whole by its reader: Dash may
fold several writes to one store into a single callback run, and a reader
that takes the whole list loses none of them.
"""

from __future__ import annotations

from typing import Final, Literal

ItemKind = Literal["dimension", "criterion"]
"""What a review item is: an assessment dimension or an MCA criterion."""

ITEM_KINDS: Final[tuple[ItemKind, ...]] = ("dimension", "criterion")

# --- The app shell -------------------------------------------------------------

CONFIG: Final = "rv-config"
"""Store carrying the ids, messages and settings ``review.js`` reads."""

LAUNCH: Final = "rv-launch"
"""The browser's outbox: the list of run requests the server has not yet
acknowledged, each ``{reviewId, nonce, items: [{kind, id, generation}],
request}``, rewritten whole by ``review.js``."""

INBOX: Final = "rv-inbox"
"""The server's outbox: an append-only list of run messages, each with the
run's ``reviewId`` and ``nonce`` and a ``type``: ``started``; ``result``
with ``kind``, ``itemId``, ``generation`` and the engine's ``response``;
``heartbeat`` with ``at``; ``done``."""

# --- The review page -------------------------------------------------------------

SESSION: Final = "rv-session"
"""Store carrying the open review's ``{reviewId, title}``; it mounts the
session."""

RECORD: Final = "rv-record"
"""Store holding the open review's validated record, refreshed on every
change."""

SUMMARY: Final = "rv-summary"
"""Store holding the reviewer summary's save state: ``{reviewId,
persisted, saveFailed, lastSavedISO}``."""

COMPLETION: Final = "rv-completion"
"""Store holding ``{ready, reasons, status, drafting}``."""

PART: Final = "rv-part"
"""Store naming the opened workspace component, ``{"key", "title"}``, or
``None`` on the hub; the breadcrumb follows it."""

CRUMB_TITLE: Final = "rv-crumb-title"
"""The project crumb on the hub."""

CRUMB_BACK: Final = "rv-crumb-back"
"""The project crumb while a component is open: back to the hub."""

CRUMB_TAIL: Final = "rv-crumb-tail"
CRUMB_PART: Final = "rv-crumb-part"
"""The open component's crumb, and its title."""

STATUS: Final = "rv-status"
DETAILS: Final = "rv-details"

# --- The list page -------------------------------------------------------------

LIST_REFRESH: Final = "assess-refresh"
"""Store whose change re-reads the Assessment list: bumped after a delete
and whenever a review changes while the list is open."""
