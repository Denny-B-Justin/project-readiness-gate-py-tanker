"""Data and formatting for the Projects workflow.

The browser owns the project store (``assets/store.js``); this module
supplies what Python knows: the template and criteria identity a new project
records, the default project's metadata and draft values, and the date
labels the Projects table shows.
"""

from __future__ import annotations

import copy
import math
from datetime import UTC, datetime, tzinfo
from typing import Any, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pcn_clone.content import load_criteria, load_default_project, load_template


class TemplateMeta(TypedDict):
    """The template and criteria identity stamped on every project record."""

    templateId: str
    templateVersion: str
    criteriaSetId: str
    criteriaVersion: str


class ProjectMeta(TemplateMeta):
    """Everything ``pcnStore.createProject`` takes: title, tags and identity."""

    title: str
    tags: list[str]


def template_meta() -> TemplateMeta:
    """The template and its default criteria set, as a new project records
    them."""
    template = load_template()
    criteria = load_criteria()
    if criteria.template_id != template.id:
        raise ValueError(
            f'Criteria set "{criteria.id}" belongs to template '
            f'"{criteria.template_id}", not "{template.id}".'
        )
    return {
        "templateId": template.id,
        "templateVersion": template.version,
        "criteriaSetId": criteria.id,
        "criteriaVersion": criteria.version,
    }


def template_badge() -> str:
    """The short template label used on default-project cards, for example
    ``"PCN v1 — Global"`` (major version and template label)."""
    template = load_template()
    major = template.version.split(".")[0] or template.version
    return f"PCN v{major} — {template.label}"


def default_project_meta() -> ProjectMeta:
    """The record metadata for a project cloned from the default: its title
    and tags plus the identity of the template it answers."""
    project = load_default_project()
    meta = template_meta()
    if project.submission.template_id != meta["templateId"]:
        raise ValueError(
            f'Default project "{project.id}" references unknown template '
            f'"{project.submission.template_id}".'
        )
    return {
        "title": project.title,
        "tags": list(project.tags),
        **meta,
    }


def default_project_values() -> dict[str, Any]:
    """The default project's answers as a draft ``values`` map: one entry per
    field id holding the raw answer. List rows keep their durable ``_rowId``.
    The result is a deep copy, safe to mutate.

    Raises ``ValueError`` when a field id is answered twice.
    """
    project = load_default_project()
    values: dict[str, Any] = {}
    for answer in project.submission.answers:
        if answer.field_id in values:
            raise ValueError(
                f'Default project "{project.id}" repeats field "{answer.field_id}".'
            )
        values[answer.field_id] = copy.deepcopy(answer.answer)
    return values


# --- Date labels -------------------------------------------------------------


def resolve_timezone(name: str | None) -> tzinfo | None:
    """The IANA zone ``name`` reported by the browser, or ``None`` (the
    server's local zone) when it is missing or unknown."""
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def parse_iso(iso: object) -> datetime | None:
    """An ISO 8601 timestamp as an aware datetime, or ``None`` when it does
    not parse. A date-only value reads as UTC midnight and a date-time
    without an offset as local time, as ``Date.parse`` reads them."""
    if not isinstance(iso, str) or not iso:
        return None
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC) if "T" not in iso else parsed.astimezone()
    return parsed


def format_date(iso: object, tz: tzinfo | None = None) -> str:
    """``"MM.DD.YYYY"`` for a timestamp in ``tz`` (the server's local zone
    when ``None``), or an em dash when it does not parse."""
    parsed = parse_iso(iso)
    if parsed is None:
        return "—"
    local = parsed.astimezone(tz)
    return f"{local.month:02d}.{local.day:02d}.{local.year}"


def _js_round(value: float) -> int:
    """``Math.round``: halves round towards positive infinity."""
    return math.floor(value + 0.5)


def _plural(count: int, unit: str) -> str:
    return f"{count} {unit}{'' if count == 1 else 's'} ago"


def relative_days(iso: object, now: datetime | None = None) -> str:
    """How long before ``now`` a timestamp is: ``"just now"`` under a minute,
    then ``"N min(s) ago"``, ``"N hour(s) ago"`` and ``"N day(s) ago"``, each
    rounded to the nearest unit. ``"recently"`` when the timestamp does not
    parse; a future timestamp reads as ``"just now"``."""
    parsed = parse_iso(iso)
    if parsed is None:
        return "recently"
    reference = now if now is not None else datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.astimezone()
    mins = _js_round((reference - parsed).total_seconds() / 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return _plural(mins, "min")
    hours = _js_round(mins / 60)
    if hours < 24:
        return _plural(hours, "hour")
    return _plural(_js_round(hours / 24), "day")
