"""The score adjustment editor's state, as data and transitions: the
reference the score editor in ``assets/review-ui.js`` is checked against
(``tests/browser/test_review_workspace.py`` runs both over the same
transitions).

The invariant they make structural mirrors the model contract and the record's
own validation: a ``not_evidenced`` basis pairs only with the scale-minimum
score, since silence cannot earn more than the floor. Raising the score off
the floor falls back to a documented basis, and "not evidenced" is refused
off the floor.

Drafts and dispositions use the record's JSON keys, so the same shapes
serve both sides.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from pcn_clone.app.review.workspace.records import JsonObject, as_list, as_object
from pcn_clone.core.jsstr import js_trim

BasisKind = Literal["documented", "not_evidenced"]


class EvidenceDraft(TypedDict):
    """One citation under curation; a blank quote or note is left out."""

    sectionId: str
    fieldId: str
    quote: NotRequired[str]
    note: NotRequired[str]


class AdjustDraft(TypedDict):
    """What the reviewer has picked and written."""

    score: int
    rationale: str
    basisKind: BasisKind
    evidence: list[EvidenceDraft]


class AdjustDraftIssues(TypedDict):
    """What still blocks a save, one flag per inline message."""

    rationaleMissing: bool
    evidenceMissing: bool


class IncompleteAdjustmentError(ValueError):
    """An adjustment that cannot be saved was asked for its disposition."""


def _evidence_draft(ref: JsonObject, *, with_note: bool) -> EvidenceDraft:
    draft: EvidenceDraft = {
        "sectionId": str(ref.get("sectionId", "")),
        "fieldId": str(ref.get("fieldId", "")),
    }
    if "quote" in ref:
        draft["quote"] = str(ref["quote"])
    if with_note and "note" in ref:
        draft["note"] = str(ref["note"])
    return draft


def _basis_kind(basis: JsonObject) -> BasisKind:
    return "not_evidenced" if basis.get("kind") == "not_evidenced" else "documented"


def initial_adjust_draft(
    score_finding: JsonObject, initial: JsonObject | None = None
) -> AdjustDraft:
    """The opening draft: a prior adjustment to continue from, else the AI
    draft's score and citations. The rationale is the reviewer's own
    argument, so without a prior adjustment it starts empty rather than
    prefilled with the AI's words."""
    if initial is not None:
        basis = as_object(initial.get("basis"))
        kind = _basis_kind(basis)
        return {
            "score": int(initial.get("finalScore", 0)),
            "rationale": str(initial.get("rationale", "")),
            "basisKind": kind,
            "evidence": (
                [
                    _evidence_draft(as_object(ref), with_note=True)
                    for ref in as_list(basis.get("evidence"))
                ]
                if kind == "documented"
                else []
            ),
        }
    basis = as_object(score_finding.get("basis"))
    kind = _basis_kind(basis)
    return {
        "score": int(score_finding.get("score", 0)),
        "rationale": "",
        "basisKind": kind,
        "evidence": (
            [
                _evidence_draft(as_object(ref), with_note=False)
                for ref in as_list(basis.get("evidence"))
            ]
            if kind == "documented"
            else []
        ),
    }


def with_score(draft: AdjustDraft, score: int, scale_minimum: int) -> AdjustDraft:
    """Pick a score. Off the floor a not-evidenced basis is inexpressible,
    so it falls back to documented (and the evidence requirement shows)."""
    basis_kind: BasisKind = (
        "documented"
        if score != scale_minimum and draft["basisKind"] == "not_evidenced"
        else draft["basisKind"]
    )
    return {**draft, "score": score, "basisKind": basis_kind}


def with_basis_kind(
    draft: AdjustDraft, basis_kind: BasisKind, scale_minimum: int
) -> AdjustDraft:
    """Pick a basis; "not evidenced" off the scale floor is refused."""
    if basis_kind == "not_evidenced" and draft["score"] != scale_minimum:
        return draft
    return {**draft, "basisKind": basis_kind}


def adjust_draft_issues(draft: AdjustDraft) -> AdjustDraftIssues:
    """A blank rationale (whitespace is not writing), and a documented
    basis without citations."""
    return {
        "rationaleMissing": js_trim(draft["rationale"]) == "",
        "evidenceMissing": draft["basisKind"] == "documented" and not draft["evidence"],
    }


def can_save_adjust_draft(draft: AdjustDraft) -> bool:
    """True when nothing blocks saving the draft as an adjustment."""
    issues = adjust_draft_issues(draft)
    return not issues["rationaleMissing"] and not issues["evidenceMissing"]


def to_adjusted_disposition(draft: AdjustDraft) -> dict[str, object]:
    """The ``adjusted`` disposition a savable draft becomes, blank quotes
    and notes left out. Raises ``IncompleteAdjustmentError`` otherwise."""
    if not can_save_adjust_draft(draft):
        raise IncompleteAdjustmentError(
            "An incomplete adjustment cannot become a disposition."
        )
    if draft["basisKind"] == "not_evidenced":
        basis: dict[str, object] = {"kind": "not_evidenced"}
    else:
        evidence: list[dict[str, str]] = []
        for ref in draft["evidence"]:
            entry = {"sectionId": ref["sectionId"], "fieldId": ref["fieldId"]}
            if ref.get("quote"):
                entry["quote"] = ref["quote"]
            if ref.get("note"):
                entry["note"] = ref["note"]
            evidence.append(entry)
        basis = {"kind": "documented", "evidence": evidence}
    return {
        "kind": "adjusted",
        "finalScore": draft["score"],
        "rationale": draft["rationale"],
        "basis": basis,
    }
