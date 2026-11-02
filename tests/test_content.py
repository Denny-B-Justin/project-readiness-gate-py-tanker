"""Content loading, strict validation and the MCA matrix invariants."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from pcn_clone.content import (
    load_assessment,
    load_criteria,
    load_default_project,
    load_mca,
    load_template,
    read_content_json,
)
from pcn_clone.content.models import (
    AssessmentSet,
    DefaultProject,
    McaMatrix,
    McaSet,
    Template,
)
from pcn_clone.core.serialize import (
    canonicalize_submission,
    input_digest,
    serialize_submission,
)
from tests.helpers import load_fixture


def test_all_content_loads_and_is_cached() -> None:
    template = load_template()
    assert template.id == "pcn_global"
    assert sum(len(section.fields) for section in template.sections) == 19
    assert load_template() is template
    assert load_criteria().template_id == "pcn_global"
    assert len(load_criteria().fields) == 19
    assert len(load_assessment().dimensions) == 5
    assert len(load_mca().matrix.criteria) == 4
    project = load_default_project()
    assert project.submission.template_id == "pcn_global" and project.tags == [
        "Transport"
    ]


def test_every_criterion_targets_a_template_field() -> None:
    template = load_template()
    for entry in load_criteria().fields:
        assert template.get_field(entry.section_id, entry.field_id) is not None
    assert load_criteria().get("investment_identification", "project_title") is not None


def test_models_round_trip_to_the_source_json() -> None:
    raw = read_content_json("template_pcn_global.json")
    shaped = load_template().to_json()
    for section in shaped["sections"]:
        for field in section["fields"]:
            field_input = field.get("input")
            if (
                field_input
                and field_input["type"] == "list"
                and field_input["conditionalRequirements"] == []
            ):
                original = next(
                    f
                    for s in raw["sections"]
                    for f in s["fields"]
                    if f["id"] == field["id"]
                )
                if "conditionalRequirements" not in original["input"]:
                    del field_input["conditionalRequirements"]
    assert shaped == raw
    assert load_mca().to_json() == read_content_json("mca_pcn_global_mca_default.json")
    assert load_assessment().to_json() == read_content_json(
        "assessment_pcn_global_reviewer_default.json"
    )
    assert load_criteria().to_json() == read_content_json(
        "criteria_pcn_global_default.json"
    )
    assert load_default_project().to_json() == read_content_json(
        "default_project_upper_valley_district_road.json"
    )


# --- Strictness --------------------------------------------------------------


def _template_raw() -> dict[str, Any]:
    return copy.deepcopy(read_content_json("template_pcn_global.json"))


def test_unknown_keys_are_rejected() -> None:
    raw = _template_raw()
    raw["sections"][0]["fields"][0]["guidence"] = "typo"
    with pytest.raises(ValidationError, match="guidence"):
        Template.model_validate(raw)


def test_snake_case_keys_are_not_accepted_for_camel_case_properties() -> None:
    raw = _template_raw()
    worksheet = raw["sections"][3]["fields"][0]["input"]
    worksheet["row_source"] = worksheet.pop("rowSource")
    with pytest.raises(ValidationError, match=r"rowSource\n\s+Field required"):
        Template.model_validate(raw)


def test_optional_properties_may_be_omitted_but_not_null() -> None:
    raw = _template_raw()
    raw["description"] = None
    with pytest.raises(ValidationError, match="must be omitted, not null"):
        Template.model_validate(raw)
    del raw["description"]
    assert Template.model_validate(raw).description is None


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        pytest.param(
            lambda raw: raw.update(version=1),
            "Input should be a valid string",
            id="number-for-string",
        ),
        pytest.param(
            lambda raw: raw["sections"][0].update(fields=[]),
            "at least 1 item",
            id="section-without-fields",
        ),
        pytest.param(
            lambda raw: raw["sections"][0]["fields"][0].update(title=""),
            "at least 1 character",
            id="empty-title",
        ),
        pytest.param(
            lambda raw: raw["sections"][0]["fields"][0]["input"].update(
                type="financial_matrix"
            ),
            "Input tag 'financial_matrix' found using 'type' does not match",
            id="unmodelled-input-kind",
        ),
        pytest.param(
            lambda raw: raw["sections"][3]["fields"][0]["input"]["summary"].update(
                includeTotalRow="true"
            ),
            "Input should be a valid boolean",
            id="string-for-boolean",
        ),
        pytest.param(
            lambda raw: raw["sections"][3]["fields"][1]["input"]["computedRows"][
                0
            ].update(subtract=["a"]),
            r"subtract\.1\n\s+Field required",
            id="one-sided-subtraction",
        ),
    ],
)
def test_malformed_templates_are_rejected(mutate: Any, message: str) -> None:
    raw = _template_raw()
    mutate(raw)
    with pytest.raises(ValidationError, match=message):
        Template.model_validate(raw)


def test_duplicate_assessment_dimensions_are_rejected() -> None:
    raw = copy.deepcopy(
        read_content_json("assessment_pcn_global_reviewer_default.json")
    )
    raw["dimensions"].append(raw["dimensions"][0])
    with pytest.raises(ValidationError, match="Duplicate dimension id"):
        AssessmentSet.model_validate(raw)


def test_default_project_answers_must_have_answer_shapes() -> None:
    raw = copy.deepcopy(
        read_content_json("default_project_upper_valley_district_road.json")
    )
    raw["submission"]["answers"][0]["answer"] = 5
    with pytest.raises(ValidationError, match="answer shape"):
        DefaultProject.model_validate(raw)


# --- MCA invariants ----------------------------------------------------------


def _matrix_raw() -> dict[str, Any]:
    return copy.deepcopy(read_content_json("mca_pcn_global_mca_default.json")["matrix"])


def test_default_matrix_satisfies_the_invariants() -> None:
    matrix = load_mca().matrix
    assert [entry.value for entry in matrix.scale] == [1, 2, 3, 4, 5]
    assert sum(criterion.weight for criterion in matrix.criteria) == 100
    thresholds = [band.min_percent_of_maximum for band in matrix.bands]
    assert thresholds == sorted(thresholds, reverse=True) and thresholds[-1] == 0


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda m: m["criteria"][0].update(weight=31),
            "sum to exactly 100; they sum to 101",
        ),
        (lambda m: m["scale"][1].update(value=3), "position 1 has value 3"),
        (
            lambda m: m["scale"].pop(),
            'has a descriptor for "5", which is not a scale value',
        ),
        (
            lambda m: m["criteria"][0]["descriptors"].pop("3"),
            "has no descriptor for scale value 3",
        ),
        (lambda m: m["bands"][-1].update(minPercentOfMaximum=10), "must be exactly 0"),
        (lambda m: m["bands"][1].update(minPercentOfMaximum=80), "strictly descending"),
        (
            lambda m: m["bands"].append(dict(m["bands"][-1], minPercentOfMaximum=0)),
            "Duplicate band id",
        ),
        (
            lambda m: m["criteria"].append(dict(m["criteria"][0], weight=1)),
            "Duplicate criterion id",
        ),
        (lambda m: m["criteria"][0].update(weight=0), "greater than 0"),
        (lambda m: m["criteria"][0].update(weight=30.5), "integer"),
        (
            lambda m: m["bands"][0].update(minPercentOfMaximum=101),
            "less than or equal to 100",
        ),
        (lambda m: m["scale"][0].update(value=True), "expected a finite number"),
    ],
    ids=[
        "weights-sum-to-101",
        "scale-not-contiguous",
        "descriptor-off-scale",
        "descriptor-missing",
        "last-band-not-zero",
        "bands-not-descending",
        "duplicate-band",
        "duplicate-criterion",
        "zero-weight",
        "fractional-weight",
        "band-above-100",
        "boolean-scale-value",
    ],
)
def test_matrix_invariants_are_enforced(mutate: Any, message: str) -> None:
    raw = _matrix_raw()
    mutate(raw)
    with pytest.raises(ValidationError, match=message):
        McaMatrix.model_validate(raw)


def test_integral_floats_are_accepted_as_integers() -> None:
    raw = _matrix_raw()
    raw["criteria"][0]["weight"] = 30.0
    assert McaMatrix.model_validate(raw).criteria[0].weight == 30


def test_mca_set_rejects_unknown_keys() -> None:
    raw = copy.deepcopy(read_content_json("mca_pcn_global_mca_default.json"))
    raw["matrix"]["weights"] = {}
    with pytest.raises(ValidationError, match=r"weights\n\s+Extra inputs"):
        McaSet.model_validate(raw)


# --- Golden content check ----------------------------------------------------


def test_loaders_match_golden_content_check() -> None:
    golden = load_fixture("content_check.json")
    template = load_template()
    mca = load_mca()
    assert template.version == golden["templateVersion"]
    assert load_criteria().version == golden["criteriaVersion"]
    assert load_assessment().version == golden["assessmentVersion"]
    assert mca.version == golden["mcaVersion"]
    assert [
        {"sectionId": section.id, "fieldId": field.id, "kind": field.kind}
        for section, field in template.iter_fields()
    ] == [
        {key: entry[key] for key in ("sectionId", "fieldId", "kind")}
        for entry in golden["fieldOrder"]
    ]
    for (_, field), entry in zip(
        template.iter_fields(), golden["fieldOrder"], strict=True
    ):
        assert field.number == entry["number"]
        assert field.title == entry["title"]
        declared = field.input.type if field.input is not None else None
        assert declared == entry["declaredInputType"]
    assert [d.id for d in load_assessment().dimensions] == golden["dimensionIds"]
    assert [c.id for c in mca.matrix.criteria] == golden["criterionIds"]
    scale = golden["scale"]
    assert [entry.to_json() for entry in mca.matrix.scale] == scale["entries"]
    assert mca.matrix.scale_minimum == scale["min"]
    assert mca.matrix.scale_maximum == scale["max"]
    assert [band.to_json() for band in mca.matrix.bands] == golden["bands"]
    assert {c.id: c.weight for c in mca.matrix.criteria} == golden["weights"]
    assert [
        {"id": s.id, "number": s.number, "title": s.title} for s in template.sections
    ] == golden["sections"]
    project = load_default_project()
    assert {
        "id": project.id,
        "version": project.version,
        "title": project.title,
    } == golden["defaultProject"]
    canonical = canonicalize_submission(template, project.submission)
    digest = input_digest(serialize_submission(template, canonical))
    assert digest == golden["defaultInputDigest"]
