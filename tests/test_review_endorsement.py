"""What a decided review settles: accepted and edited findings stand,
dismissed ones are counted apart, and the final MCA computation counts an
adjusted criterion's own score; asking before every item is decided
raises."""

from __future__ import annotations

from typing import Any

import pytest

from pcn_clone.app.review.workspace.endorsement import (
    EndorsementError,
    endorsement,
)
from pcn_clone.app.review.workspace.summary_state import percent_text
from pcn_clone.content.models import McaMatrix
from tests.review_records import criterion_ids, dimension_ids, drafted_record


@pytest.fixture
def record() -> dict[str, Any]:
    return drafted_record()


def decide_all(record: dict[str, Any]) -> None:
    kinds = ["accepted", "dismissed", "accepted", "dismissed", "accepted"]
    for item, kind in zip(dimension_ids(record), kinds, strict=True):
        record["dimensions"][item]["disposition"] = {"kind": kind}
    record["dimensions"][dimension_ids(record)[2]]["disposition"] = {
        "kind": "edited",
        "finalVerdict": "fail",
        "finalText": "My own finding.",
        "evidence": [],
    }
    for item in criterion_ids(record):
        record["mca"]["criteria"][item]["disposition"] = {"kind": "accepted"}


def settle(record: dict[str, Any], *, with_mca: bool = True) -> Any:
    matrix = McaMatrix.model_validate(record["mca"]["matrix"]) if with_mca else None
    return endorsement(
        record["dimensionDefs"],
        record["dimensions"],
        matrix,
        record["mca"]["criteria"],
    )


def test_accepted_and_edited_findings_stand_and_dismissed_ones_do_not(
    record: dict[str, Any],
) -> None:
    decide_all(record)
    settled = settle(record)
    assert (settled.standing, settled.dismissed) == (3, 2)


def test_the_final_score_counts_an_adjusted_criterion(record: dict[str, Any]) -> None:
    decide_all(record)
    adjusted = criterion_ids(record)[1]
    record["mca"]["criteria"][adjusted]["disposition"] = {
        "kind": "adjusted",
        "finalScore": 1,
        "rationale": "Nothing documented.",
        "basis": {"kind": "not_evidenced"},
    }
    summary = settle(record).summary
    # Scores 4, 1, 4, 3 at weights 30, 30, 20, 20: 120 + 30 + 80 + 60 of 500.
    assert (summary.total_weighted_points, summary.max_weighted_points) == (290, 500)
    assert percent_text(summary.percent_of_maximum) == "58.0%"
    assert summary.band.label == "Low"


def test_a_record_without_an_mca_block_settles_findings_only(
    record: dict[str, Any],
) -> None:
    decide_all(record)
    assert settle(record, with_mca=False).summary is None


def test_an_undecided_finding_settles_nothing(record: dict[str, Any]) -> None:
    with pytest.raises(EndorsementError, match="not decided"):
        settle(record)


def test_an_undecided_score_settles_nothing(record: dict[str, Any]) -> None:
    decide_all(record)
    del record["mca"]["criteria"][criterion_ids(record)[0]]["disposition"]
    with pytest.raises(EndorsementError, match="not final"):
        settle(record)
