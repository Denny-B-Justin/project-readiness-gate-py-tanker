"""What a decided review settles: how many findings stand, and the final
prioritisation score.

A finding stands when the reviewer accepted or edited it; a dismissed one
is left out. The final score is the MCA computation once every criterion
is decided (:func:`.summary_state.select_mca_summary_state`), an adjusted
criterion counting the reviewer's score. Asking before every item is
decided raises ``EndorsementError``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pcn_clone.app.review.workspace.records import (
    JsonObject,
    disposition_of,
    state_of,
)
from pcn_clone.app.review.workspace.summary_state import (
    matrix_states,
    select_mca_summary_state,
)
from pcn_clone.content.models import McaMatrix
from pcn_clone.core.mca import McaSummary


class EndorsementError(ValueError):
    """Some item of the review is not decided yet."""


@dataclass(frozen=True, slots=True)
class Endorsement:
    """The findings that stand, those dismissed, and the final MCA
    computation (None for a record without an MCA block)."""

    standing: int
    dismissed: int
    summary: McaSummary | None


def endorsement(
    definitions: Sequence[JsonObject],
    dimensions: Mapping[str, Any],
    matrix: McaMatrix | None,
    criteria: Mapping[str, Any],
) -> Endorsement:
    """What the decided review settles."""
    kinds = []
    for definition in definitions:
        disposition = disposition_of(state_of(dimensions, str(definition.get("id"))))
        if disposition is None:
            raise EndorsementError(
                f'Dimension "{definition.get("id")}" is not decided.'
            )
        kinds.append(disposition.get("kind"))
    dismissed = kinds.count("dismissed")
    summary = None
    if matrix is not None:
        selected = select_mca_summary_state(matrix, matrix_states(matrix, criteria))
        if selected.state != "final":
            raise EndorsementError("The MCA summary is not final.")
        summary = selected.summary
    return Endorsement(len(kinds) - dismissed, dismissed, summary)
