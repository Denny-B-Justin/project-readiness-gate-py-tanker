"""MCA summary arithmetic and band resolution."""

from __future__ import annotations

from typing import Any

import pytest

from pcn_clone.content import load_mca
from pcn_clone.core.mca import McaScoreError, compute_mca_summary
from tests.helpers import as_json, fixture_params

URGENCY = "urgency_and_criticality"
IMPACT = "expected_economic_and_development_impact"
ENVIRONMENT = "environmental_impact"
FISCAL = "fiscal_affordability_and_sustainability"


def _scores(urgency: Any, impact: Any, environment: Any, fiscal: Any) -> dict[str, Any]:
    return {URGENCY: urgency, IMPACT: impact, ENVIRONMENT: environment, FISCAL: fiscal}


@pytest.mark.parametrize("case", fixture_params("mca_cases.json", label="mca"))
def test_mca_case_matches_golden(case: dict[str, Any]) -> None:
    matrix = load_mca().matrix
    expected = case["result"]
    if "error" in expected:
        with pytest.raises(McaScoreError) as raised:
            compute_mca_summary(matrix, case["scores"])
        assert str(raised.value) == expected["error"]
        return
    assert as_json(compute_mca_summary(matrix, case["scores"])) == expected


def test_percent_is_full_precision_and_bands_are_inclusive() -> None:
    matrix = load_mca().matrix
    summary = compute_mca_summary(matrix, _scores(3, 3, 3, 2.0))
    assert summary.total_weighted_points == 280
    assert summary.max_weighted_points == 500
    assert summary.percent_of_maximum == 56.00000000000001
    assert summary.band.id == "low"
    assert compute_mca_summary(matrix, _scores(3, 3, 3, 3)).band.id == "medium"
    assert compute_mca_summary(matrix, _scores(4, 4, 4, 4)).band.id == "high"
    assert compute_mca_summary(matrix, _scores(1, 1, 1, 1)).percent_of_maximum == 20


def test_incomplete_or_off_scale_maps_raise() -> None:
    matrix = load_mca().matrix
    with pytest.raises(McaScoreError, match=f'missing criterion "{FISCAL}"'):
        compute_mca_summary(matrix, {URGENCY: 1, IMPACT: 1, ENVIRONMENT: 1})
    with pytest.raises(McaScoreError, match='unknown criterion "extra"'):
        compute_mca_summary(matrix, {**_scores(1, 1, 1, 1), "extra": 1})
    with pytest.raises(McaScoreError, match=r"Score 2\.5 for criterion"):
        compute_mca_summary(matrix, _scores(1, 2.5, 1, 1))
    with pytest.raises(McaScoreError, match="Score null for criterion"):
        compute_mca_summary(matrix, _scores(None, 1, 1, 1))
    with pytest.raises(McaScoreError, match="Score true for criterion"):
        compute_mca_summary(matrix, _scores(True, 1, 1, 1))
