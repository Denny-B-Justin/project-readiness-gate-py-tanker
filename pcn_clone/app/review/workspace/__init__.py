"""The assessor workspace: the hub, the findings and scoring components,
the score summary and the reviewer summary.

The review page mounts :func:`workspace_view` once the session has found
the record. Everything shown comes from the record's own snapshots
(dimension definitions, MCA matrix, field labels and the exact text the
assessor read), never from the live content, so a historical review renders
as it was assessed.

Rendering is split so the live state lands without redrawing the page: a
server callback draws the views and card frames once per record load, from
the structure ``assets/review-ui.js`` publishes; as results land and
decisions change the script asks for exactly the stale card regions to be
redrawn (a component's cards from the first time its view opens), with the
component regions and the memo panel (:mod:`.render`). The script owns
everything the reviewer types: the summary, decision notes (saved on blur)
and the in-place editors, each drawn when opened and cleared when closed,
whose drafts it writes through the session's ``pcnReview.decide`` on Save.
No callback re-renders an ancestor of a control in use.

The open view lives in the session's ``rv-part`` store (``{"key",
"title"}``, or ``None`` on the hub); opening or closing one scrolls to the
top.

Importing this package registers the workspace's callbacks.
"""

from __future__ import annotations

from pcn_clone.app.review.workspace import callbacks as callbacks
from pcn_clone.app.review.workspace.layout import workspace_view

__all__ = ["workspace_view"]
