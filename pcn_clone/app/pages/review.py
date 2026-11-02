"""``?page=review&review_id=…``: one review session, behind the review gate.

The server cannot see the browser's review store, so the page is gated (see
``pcn_clone.app.gate``): it opens in a checking state and renders the
session (``pcn_clone.app.review``) only when this device holds a readable
record with that id; a missing record gets a not-found panel and a record
that fails validation an unreadable panel with the reason. The record is
self-contained, so the page renders from it alone, whatever the live
content says now.
"""

from __future__ import annotations

from dash.development.base_component import Component

from pcn_clone.app.gate import gate_container, register_gate
from pcn_clone.app.review import review_view
from pcn_clone.app.review.context_bar import PROVENANCE_FIELDS
from pcn_clone.app.review.view import checking_panel, missing_panel, unreadable_panel


def layout(review_id: str | None = None) -> Component:
    """The gated review page; it opens in the checking state."""
    return gate_container(
        "review",
        record_type="review",
        record_id=review_id,
        expect={},
        fields=list(PROVENANCE_FIELDS),
        checking=checking_panel(),
    )


render_gate = register_gate(
    "review",
    found=review_view,
    missing=missing_panel,
    checking=checking_panel,
    unreadable=unreadable_panel,
)
