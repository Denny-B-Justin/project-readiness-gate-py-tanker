"""Text the workspace shows from both sides: rendered here and shipped to
``assets/review-ui.js`` in the client configuration, so each string is
defined once. ``{name}`` marks a value review-ui.js fills in."""

from __future__ import annotations

from typing import Final

AUTOSAVE_IDLE: Final = "Changes save automatically"
"""The summary's save line before its first save."""

AUTOSAVE_SAVED: Final = "Last saved at {time}"
"""The summary's save line after a save, with its local time (HH:MM)."""

AUTOSAVE_FAILED: Final = (
    "Your draft couldn’t be saved — check your browser’s storage settings."  # noqa: RUF001
)
"""The summary's save line when the last save failed."""

CITATIONS_ONE: Final = "{count} citation"
CITATIONS_MANY: Final = "{count} citations"

CURATED_QUOTE: Final = "“{quote}”"
"""A reviewer-curated citation's quote."""

CURATED_NOTE: Final = "Note: {note}"
"""A reviewer-curated citation's note."""

SAVING: Final = "Saving…"
"""A save button's label while its decision is being written."""

SAVE_EDIT: Final = "Save edit"
SAVE_SCORE: Final = "Save score"


def citations(count: int) -> str:
    """ "1 citation" / "3 citations"."""
    return (CITATIONS_ONE if count == 1 else CITATIONS_MANY).format(count=count)
