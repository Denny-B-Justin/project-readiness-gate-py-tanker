"""The prompt builders produce the golden prompts exactly."""

from __future__ import annotations

from typing import Any

import pytest

from pcn_clone.ai.prompts import assessment_prompts, field_prompts, mca_prompts
from pcn_clone.content import (
    load_assessment,
    load_criteria,
    load_mca,
    load_template,
)
from pcn_clone.core.prepare import prepare_field_answer
from tests.ai.support import default_answer, default_answers, default_fields
from tests.helpers import load_fixture

FIELD_PROMPTS = load_fixture("prompts/field_prompts.json")
ASSESSMENT_PROMPTS = load_fixture("prompts/assessment_prompts.json")
MCA_PROMPTS = load_fixture("prompts/mca_prompts.json")


def test_fixture_coverage() -> None:
    template = load_template()
    assert list(FIELD_PROMPTS) == [field.id for _, field in template.iter_fields()]
    assert list(ASSESSMENT_PROMPTS) == [d.id for d in load_assessment().dimensions]
    assert list(MCA_PROMPTS) == [c.id for c in load_mca().matrix.criteria]


@pytest.mark.parametrize("field_id", list(FIELD_PROMPTS))
def test_field_prompts(field_id: str) -> None:
    expected: dict[str, Any] = FIELD_PROMPTS[field_id]
    template = load_template()
    section_id = expected["sectionId"]
    prepared = prepare_field_answer(
        template, section_id, field_id, default_answer(field_id), default_answers()
    )
    assert prepared.ok
    system, user = field_prompts(
        template, load_criteria(), section_id, field_id, prepared.answer_text or ""
    )
    assert system == expected["system"]
    assert user == expected["user"]


@pytest.mark.parametrize("dimension_id", list(ASSESSMENT_PROMPTS))
def test_assessment_prompts(dimension_id: str) -> None:
    expected = ASSESSMENT_PROMPTS[dimension_id]
    system, user = assessment_prompts(
        load_template(), load_assessment(), dimension_id, default_fields()
    )
    assert system == expected["system"]
    assert user == expected["user"]


@pytest.mark.parametrize("criterion_id", list(MCA_PROMPTS))
def test_mca_prompts(criterion_id: str) -> None:
    expected = MCA_PROMPTS[criterion_id]
    system, user = mca_prompts(
        load_template(), load_mca(), criterion_id, default_fields()
    )
    assert system == expected["system"]
    assert user == expected["user"]


def test_blank_field_answer_is_marked() -> None:
    _, user = field_prompts(
        load_template(),
        load_criteria(),
        "investment_identification",
        "project_title",
        " \n﻿",
    )
    assert '## Proposer\'s answer\n"""\n(no answer provided)\n"""' in user


def test_unknown_ids_raise() -> None:
    template = load_template()
    with pytest.raises(LookupError, match='Unknown field "nope/nope"'):
        field_prompts(template, load_criteria(), "nope", "nope", "x")
    with pytest.raises(LookupError, match="has no dimension"):
        assessment_prompts(template, load_assessment(), "nope", default_fields())
    with pytest.raises(LookupError, match="has no criterion"):
        mca_prompts(template, load_mca(), "nope", default_fields())


def test_set_for_another_template_raises() -> None:
    template = load_template().model_copy(update={"id": "other"})
    with pytest.raises(ValueError, match='targets template "pcn_global"'):
        assessment_prompts(
            template, load_assessment(), "internal_coherence", default_fields()
        )
    with pytest.raises(ValueError, match='targets template "pcn_global"'):
        mca_prompts(template, load_mca(), "environmental_impact", default_fields())
