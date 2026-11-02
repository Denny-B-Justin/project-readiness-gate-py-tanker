"""Component ids of the proposer workspace.

Single components have fixed ids; per-field and per-section components use
pattern-matching ids ``{"type": <kind>, "field": <field id>}`` (or
``"section"``) so one callback serves every field. Component ids start with
``pf-``, except ``form-values`` (the store the rest of the app reads answers
from); element ids that are not Dash components (section anchors, field
headings) follow their own patterns below.
"""

from __future__ import annotations

from typing import Final

FORM_VALUES: Final = "form-values"
"""Memory store mirroring every answer, kept current by ``assets/form.js``."""

PROJECT: Final = "pf-project"
"""Store carrying the open project's ``id`` and ``title``."""

CONFIG: Final = "pf-config"
"""Store carrying the per-field configuration form.js reads."""

ROOT: Final = "pf-root"
"""The element around the whole workspace; form.js binds to it."""

AUTOSAVE: Final = "pf-autosave"
NOTES_DIALOG: Final = "pf-notes-dialog"
BACK_TO_TOP: Final = "pf-back-to-top"
JUMP_TRIGGER: Final = "pf-jump-trigger"
JUMP_NUMBER: Final = "pf-jump-number"
JUMP_TITLE: Final = "pf-jump-title"
SUBMIT: Final = "pf-submit"
"""The Submit button: ``aria-disabled`` until the workspace is hydrated,
``aria-busy`` while the review is being created."""

SUBMIT_HINT: Final = "pf-submit-hint"
"""The Submit button's description: empty, or why it cannot be used."""

SUBMIT_REQUEST: Final = "pf-submit-request"
"""Store the browser writes at a Submit click: ``{nonce, projectId,
projectTitle, sourceProjectTemplateVersion, values}``."""

SUBMIT_SNAPSHOT: Final = "pf-submit-snapshot"
"""Store holding the intake snapshot for the latest request: ``{nonce, ok,
intake}`` or ``{nonce, ok: false, errorMessage}``."""

NAV: Final = "pf-nav"
"""Location that opens the review once it is created."""

EVALUATE: Final = "pf-evaluate"
"""The field's Evaluate button."""

EVALUATE_REQUEST: Final = "pf-evaluate-request"
"""Store form.js writes to start an evaluation: ``{"answer", "context",
"n"}``, the snapshot the verdict is graded on."""

EVALUATING: Final = "pf-evaluating"
"""Store that is ``True`` while the field's evaluation runs."""

EVALUATION: Final = "pf-evaluation"
"""Store holding the field's latest evaluation response."""

READINESS_REQUEST: Final = "pf-readiness-request"
"""Store form.js writes with every answer whose readiness the server still
owes: ``{field id: {"answer", "context", "n"}}``."""

READINESS: Final = "pf-readiness"
"""Store holding the latest readiness answer: ``{field id: {"ready",
"issues", "n"}}``."""

ISSUES: Final = "pf-issues"
"""The "Complete the following before evaluating" panel."""

STATUS: Final = "pf-status"
"""The footer's state region (spinner, verdict, stale badge, failure)."""

GUIDANCE_OPEN: Final = "pf-guidance-open"
GUIDANCE_DIALOG: Final = "pf-guidance-dialog"
CRITERIA_OPEN: Final = "pf-criteria-open"
CRITERIA_DIALOG: Final = "pf-criteria-dialog"

TALLY: Final = "pf-tally"
JUMP_ITEM: Final = "pf-jump-item"


def field_id(kind: str, field: str) -> dict[str, str]:
    """The pattern-matching id of one field's ``kind`` component."""
    return {"type": kind, "field": field}


def section_id(kind: str, section: str) -> dict[str, str]:
    """The pattern-matching id of one section's ``kind`` component."""
    return {"type": kind, "section": section}


def title_id(field: str) -> str:
    """The id of a field card's heading, which names the field's input."""
    return f"pf-title-{field}"


def anchor_id(section: str) -> str:
    """The id of a section's anchor, the target of the jump menu."""
    return f"section-{section}"
