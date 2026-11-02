"""Projects data: template identity, the default project's draft values, and
the Projects table's date labels."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from pcn_clone.app.projects_data import (
    default_project_meta,
    default_project_values,
    format_date,
    relative_days,
    resolve_timezone,
    template_badge,
    template_meta,
)
from pcn_clone.content import CONTENT_DIR, DEFAULT_PROJECT_FILE

NOW = datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC)


def ago(**delta: float) -> str:
    """An ISO timestamp ``delta`` before ``NOW``, as ``toISOString`` writes it."""
    moment = NOW - timedelta(**delta)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


# --- Template identity and the default project -------------------------------


def test_template_meta_names_the_template_and_its_default_criteria() -> None:
    assert template_meta() == {
        "templateId": "pcn_global",
        "templateVersion": "1.5.0",
        "criteriaSetId": "pcn_global_default",
        "criteriaVersion": "1.4.0",
    }


def test_template_badge_shows_major_version_and_label() -> None:
    assert template_badge() == "PCN v1 — Global"


def test_default_project_meta_is_a_create_project_input() -> None:
    assert default_project_meta() == {
        "title": "Upper Valley District Road Rehabilitation",
        "tags": ["Transport"],
        **template_meta(),
    }


def test_default_project_values_are_the_flat_field_answer_map() -> None:
    raw = json.loads((CONTENT_DIR / DEFAULT_PROJECT_FILE).read_text(encoding="utf-8"))
    answers = raw["submission"]["answers"]

    values = default_project_values()

    assert len(values) == 19
    assert list(values) == [answer["fieldId"] for answer in answers]
    assert values == {answer["fieldId"]: answer["answer"] for answer in answers}


def test_default_project_values_keep_list_row_ids() -> None:
    values = default_project_values()

    scope = values["scope_of_the_project"]
    risks = values["project_risks"]

    assert [row["_rowId"] for row in scope] == [
        "comp-design",
        "comp-works",
        "comp-equipment",
    ]
    assert [row["_rowId"] for row in risks] == [
        "risk-cost",
        "risk-permit",
        "risk-demand",
        "risk-climate",
    ]


def test_default_project_values_are_a_private_copy() -> None:
    first = default_project_values()
    first["scope_of_the_project"][0]["component"] = "changed"
    first["project_title"] = "changed"

    second = default_project_values()

    assert second["scope_of_the_project"][0]["component"] != "changed"
    assert second["project_title"] != "changed"


def test_default_project_values_survive_a_json_round_trip() -> None:
    values = default_project_values()
    assert json.loads(json.dumps(values)) == values


# --- format_date ---------------------------------------------------------------


def test_format_date_is_month_day_year_with_dots() -> None:
    assert format_date("2026-08-25T10:30:00.000Z", UTC) == "08.25.2026"


def test_format_date_pads_single_digits() -> None:
    assert format_date("2026-01-05T00:00:00.000Z", UTC) == "01.05.2026"


def test_format_date_uses_the_given_zone() -> None:
    late_utc = "2026-08-25T23:30:00.000Z"
    assert format_date(late_utc, UTC) == "08.25.2026"
    assert format_date(late_utc, ZoneInfo("Asia/Tokyo")) == "08.26.2026"
    assert format_date(late_utc, timezone(timedelta(hours=-5))) == "08.25.2026"


@pytest.mark.parametrize("bad", ["", "not a date", "2026-13-45T00:00:00Z", None, 42])
def test_format_date_is_an_em_dash_when_unparseable(bad: object) -> None:
    assert format_date(bad) == "—"


def test_format_date_reads_a_date_only_value_as_utc() -> None:
    assert format_date("2026-08-25", UTC) == "08.25.2026"


# --- relative_days ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("delta", "label"),
    [
        ({"seconds": 0}, "just now"),
        ({"seconds": 29}, "just now"),
        ({"seconds": 30}, "1 min ago"),
        ({"seconds": 89}, "1 min ago"),
        ({"seconds": 90}, "2 mins ago"),
        ({"minutes": 59}, "59 mins ago"),
        ({"minutes": 59, "seconds": 30}, "1 hour ago"),
        ({"minutes": 89}, "1 hour ago"),
        ({"minutes": 90}, "2 hours ago"),
        ({"hours": 23}, "23 hours ago"),
        ({"hours": 23, "minutes": 30}, "1 day ago"),
        ({"hours": 35}, "1 day ago"),
        ({"hours": 36}, "2 days ago"),
        ({"days": 42}, "42 days ago"),
        ({"days": 120}, "120 days ago"),
    ],
)
def test_relative_days_matches_the_listing_labels(
    delta: dict[str, float], label: str
) -> None:
    assert relative_days(ago(**delta), NOW) == label


def test_relative_days_reads_a_future_timestamp_as_just_now() -> None:
    assert relative_days("2026-10-07T12:00:00.000Z", NOW) == "just now"


@pytest.mark.parametrize("bad", ["", "yesterday", None])
def test_relative_days_is_recently_when_unparseable(bad: object) -> None:
    assert relative_days(bad, NOW) == "recently"


def test_relative_days_defaults_to_the_current_time() -> None:
    assert relative_days(datetime.now(UTC).isoformat()) == "just now"


# --- Helpers ---------------------------------------------------------------------


def test_resolve_timezone_accepts_iana_names_only() -> None:
    assert resolve_timezone("Europe/Skopje") == ZoneInfo("Europe/Skopje")
    assert resolve_timezone("Not/AZone") is None
    assert resolve_timezone("") is None
    assert resolve_timezone(None) is None
