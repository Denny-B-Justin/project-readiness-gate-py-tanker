"""User-facing text the workspace shows from both sides: rendered here and
shipped to ``assets/form.js`` in the client configuration, so each string
is defined once."""

from __future__ import annotations

from typing import Final

TRANSPORT_FAILURE: Final = (
    "The evaluation request could not be completed. Please try again."
)
"""Why an evaluation failed when its request itself failed."""

NOT_READY: Final = "This field is not ready to evaluate."
"""Why an evaluation was refused before any model call."""

EVALUATE_LABEL: Final = "Evaluate field"
"""The Evaluate button's label before the field's first verdict."""

AUTOSAVE_IDLE: Final = "Changes save automatically"
"""The autosave line before the first save."""

JUMP_LABEL: Final = "Jump to section"

JUMP_CURRENT: Final = "Jump to section. Current: {number} {title}"
"""The jump trigger's accessible name for the section in view."""

FIELD_ACTION: Final = "{action}: {number} {title}"
"""The accessible name of a field's button, naming the field it acts on."""


def field_action(action: str, number: str, title: str) -> str:
    """``FIELD_ACTION`` for one field's ``action`` button."""
    return FIELD_ACTION.format(action=action, number=number, title=title)
