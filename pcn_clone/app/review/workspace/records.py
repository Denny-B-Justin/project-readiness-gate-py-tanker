"""Reading the review record's JSON: item states, dispositions and the field
snapshot citations resolve against.

The record arrives from the browser as plain JSON in the review store's
version 2 shape (camelCase keys). An item state is ``{"status": "pending" |
"error" | "ok", "generation", ...}``: an error carries ``error`` (``{"kind":
"retryable" | "terminal", "code"}``) and ``errorMessage``; an ok dimension
carries ``finding`` and an ok criterion ``scoreFinding``, each with an
optional reviewer ``disposition``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

JsonObject = Mapping[str, Any]

LOCATION: Final = "{section} — {field}"
"""Where a citation points, by its field's snapshotted labels."""

LOCATION_MISSING: Final = "{ref} (not in snapshot)"
"""A citation whose field the snapshot does not hold, by its reference."""

FieldIndex = Mapping[str, JsonObject]
"""Snapshotted fields keyed ``"<sectionId>/<fieldId>"``."""

PENDING: JsonObject = {"status": "pending", "generation": 0}
"""The state of an item the record has no entry for."""


def ref_key(ref: JsonObject) -> str:
    """``"<sectionId>/<fieldId>"`` for a citation or field."""
    return f"{ref.get('sectionId', '')}/{ref.get('fieldId', '')}"


def field_index(fields: Iterable[JsonObject]) -> dict[str, JsonObject]:
    """The field snapshot keyed by reference."""
    return {ref_key(field): field for field in fields}


def location_label(fields: FieldIndex, ref: JsonObject) -> str:
    """ "Section — Field" from the snapshot; the raw reference, marked, when
    the snapshot does not hold it."""
    field = fields.get(ref_key(ref))
    if field is None:
        return LOCATION_MISSING.format(ref=ref_key(ref))
    return LOCATION.format(
        section=field.get("sectionLabel", ""), field=field.get("fieldLabel", "")
    )


def as_object(value: Any) -> JsonObject:
    """``value`` when it is a JSON object, else an empty one."""
    return value if isinstance(value, Mapping) else {}


def as_list(value: Any) -> list[Any]:
    """``value`` when it is a JSON array, else an empty one."""
    return list(value) if isinstance(value, list) else []


def state_of(states: JsonObject, item: str) -> JsonObject:
    """The state of ``item``, pending when the map has none."""
    state = states.get(item)
    return state if isinstance(state, Mapping) else PENDING


def status_of(state: JsonObject) -> str:
    """``pending``, ``error`` or ``ok``."""
    status = state.get("status")
    return status if status in ("error", "ok") else "pending"


def disposition_of(state: JsonObject) -> JsonObject | None:
    """The reviewer's decision on a completed item, if any."""
    if status_of(state) != "ok":
        return None
    disposition = state.get("disposition")
    return disposition if isinstance(disposition, Mapping) else None


def is_decided(state: JsonObject) -> bool:
    """True once the reviewer has dealt with a completed item."""
    return disposition_of(state) is not None
