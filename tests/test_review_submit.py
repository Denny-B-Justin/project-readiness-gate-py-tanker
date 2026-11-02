"""Submit on the server: a form's answers become the canonical submission
(template order, blanks for the unanswered, unknown keys left out), and the
intake callback freezes them into the snapshot a review is created from;
for the default project its fields and digest are the reference's. Every
failure, expected or not, still answers the request."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from pcn_clone.ai import AiConfigurationError
from pcn_clone.app.projects_data import default_project_values
from pcn_clone.app.review import submit
from pcn_clone.app.review.messages import SUBMIT_UNEXPECTED
from pcn_clone.app.review.submit import UNREADABLE_ANSWERS, submission_from_values
from pcn_clone.content import load_assessment, load_mca, load_template
from tests.helpers import load_fixture


def intake(request: Any) -> dict[str, Any]:
    return asyncio.run(submit.intake(request))


def test_answers_follow_the_template_with_blanks_for_the_rest() -> None:
    submission = submission_from_values(
        {"objectives": "Reopen the road.", "stale": "x"}
    )
    fields = list(load_template().iter_fields())

    assert submission["templateId"] == "pcn_global"
    assert [(a["sectionId"], a["fieldId"]) for a in submission["answers"]] == [
        (section.id, field.id) for section, field in fields
    ]
    answers = {a["fieldId"]: a["answer"] for a in submission["answers"]}
    assert answers["objectives"] == "Reopen the road."
    assert answers["project_title"] == ""
    assert answers["scope_of_the_project"] == []
    assert answers["investment_cost_estimate"] == {
        "componentCosts": {},
        "narratives": {},
    }
    assert "stale" not in answers


def test_the_default_project_freezes_to_the_reference_snapshot() -> None:
    expected = load_fixture("serialized_default.json")

    response = intake({"nonce": "n1", "values": default_project_values()})

    assert response["nonce"] == "n1"
    assert response["ok"] is True
    snapshot = response["intake"]
    assert snapshot["fields"] == expected["fields"]
    assert snapshot["assessmentInputDigest"] == expected["digest"]
    assert snapshot["assessmentInputDigest"].startswith("aiv1-9c67")
    assert snapshot["submission"]["answers"] == expected["canonicalAnswers"]
    assert [d["id"] for d in snapshot["dimensionDefs"]] == [
        d.id for d in load_assessment().dimensions
    ]
    assert [c["id"] for c in snapshot["matrix"]["criteria"]] == [
        c.id for c in load_mca().matrix.criteria
    ]
    assert snapshot["model"] == "fake/pcn-reviewer"
    assert (snapshot["mcaSetId"], snapshot["mcaSetVersion"]) == (
        "pcn_global_mca_default",
        "0.1.0",
    )


def test_answers_that_are_not_a_map_are_refused() -> None:
    assert intake({"nonce": "n2", "values": ["x"]}) == {
        "nonce": "n2",
        "ok": False,
        "errorMessage": UNREADABLE_ANSWERS,
    }
    assert intake(None) == {
        "nonce": None,
        "ok": False,
        "errorMessage": UNREADABLE_ANSWERS,
    }


def test_a_malformed_answer_is_refused_with_the_reason() -> None:
    response = intake({"nonce": "n3", "values": {"objectives": 42}})

    assert response["ok"] is False
    assert response["nonce"] == "n3"
    assert "answer" in response["errorMessage"]


def test_unusable_ai_settings_refuse_the_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(_submission: Any) -> Any:
        raise AiConfigurationError("OPENROUTER_API_KEY is not set.")

    monkeypatch.setattr(submit, "build_snapshot", broken)

    assert intake({"nonce": "n4", "values": {}}) == {
        "nonce": "n4",
        "ok": False,
        "errorMessage": "OPENROUTER_API_KEY is not set.",
    }


def test_an_unexpected_failure_still_answers_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(_submission: Any) -> Any:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(submit, "build_snapshot", broken)

    assert intake({"nonce": "n5", "values": {}}) == {
        "nonce": "n5",
        "ok": False,
        "errorMessage": SUBMIT_UNEXPECTED,
    }
