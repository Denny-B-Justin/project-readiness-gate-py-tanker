"""Review records in the review store's version 2 shape, built from the
default project's intake snapshot, for the workspace tests.

``blank_record`` is a fresh review (every item pending); the state builders
make each item state the workspace renders, with citations quoting the
snapshot's own text so they verify.
"""

from __future__ import annotations

import copy
from functools import cache
from typing import Any

from pcn_clone.ai import build_snapshot
from pcn_clone.content import load_default_project
from pcn_clone.core.evidence import verify_quote

PROJECT_TITLE = "Upper Valley District Road Rehabilitation"


@cache
def _snapshot() -> dict[str, Any]:
    return build_snapshot(load_default_project().submission).to_json()


def snapshot() -> dict[str, Any]:
    """The default project's intake snapshot (a fresh copy)."""
    return copy.deepcopy(_snapshot())


def blank_record(review_id: str = "rv-test") -> dict[str, Any]:
    """A new review of the default project: every item pending."""
    intake = snapshot()
    pending = {"status": "pending", "generation": 0}
    return {
        "schemaVersion": 2,
        "id": review_id,
        "createdISO": "2026-10-06T09:00:00.000Z",
        "editedISO": "2026-10-06T09:00:00.000Z",
        "projectId": "p-test",
        "projectTitle": PROJECT_TITLE,
        "templateId": intake["templateId"],
        "templateLabel": intake["templateLabel"],
        "templateVersion": intake["templateVersion"],
        "sourceProjectTemplateVersion": intake["templateVersion"],
        "assessmentSetId": intake["assessmentSetId"],
        "assessmentSetVersion": intake["assessmentSetVersion"],
        "model": intake["model"],
        "assessmentInputDigest": intake["assessmentInputDigest"],
        "dimensionDefs": intake["dimensionDefs"],
        "fields": intake["fields"],
        "submission": intake["submission"],
        "dimensions": {d["id"]: dict(pending) for d in intake["dimensionDefs"]},
        "mca": {
            "setId": intake["mcaSetId"],
            "setVersion": intake["mcaSetVersion"],
            "matrix": intake["matrix"],
            "criteria": {c["id"]: dict(pending) for c in intake["matrix"]["criteria"]},
        },
        "reviewerSummary": "",
    }


def dimension_ids(record: dict[str, Any]) -> list[str]:
    return [d["id"] for d in record["dimensionDefs"]]


def criterion_ids(record: dict[str, Any]) -> list[str]:
    return [c["id"] for c in record["mca"]["matrix"]["criteria"]]


def citation(record: dict[str, Any], index: int) -> dict[str, Any]:
    """A verified citation of the ``index``-th field: its first words."""
    field = record["fields"][index]
    quote = " ".join(field["serializedText"].split()[:6])
    return {
        "sectionId": field["sectionId"],
        "fieldId": field["fieldId"],
        "quote": quote,
        "verified": verify_quote(quote, field["serializedText"]),
    }


def finding_state(
    record: dict[str, Any],
    dimension_id: str,
    verdict: str = "pass",
    *,
    citations: tuple[int, ...] = (0, 3),
    questions: tuple[str, ...] = (),
    generation: int = 1,
    disposition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A drafted finding, optionally decided."""
    state: dict[str, Any] = {
        "status": "ok",
        "generation": generation,
        "finding": {
            "dimensionId": dimension_id,
            "model": record["model"],
            "verdict": verdict,
            "reasoning": f"Drafted reasoning for {dimension_id}.",
            "evidence": [citation(record, index) for index in citations],
            "questions": list(questions),
        },
    }
    if disposition is not None:
        state["disposition"] = disposition
    return state


def score_state(
    record: dict[str, Any],
    criterion_id: str,
    score: int,
    *,
    citations: tuple[int, ...] = (1,),
    generation: int = 1,
    disposition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A drafted score: documented by ``citations``, or not evidenced (at
    the scale minimum) when there are none."""
    basis: dict[str, Any] = (
        {"kind": "documented", "evidence": [citation(record, i) for i in citations]}
        if citations
        else {"kind": "not_evidenced"}
    )
    state: dict[str, Any] = {
        "status": "ok",
        "generation": generation,
        "scoreFinding": {
            "criterionId": criterion_id,
            "model": record["model"],
            "score": score,
            "justification": f"Drafted justification for {criterion_id}.",
            "basis": basis,
        },
    }
    if disposition is not None:
        state["disposition"] = disposition
    return state


def error_state(retryable: bool, code: str | None = None) -> dict[str, Any]:
    """A failed item: retryable (``provider_error``) or terminal."""
    kind = "retryable" if retryable else "terminal"
    return {
        "status": "error",
        "generation": 1,
        "errorMessage": f"The {kind} failure's own message.",
        "error": {
            "kind": kind,
            "code": code or ("provider_error" if retryable else "model_mismatch"),
        },
    }


def drafted_record(review_id: str = "rv-test") -> dict[str, Any]:
    """Every dimension and criterion drafted, none decided: verdicts pass,
    notClear, pass, fail, pass; scores 4, 2, 4, 3."""
    record = blank_record(review_id)
    verdicts = ["pass", "notClear", "pass", "fail", "pass"]
    for dimension_id, verdict in zip(dimension_ids(record), verdicts, strict=True):
        record["dimensions"][dimension_id] = finding_state(
            record, dimension_id, verdict
        )
    for criterion_id, score in zip(criterion_ids(record), [4, 2, 4, 3], strict=True):
        record["mca"]["criteria"][criterion_id] = score_state(
            record, criterion_id, score
        )
    return record
