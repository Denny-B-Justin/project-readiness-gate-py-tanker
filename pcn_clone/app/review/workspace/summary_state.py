"""Which MCA computation may be shown, and over which scores.

``pcn_clone.core.mca.compute_mca_summary`` is the only producer of weighted
points, percent of maximum and band, and is blind to endorsement; this
module decides which score counts for each criterion and what the result
may be called:

- **unavailable**: some criterion is pending or failed. No total, percent
  or band: a partial sum is a wrong number, not a preview.
- **provisional**: every draft exists but not every one is decided. Each
  criterion counts the reviewer's adjusted score where adjusted, the AI
  draft otherwise.
- **final**: every criterion is decided; the same scores, now endorsed.
  This is the only computation the memo carries.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pcn_clone.app.review.workspace.records import (
    JsonObject,
    as_object,
    disposition_of,
    state_of,
    status_of,
)
from pcn_clone.content.models import McaMatrix
from pcn_clone.core.mca import McaSummary, compute_mca_summary
from pcn_clone.core.numbers import to_fixed

SummaryStateName = Literal["unavailable", "provisional", "final"]


@dataclass(frozen=True, slots=True)
class McaSummaryState:
    """The selected summary: absent while unavailable."""

    state: SummaryStateName
    summary: McaSummary | None = None


def effective_score(state: JsonObject) -> Any:
    """The score a completed criterion counts: the reviewer's where
    adjusted, the AI draft otherwise (an acceptance endorses the draft)."""
    disposition = disposition_of(state)
    if disposition is not None and disposition.get("kind") == "adjusted":
        return disposition.get("finalScore")
    return as_object(state.get("scoreFinding")).get("score")


def select_mca_summary_state(
    matrix: McaMatrix, criterion_states: Mapping[str, JsonObject]
) -> McaSummaryState:
    """The summary state for one record's criterion states, keyed by
    criterion id. The states must be the matrix's own (one per criterion);
    ``compute_mca_summary`` raises on any drift."""
    if any(status_of(state) != "ok" for state in criterion_states.values()):
        return McaSummaryState("unavailable")
    summary = compute_mca_summary(
        matrix,
        {
            criterion: effective_score(state)
            for criterion, state in criterion_states.items()
        },
    )
    final = all(
        disposition_of(state) is not None for state in criterion_states.values()
    )
    return McaSummaryState("final" if final else "provisional", summary)


def matrix_states(
    matrix: McaMatrix, criteria: Mapping[str, Any]
) -> dict[str, JsonObject]:
    """The criterion states in matrix order, one per criterion, pending
    where the record holds none."""
    return {
        criterion.id: state_of(criteria, criterion.id) for criterion in matrix.criteria
    }


def percent_text(value: float) -> str:
    """A percent of maximum for display, to one decimal: ``"53.3%"``."""
    return f"{to_fixed(value, 1)}%"
