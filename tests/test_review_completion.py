"""When a review is complete: every blocking reason, its wording and
plurals, the fixed order of the reasons, the summary's three states, and
the status line the context bar shows."""

from __future__ import annotations

from typing import Any

import pytest

from pcn_clone.app.review import messages
from pcn_clone.app.review.completion import SummaryState, completion, status_line

DIMENSIONS = ("d1", "d2", "d3")
CRITERIA = ("c1", "c2")

DECIDED: dict[str, Any] = {
    "status": "ok",
    "generation": 2,
    "disposition": {"kind": "accepted"},
}
UNDECIDED: dict[str, Any] = {"status": "ok", "generation": 1}
PENDING: dict[str, Any] = {"status": "pending", "generation": 1}


def failed(kind: str, code: str) -> dict[str, Any]:
    return {
        "status": "error",
        "generation": 1,
        "errorMessage": "Failed.",
        "error": {"kind": kind, "code": code},
    }


RETRYABLE = failed("retryable", "provider_error")
MOVED_ON = failed("terminal", "model_mismatch")
INVALID = failed("terminal", "invalid_result")

SAVED: SummaryState = {"text": "Fundable.", "persisted": True, "saveFailed": False}


def record(
    dimensions: dict[str, dict[str, Any]] | None = None,
    criteria: dict[str, dict[str, Any]] | None = None,
    *,
    with_mca: bool = True,
) -> dict[str, Any]:
    """A record whose items are all decided except those given."""
    states = {item: DECIDED for item in DIMENSIONS} | (dimensions or {})
    built: dict[str, Any] = {
        "dimensionDefs": [{"id": item} for item in DIMENSIONS],
        "dimensions": states,
    }
    if with_mca:
        built["mca"] = {
            "matrix": {"criteria": [{"id": item} for item in CRITERIA]},
            "criteria": {item: DECIDED for item in CRITERIA} | (criteria or {}),
        }
    return built


def test_a_decided_review_with_a_saved_summary_is_complete() -> None:
    result = completion(record(), SAVED)

    assert result.ready is True
    assert result.reasons == ()
    assert status_line(record(), SAVED) == messages.READY


@pytest.mark.parametrize(
    ("dimensions", "criteria", "reason"),
    [
        ({"d1": PENDING}, {}, "1 dimension is still being assessed."),
        ({"d1": PENDING, "d2": PENDING}, {}, "2 dimensions are still being assessed."),
        ({}, {"c1": PENDING}, "1 criterion is still being scored."),
        ({}, {"c1": PENDING, "c2": PENDING}, "2 criteria are still being scored."),
        ({"d1": RETRYABLE}, {}, "1 dimension failed — retry it above."),
        (
            {"d1": RETRYABLE, "d3": RETRYABLE},
            {},
            "2 dimensions failed — retry them above.",
        ),
        ({}, {"c2": RETRYABLE}, "1 criterion failed to score — retry it above."),
        (
            {},
            {"c1": RETRYABLE, "c2": RETRYABLE},
            "2 criteria failed to score — retry them above.",
        ),
        (
            {"d2": MOVED_ON},
            {},
            "1 dimension can no longer be assessed — submit the project again "
            "from its editor.",
        ),
        (
            {},
            {"c1": MOVED_ON, "c2": MOVED_ON},
            "2 criteria can no longer be scored — submit the project again from "
            "its editor.",
        ),
        (
            {"d1": INVALID},
            {},
            "1 dimension returned an internally inconsistent result — an "
            "application defect; please report it.",
        ),
        (
            {},
            {"c1": INVALID},
            "1 criterion returned an internally inconsistent score — an "
            "application defect; please report it.",
        ),
        ({"d1": UNDECIDED}, {}, "1 finding awaits your decision."),
        (
            {"d1": UNDECIDED, "d2": UNDECIDED, "d3": UNDECIDED},
            {},
            "3 findings await your decision.",
        ),
        ({}, {"c1": UNDECIDED}, "1 score awaits your decision."),
        ({}, {"c1": UNDECIDED, "c2": UNDECIDED}, "2 scores await your decision."),
    ],
)
def test_each_item_state_blocks_with_its_own_sentence(
    dimensions: dict[str, dict[str, Any]],
    criteria: dict[str, dict[str, Any]],
    reason: str,
) -> None:
    result = completion(record(dimensions, criteria), SAVED)

    assert result.ready is False
    assert result.reasons == (reason,)


@pytest.mark.parametrize(
    ("summary", "reason"),
    [
        (
            {"text": "", "persisted": True, "saveFailed": False},
            "The reviewer summary has not been written yet.",
        ),
        (
            {"text": " \n\t", "persisted": False, "saveFailed": True},
            "The reviewer summary has not been written yet.",
        ),
        (
            {"text": "Fundable.", "persisted": False, "saveFailed": False},
            "The reviewer summary is still saving.",
        ),
        (
            {"text": "Fundable.", "persisted": False, "saveFailed": True},
            "The reviewer summary could not be saved on this device — check your "
            "browser's storage settings.",
        ),
    ],
)
def test_the_summary_blocks_until_written_and_saved(
    summary: SummaryState, reason: str
) -> None:
    assert completion(record(), summary).reasons == (reason,)


def test_reasons_come_in_fixed_order() -> None:
    every = record(
        {"d1": PENDING, "d2": RETRYABLE, "d3": UNDECIDED},
        {"c1": MOVED_ON, "c2": INVALID},
    )
    every["dimensionDefs"] += [{"id": "d4"}, {"id": "d5"}]
    every["dimensions"] |= {"d4": MOVED_ON, "d5": INVALID}
    every["mca"]["matrix"]["criteria"] += [
        {"id": "c3"},
        {"id": "c4"},
        {"id": "c5"},
    ]
    every["mca"]["criteria"] |= {"c3": PENDING, "c4": RETRYABLE, "c5": UNDECIDED}
    blank: SummaryState = {"text": "", "persisted": True, "saveFailed": False}

    assert completion(every, blank).reasons == (
        "1 dimension is still being assessed.",
        "1 criterion is still being scored.",
        "1 dimension failed — retry it above.",
        "1 criterion failed to score — retry it above.",
        "1 dimension can no longer be assessed — submit the project again from "
        "its editor.",
        "1 criterion can no longer be scored — submit the project again from its "
        "editor.",
        "1 dimension returned an internally inconsistent result — an application "
        "defect; please report it.",
        "1 criterion returned an internally inconsistent score — an application "
        "defect; please report it.",
        "1 finding awaits your decision.",
        "1 score awaits your decision.",
        "The reviewer summary has not been written yet.",
    )


def test_a_review_without_mca_gates_on_its_dimensions_alone() -> None:
    plain = record({"d2": UNDECIDED}, with_mca=False)

    assert completion(plain, SAVED).reasons == ("1 finding awaits your decision.",)


def test_a_decision_on_a_terminal_failure_is_not_needed() -> None:
    assert completion(record({"d1": MOVED_ON}), SAVED).reasons == (
        "1 dimension can no longer be assessed — submit the project again from "
        "its editor.",
    )


def test_the_status_line_narrates_the_run_while_anything_is_pending() -> None:
    drafting = record({"d1": PENDING, "d2": UNDECIDED}, {"c2": PENDING})

    assert status_line(drafting, SAVED) == (
        "Drafting all 5 sections in parallel — 3 returned"
    )


def test_after_the_run_the_status_line_is_the_first_reason() -> None:
    blocked = record({"d2": UNDECIDED}, {"c1": RETRYABLE})

    assert status_line(blocked, SAVED) == (
        "1 criterion failed to score — retry it above."
    )
