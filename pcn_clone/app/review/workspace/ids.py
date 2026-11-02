"""Every name the assessor workspace shares with the review session and
with ``assets/review-ui.js``: the session's stores and browser API it reads
(defined in :mod:`pcn_clone.app.review.ids`), and its own component ids.

The workspace's own ids start with ``rv-ws-``. Per-item and per-view
regions use pattern-matching ids so one callback serves every card whatever
the record holds.
"""

from __future__ import annotations

from typing import Final, Literal

from pcn_clone.app.review import ids as session

# --- The session's names (read, never defined, here) -------------------------

RECORD: Final = session.RECORD
"""The open review's record (schema version 2)."""

SUMMARY_STATE: Final = session.SUMMARY
"""The reviewer summary's save state: ``{reviewId, persisted, saveFailed,
lastSavedISO}``."""

COMPLETION: Final = session.COMPLETION
"""``{ready, reasons, status, drafting}``: what still blocks completion."""

VIEW: Final = session.PART
"""The open view, ``{"key": "findings" | "scores", "title"}``, or ``None``
on the hub (the session's ``rv-part`` store). The workspace writes it; the
session's breadcrumb follows it and its project crumb sets it back to
``None``."""

SESSION_API: Final = "pcnReview"
"""The ``window`` global through which the browser records decisions,
retries items and saves the summary."""

CONFIG: Final = "rv-ws-config"
"""Store carrying the ids, kinds and text review-ui.js reads."""

SHAPE: Final = "rv-ws-shape"
"""Store review-ui.js writes once per record load with the record's frozen
structure; its change renders the workspace's cards."""

PROGRESS: Final = "rv-ws-progress"
"""Store review-ui.js writes as item states, decisions and the summary's
completion change; its change redraws the regions that show them."""

# --- Elements ----------------------------------------------------------------

ROOT: Final = "rv-ws-root"
"""The element the cards render into; review-ui.js binds to it."""

SUMMARY: Final = "rv-ws-summary"
"""The reviewer summary's textarea."""

AUTOSAVE: Final = "rv-ws-autosave"
"""The reviewer summary's save-status line."""

MEMO: Final = "rv-ws-memo"
"""The memo panel's live regions: the locked panel's "sections in" line
(slot ``count``) and the blocking reasons or completion status (slot
``readiness``)."""

ITEM_TOP: Final = "rv-ws-item-top"
"""A card's header and body for the item's current state."""

ITEM_FOOT: Final = "rv-ws-item-foot"
"""A card's decision footer for the item's current state."""

EDITOR: Final = "rv-ws-editor"
"""A card's editor slot, drawn when the reviewer opens the editor and
cleared when it closes."""

EDITING: Final = "rv-ws-editing"
"""Store review-ui.js writes to have editors drawn or cleared: ``{draw,
clear, fields}`` (see :mod:`.render`)."""

REGION: Final = "rv-ws-region"
"""A view's live regions, ``{"type": REGION, "view", "slot"}``: the view's
hub card (slot ``hub``), its progress trail and header aside, and the score
summary."""

ItemKind = session.ItemKind
"""``"dimension"`` or ``"criterion"``, as the session names items."""

ViewKey = Literal["findings", "scores"]
"""An openable view: the assessment findings or the prioritisation scoring."""

VIEW_OF_KIND: Final[dict[ItemKind, ViewKey]] = {
    "dimension": "findings",
    "criterion": "scores",
}


def anchor_id(kind: ItemKind, item: str) -> str:
    """The element id of an item's card: ``finding-<id>`` for a dimension,
    ``score-<id>`` for a criterion, namespaced because a criterion may share
    an id with a dimension."""
    return f"{'finding' if kind == 'dimension' else 'score'}-{item}"


def control_id(kind: ItemKind, item: str, control: str) -> str:
    """The element id of one control inside an item's card or editor."""
    return f"rv-{kind}-{item}-{control}"
