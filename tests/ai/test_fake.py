"""The fake provider answers deterministically, inside the contracts, with
citations that verify."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

import pytest

from pcn_clone.ai.prompts import assessment_prompts, field_prompts, mca_prompts
from pcn_clone.ai.provider import FakeClient, ModelReply, ProviderError
from pcn_clone.ai.schemas import (
    ASSESSMENT_FINDING_FORMAT,
    FIELD_EVALUATION_FORMAT,
    MCA_SCORE_FINDING_FORMAT,
    AssessmentFinding,
    Citation,
    FieldEvaluation,
    McaScoreFinding,
    ReplyScope,
    assessment_finding_schema,
    field_evaluation_schema,
    mca_score_finding_schema,
)
from pcn_clone.content import load_assessment, load_criteria, load_mca, load_template
from pcn_clone.core.evidence import verify_quote
from pcn_clone.core.serialize import (
    SerializedField,
    canonicalize_submission,
    serialize_submission,
)
from tests.ai.support import default_fields

DIMENSIONS = [d.id for d in load_assessment().dimensions]
CRITERIA = [c.id for c in load_mca().matrix.criteria]


def _blank_fields() -> list[SerializedField]:
    template = load_template()
    blank = {
        "templateId": template.id,
        "answers": [
            {
                "sectionId": "investment_identification",
                "fieldId": "project_title",
                "answer": "",
            }
        ],
    }
    return serialize_submission(template, canonicalize_submission(template, blank))


def _assess(
    client: FakeClient, dimension_id: str, fields: Sequence[SerializedField]
) -> ModelReply:
    system, user = assessment_prompts(
        load_template(), load_assessment(), dimension_id, fields
    )
    return asyncio.run(
        client.complete(
            system=system,
            user=user,
            schema=assessment_finding_schema(fields),
            format_name=ASSESSMENT_FINDING_FORMAT,
        )
    )


def _score(
    client: FakeClient, criterion_id: str, fields: Sequence[SerializedField]
) -> ModelReply:
    system, user = mca_prompts(load_template(), load_mca(), criterion_id, fields)
    return asyncio.run(
        client.complete(
            system=system,
            user=user,
            schema=mca_score_finding_schema(fields, load_mca().matrix),
            format_name=MCA_SCORE_FINDING_FORMAT,
        )
    )


def _field_reply(client: FakeClient, answer: str) -> ModelReply:
    system, user = field_prompts(
        load_template(), load_criteria(), "investment_rationale", "objectives", answer
    )
    return asyncio.run(
        client.complete(
            system=system,
            user=user,
            schema=field_evaluation_schema(),
            format_name=FIELD_EVALUATION_FORMAT,
        )
    )


def _assert_verified(citations: Sequence[Citation]) -> None:
    text = {(f.section_id, f.field_id): f.serialized_text for f in default_fields()}
    for citation in citations:
        assert verify_quote(
            citation.quote, text[(citation.section_id, citation.field_id)]
        )


def test_field_reply_is_deterministic_and_valid() -> None:
    first = _field_reply(FakeClient(), "Cut travel time to the hospital.")
    second = _field_reply(FakeClient(), "Cut travel time to the hospital.")
    assert first == second
    reply = FieldEvaluation.model_validate(first.data)
    assert "2.2 Objectives" in reply.reasoning
    assert first.model == "fake/pcn-reviewer"


def test_blank_field_answer_fails() -> None:
    reply = FieldEvaluation.model_validate(_field_reply(FakeClient(), "").data)
    assert reply.verdict == "fail"


@pytest.mark.parametrize("dimension_id", DIMENSIONS)
def test_assessment_reply_cites_real_text(dimension_id: str) -> None:
    reply = _assess(FakeClient(), dimension_id, default_fields())
    finding = AssessmentFinding.model_validate(
        reply.data, context=ReplyScope(fields=default_fields())
    )
    assert 1 <= len(finding.evidence) <= 2
    _assert_verified(finding.evidence)
    label = load_assessment().get_dimension(dimension_id)
    assert label is not None
    assert label.label in finding.reasoning


@pytest.mark.parametrize("criterion_id", CRITERIA)
def test_mca_reply_is_documented_on_scale(criterion_id: str) -> None:
    matrix = load_mca().matrix
    reply = _score(FakeClient(), criterion_id, default_fields())
    finding = McaScoreFinding.model_validate(
        reply.data, context=ReplyScope(fields=default_fields(), matrix=matrix)
    )
    assert finding.basis.kind == "documented"
    assert matrix.scale_minimum <= finding.basis.score <= matrix.scale_maximum
    _assert_verified(finding.basis.evidence)


def test_blank_submission_gives_no_citations() -> None:
    fields = _blank_fields()
    finding = AssessmentFinding.model_validate(
        _assess(FakeClient(), DIMENSIONS[0], fields).data,
        context=ReplyScope(fields=fields),
    )
    assert finding.evidence == []
    assert finding.verdict == "notClear"
    score = McaScoreFinding.model_validate(
        _score(FakeClient(), CRITERIA[0], fields).data,
        context=ReplyScope(fields=fields, matrix=load_mca().matrix),
    )
    assert score.basis.kind == "not_evidenced"
    assert score.basis.score == 1


def test_failure_injection_by_id() -> None:
    client = FakeClient(fail={DIMENSIONS[1], CRITERIA[2], "objectives"})
    with pytest.raises(ProviderError) as raised:
        _assess(client, DIMENSIONS[1], default_fields())
    assert raised.value.kind == "retryable"
    with pytest.raises(ProviderError):
        _score(client, CRITERIA[2], default_fields())
    with pytest.raises(ProviderError):
        _field_reply(client, "x")
    _assess(client, DIMENSIONS[0], default_fields())
    _score(client, CRITERIA[0], default_fields())


def test_failure_injection_for_every_call() -> None:
    with pytest.raises(ProviderError, match="Injected fake failure"):
        _assess(FakeClient(fail={"*"}), DIMENSIONS[0], default_fields())


def test_delay() -> None:
    started = time.perf_counter()
    _field_reply(FakeClient(delay_seconds=0.05), "x")
    assert time.perf_counter() - started >= 0.05


def test_unknown_format_is_terminal() -> None:
    with pytest.raises(ProviderError) as raised:
        asyncio.run(
            FakeClient().complete(system="s", user="u", schema={}, format_name="other")
        )
    assert raised.value.kind == "terminal"
