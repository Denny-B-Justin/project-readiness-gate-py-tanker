"""The score adjustment editor's state as pure transitions: the score and
basis invariant (not evidenced pairs only with the scale floor, both ways),
the required rationale and evidence, and the disposition a valid draft
saves as. The browser suite checks review-ui.js makes the same moves."""

from __future__ import annotations

from typing import Any

import pytest

from tests.oracles.adjust_draft import (
    AdjustDraft,
    IncompleteAdjustmentError,
    adjust_draft_issues,
    can_save_adjust_draft,
    initial_adjust_draft,
    to_adjusted_disposition,
    with_basis_kind,
    with_score,
)

SCALE_MINIMUM = 1


def score_finding(**overrides: Any) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "criterionId": "urgency",
        "model": "fixture-model",
        "score": 2,
        "justification": "The submission documents some merit.",
        "basis": {
            "kind": "documented",
            "evidence": [
                {
                    "sectionId": "s1",
                    "fieldId": "f1",
                    "quote": "halves travel time",
                    "verified": True,
                }
            ],
        },
    }
    finding.update(overrides)
    return finding


def valid_draft(**overrides: Any) -> AdjustDraft:
    draft: AdjustDraft = {
        "score": 3,
        "rationale": "The outage evidence is stronger than the draft credits.",
        "basisKind": "documented",
        "evidence": [
            {"sectionId": "s1", "fieldId": "f1", "quote": "halves travel time"}
        ],
    }
    draft.update(overrides)  # type: ignore[typeddict-item]
    return draft


def test_the_opening_draft_takes_the_ai_score_and_citations_not_its_words() -> None:
    draft = initial_adjust_draft(score_finding())
    assert draft == {
        "score": 2,
        "rationale": "",
        "basisKind": "documented",
        "evidence": [
            {"sectionId": "s1", "fieldId": "f1", "quote": "halves travel time"}
        ],
    }


def test_a_not_evidenced_draft_opens_at_the_floor_with_nothing_to_curate() -> None:
    draft = initial_adjust_draft(
        score_finding(score=1, basis={"kind": "not_evidenced"})
    )
    assert (draft["score"], draft["basisKind"], draft["evidence"]) == (
        1,
        "not_evidenced",
        [],
    )


def test_readjusting_continues_from_the_prior_adjustment() -> None:
    draft = initial_adjust_draft(
        score_finding(),
        {
            "kind": "adjusted",
            "finalScore": 3,
            "rationale": "Documented outages.",
            "basis": {
                "kind": "documented",
                "evidence": [
                    {"sectionId": "s1", "fieldId": "f1", "note": "the whole answer"}
                ],
            },
        },
    )
    assert draft == {
        "score": 3,
        "rationale": "Documented outages.",
        "basisKind": "documented",
        "evidence": [{"sectionId": "s1", "fieldId": "f1", "note": "the whole answer"}],
    }


def test_raising_the_score_off_the_floor_falls_back_to_documented() -> None:
    floor = valid_draft(score=SCALE_MINIMUM, basisKind="not_evidenced", evidence=[])
    raised = with_score(floor, 2, SCALE_MINIMUM)
    assert (raised["score"], raised["basisKind"]) == (2, "documented")
    lowered = with_score(valid_draft(), SCALE_MINIMUM, SCALE_MINIMUM)
    assert lowered["basisKind"] == "documented"


def test_not_evidenced_is_refused_off_the_floor_and_accepted_on_it() -> None:
    off_floor = with_basis_kind(valid_draft(score=2), "not_evidenced", SCALE_MINIMUM)
    assert off_floor["basisKind"] == "documented"
    on_floor = with_basis_kind(
        valid_draft(score=SCALE_MINIMUM), "not_evidenced", SCALE_MINIMUM
    )
    assert on_floor["basisKind"] == "not_evidenced"


@pytest.mark.parametrize("rationale", ["", "   ", "\n\t ", "﻿"])
def test_a_blank_rationale_blocks_the_save(rationale: str) -> None:
    draft = valid_draft(rationale=rationale)
    assert adjust_draft_issues(draft)["rationaleMissing"] is True
    assert can_save_adjust_draft(draft) is False


def test_documented_needs_a_citation_and_not_evidenced_none() -> None:
    documented = valid_draft(evidence=[])
    assert adjust_draft_issues(documented) == {
        "rationaleMissing": False,
        "evidenceMissing": True,
    }
    assert can_save_adjust_draft(documented) is False
    silent = valid_draft(score=SCALE_MINIMUM, basisKind="not_evidenced", evidence=[])
    assert can_save_adjust_draft(silent) is True


def test_a_valid_draft_saves_as_adjusted_with_blanks_left_out() -> None:
    disposition = to_adjusted_disposition(
        valid_draft(
            evidence=[{"sectionId": "s1", "fieldId": "f1", "quote": "", "note": ""}]
        )
    )
    assert disposition == {
        "kind": "adjusted",
        "finalScore": 3,
        "rationale": "The outage evidence is stronger than the draft credits.",
        "basis": {
            "kind": "documented",
            "evidence": [{"sectionId": "s1", "fieldId": "f1"}],
        },
    }


def test_a_not_evidenced_draft_saves_without_its_earlier_citations() -> None:
    disposition = to_adjusted_disposition(
        valid_draft(
            score=SCALE_MINIMUM,
            basisKind="not_evidenced",
            evidence=[{"sectionId": "s1", "fieldId": "f1", "quote": "stale"}],
        )
    )
    assert disposition["basis"] == {"kind": "not_evidenced"}


def test_an_incomplete_draft_cannot_become_a_disposition() -> None:
    with pytest.raises(IncompleteAdjustmentError, match="incomplete adjustment"):
        to_adjusted_disposition(valid_draft(rationale=" "))
