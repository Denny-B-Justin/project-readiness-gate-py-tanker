"""The compiled ``pcn_global`` content: template, criteria, assessment and MCA
sets, and the default project, each validated on first load and cached.

Every loader returns the same cached instance on each call. Attribute
assignment is blocked; nested containers are shared, do not mutate them
(copy first when an answer needs changing).
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from pcn_clone.content.models import (
    AssessmentSet,
    CriteriaSet,
    DefaultProject,
    McaSet,
    Template,
)

CONTENT_DIR = Path(__file__).resolve().parent

TEMPLATE_FILE = "template_pcn_global.json"
CRITERIA_FILE = "criteria_pcn_global_default.json"
ASSESSMENT_FILE = "assessment_pcn_global_reviewer_default.json"
MCA_FILE = "mca_pcn_global_mca_default.json"
DEFAULT_PROJECT_FILE = "default_project_upper_valley_district_road.json"


def read_content_json(name: str) -> Any:
    """The parsed JSON of one content file."""
    return json.loads((CONTENT_DIR / name).read_text(encoding="utf-8"))


@cache
def load_template() -> Template:
    """The ``pcn_global`` template (cached and shared; do not mutate)."""
    return Template.model_validate(read_content_json(TEMPLATE_FILE))


@cache
def load_criteria() -> CriteriaSet:
    """The default per-field criteria set (cached and shared; do not mutate)."""
    return CriteriaSet.model_validate(read_content_json(CRITERIA_FILE))


@cache
def load_assessment() -> AssessmentSet:
    """The default reviewer assessment set (cached and shared; do not mutate)."""
    return AssessmentSet.model_validate(read_content_json(ASSESSMENT_FILE))


@cache
def load_mca() -> McaSet:
    """The default MCA set (cached and shared; do not mutate)."""
    return McaSet.model_validate(read_content_json(MCA_FILE))


@cache
def load_default_project() -> DefaultProject:
    """The Upper Valley District Road example project (cached and shared; do
    not mutate its answers)."""
    return DefaultProject.model_validate(read_content_json(DEFAULT_PROJECT_FILE))


__all__ = [
    "CONTENT_DIR",
    "load_assessment",
    "load_criteria",
    "load_default_project",
    "load_mca",
    "load_template",
    "read_content_json",
]
