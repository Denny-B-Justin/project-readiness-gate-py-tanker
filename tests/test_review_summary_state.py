"""Which MCA computation the workspace may show: unavailable while any
criterion is pending or failed, provisional over the drafts (adjusted
scores counting), final once every score is decided; the numbers always
come from ``compute_mca_summary``.

The matrix: urgency ×60 and fiscal ×40 on a 1–3 scale, bands 80/60/0.
Scores 2 and 2 give 200 of 300, 66.67%, Medium; urgency adjusted to 3 gives
260, 86.67%, High."""

from __future__ import annotations

from typing import Any

import pytest

from pcn_clone.app.review.workspace.summary_state import (
    effective_score,
    matrix_states,
    percent_text,
    select_mca_summary_state,
)
from pcn_clone.content.models import McaMatrix
from pcn_clone.core.mca import McaScoreError

DESCRIPTORS = {"1": "None.", "2": "Some.", "3": "Strong."}

MATRIX = McaMatrix.model_validate(
    {
        "scale": [
            {"value": 1, "label": "Low", "meaning": "Poor."},
            {"value": 2, "label": "Medium", "meaning": "Adequate."},
            {"value": 3, "label": "High", "meaning": "Strong."},
        ],
        "bands": [
            {"id": "high", "label": "High", "minPercentOfMaximum": 80},
            {"id": "medium", "label": "Medium", "minPercentOfMaximum": 60},
            {"id": "low", "label": "Low", "minPercentOfMaximum": 0},
        ],
        "criteria": [
            {
                "id": "urgency",
                "label": "Urgency",
                "weight": 60,
                "description": "How soon.",
                "descriptors": DESCRIPTORS,
            },
            {
                "id": "fiscal",
                "label": "Fiscal affordability",
                "weight": 40,
                "description": "Running costs.",
                "descriptors": DESCRIPTORS,
            },
        ],
    }
)

ADJUSTED_UP = {
    "kind": "adjusted",
    "finalScore": 3,
    "rationale": "Stronger than drafted.",
    "basis": {"kind": "documented", "evidence": [{"sectionId": "s1", "fieldId": "f1"}]},
}


def ok(score: int, disposition: dict[str, Any] | None = None) -> dict[str, Any]:
    state: dict[str, Any] = {
        "status": "ok",
        "generation": 1,
        "scoreFinding": {"score": score, "basis": {"kind": "not_evidenced"}},
    }
    if disposition is not None:
        state["disposition"] = disposition
    return state


@pytest.mark.parametrize(
    "other",
    [
        {"status": "pending", "generation": 1},
        {
            "status": "error",
            "generation": 1,
            "errorMessage": "The scoring could not be completed.",
            "error": {"kind": "retryable", "code": "provider_error"},
        },
    ],
)
def test_a_pending_or_failed_criterion_makes_the_summary_unavailable(
    other: dict[str, Any],
) -> None:
    selected = select_mca_summary_state(MATRIX, {"urgency": ok(2), "fiscal": other})
    assert selected.state == "unavailable"
    assert selected.summary is None


def test_every_draft_in_but_not_decided_is_provisional() -> None:
    selected = select_mca_summary_state(MATRIX, {"urgency": ok(2), "fiscal": ok(2)})
    assert selected.state == "provisional"
    assert selected.summary is not None
    assert selected.summary.total_weighted_points == 200
    assert selected.summary.max_weighted_points == 300
    assert selected.summary.band.id == "medium"


def test_an_adjusted_score_counts_in_the_provisional_summary() -> None:
    selected = select_mca_summary_state(
        MATRIX, {"urgency": ok(2, ADJUSTED_UP), "fiscal": ok(2)}
    )
    assert selected.state == "provisional"
    assert selected.summary is not None
    assert selected.summary.total_weighted_points == 260
    assert selected.summary.band.id == "high"
    assert percent_text(selected.summary.percent_of_maximum) == "86.7%"


def test_every_score_decided_is_final() -> None:
    silent = {
        "kind": "adjusted",
        "finalScore": 1,
        "rationale": "None documented.",
        "basis": {"kind": "not_evidenced"},
    }
    selected = select_mca_summary_state(
        MATRIX, {"urgency": ok(2, {"kind": "accepted"}), "fiscal": ok(2, silent)}
    )
    assert selected.state == "final"
    assert selected.summary is not None
    assert selected.summary.total_weighted_points == 160
    assert selected.summary.band.id == "low"
    assert percent_text(selected.summary.percent_of_maximum) == "53.3%"


def test_a_state_map_that_drifts_from_the_matrix_raises() -> None:
    with pytest.raises(McaScoreError, match="missing criterion"):
        select_mca_summary_state(MATRIX, {"urgency": ok(2)})


def test_the_effective_score_is_the_adjustment_where_adjusted() -> None:
    assert effective_score(ok(2)) == 2
    assert effective_score(ok(2, {"kind": "accepted"})) == 2
    assert effective_score(ok(2, ADJUSTED_UP)) == 3


def test_matrix_states_fills_missing_criteria_as_pending_in_matrix_order() -> None:
    states = matrix_states(MATRIX, {"fiscal": ok(2), "stray": ok(1)})
    assert list(states) == ["urgency", "fiscal"]
    assert states["urgency"]["status"] == "pending"
