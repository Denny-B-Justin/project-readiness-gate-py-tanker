"""When a review is complete, and what still blocks it.

A review is complete when every dimension and every MCA criterion has
returned, every finding and score carries the reviewer's decision, and the
reviewer summary is written and saved: text still waiting to be saved, or
lost to a failed save, blocks completion rather than standing as written.

The blocking reasons are reviewer-facing sentences in a fixed order: the run
first, then failures, then decisions, then the summary, with the dimension
sentence before the criterion sentence in each slot. A failure points at
what can help: Retry for a retryable error, a fresh submission when the
platform has moved on, a report for an internally inconsistent result. The
context bar shows the first reason (or the drafting line while the run
streams); the same function runs in the browser (``pcnReview.completion``
in ``assets/review.js``) from the same sentences.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypedDict

from pcn_clone.app.review import messages
from pcn_clone.app.review.messages import Plural
from pcn_clone.core.jsstr import js_trim


class SummaryState(TypedDict):
    """The summary editor's state: the live ``text``, whether the stored
    record holds exactly that text, and whether the last save failed."""

    text: str
    persisted: bool
    saveFailed: bool


@dataclass(frozen=True, slots=True)
class Completion:
    """Whether the review is complete, and the blocking reasons in order
    (empty exactly when complete)."""

    ready: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Tally:
    pending: int
    retryable: int
    moved_on: int
    invalid_result: int
    undecided: int


def _tally(states: Iterable[Mapping[str, Any]]) -> _Tally:
    pending = retryable = moved_on = invalid_result = undecided = 0
    for state in states:
        status = state.get("status")
        if status == "pending":
            pending += 1
        elif status == "ok":
            undecided += "disposition" not in state
        elif status == "error":
            error = state.get("error") or {}
            if error.get("kind") == "retryable":
                retryable += 1
            elif error.get("code") == "invalid_result":
                invalid_result += 1
            else:
                moved_on += 1
    return _Tally(pending, retryable, moved_on, invalid_result, undecided)


def _count(n: int, sentence: Plural) -> str:
    return sentence[0 if n == 1 else 1].format(n=n)


def item_states(
    record: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """The record's dimension and criterion states, in their frozen order."""
    dimensions = record["dimensions"]
    dimension_states = [dimensions[d["id"]] for d in record["dimensionDefs"]]
    mca = record.get("mca")
    criterion_states = (
        [mca["criteria"][c["id"]] for c in mca["matrix"]["criteria"]] if mca else []
    )
    return dimension_states, criterion_states


def completion(record: Mapping[str, Any], summary: SummaryState) -> Completion:
    """What still blocks ``record`` from being complete, given the summary
    editor's state."""
    dimension_states, criterion_states = item_states(record)
    dims = _tally(dimension_states)
    crits = _tally(criterion_states)
    slots = (
        (dims.pending, messages.DIMENSIONS_PENDING),
        (crits.pending, messages.CRITERIA_PENDING),
        (dims.retryable, messages.DIMENSIONS_RETRYABLE),
        (crits.retryable, messages.CRITERIA_RETRYABLE),
        (dims.moved_on, messages.DIMENSIONS_MOVED_ON),
        (crits.moved_on, messages.CRITERIA_MOVED_ON),
        (dims.invalid_result, messages.DIMENSIONS_INVALID),
        (crits.invalid_result, messages.CRITERIA_INVALID),
        (dims.undecided, messages.DIMENSIONS_UNDECIDED),
        (crits.undecided, messages.CRITERIA_UNDECIDED),
    )
    reasons = [_count(n, sentence) for n, sentence in slots if n > 0]
    if js_trim(summary["text"]) == "":
        reasons.append(messages.SUMMARY_BLANK)
    elif not summary["persisted"]:
        reasons.append(
            messages.SUMMARY_SAVE_FAILED
            if summary["saveFailed"]
            else messages.SUMMARY_SAVING
        )
    return Completion(ready=not reasons, reasons=tuple(reasons))


def status_line(record: Mapping[str, Any], summary: SummaryState) -> str:
    """The context bar's sentence: the drafting progress while any item is
    pending, otherwise the first blocking reason, or the ready line."""
    dimension_states, criterion_states = item_states(record)
    states = [*dimension_states, *criterion_states]
    pending = sum(state.get("status") == "pending" for state in states)
    if pending:
        return messages.DRAFTING.format(
            total=len(states), returned=len(states) - pending
        )
    reasons = completion(record, summary).reasons
    return reasons[0] if reasons else messages.READY
