"""Shared test helpers: golden-fixture loading and JSON shaping of results.

A golden fixture that is missing fails the run (at collection time for
parametrized cases), so a deleted or renamed fixture cannot silently turn
its tests into skips.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from pcn_clone.core.numbers import AmountParse, ParsedAmount
from pcn_clone.core.prepare import PrepareResult

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture_path(name: str) -> Path:
    """The path of a golden fixture file, failing when it is absent."""
    path = FIXTURES / name
    if not path.exists():
        pytest.fail(f"golden fixture is missing: {path}", pytrace=False)
    return path


def load_fixture(name: str) -> Any:
    """Load a golden fixture, failing when it is absent."""
    return json.loads(fixture_path(name).read_text(encoding="utf-8"))


def fixture_params(name: str, key: str | None = None, label: str = "case") -> list[Any]:
    """Golden cases as ``pytest.param`` objects with readable ids."""
    data = load_fixture(name)
    cases = data[key] if key is not None else data
    return [
        pytest.param(
            case,
            id=f"{label}-{index}-{case['name']}"
            if isinstance(case, dict) and "name" in case
            else f"{label}-{index}",
        )
        for index, case in enumerate(cases)
    ]


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


def as_json(value: Any, *, keep_none: bool = False) -> Any:
    """A result as JSON-shaped data: dataclass fields camelCased, content
    models by alias, tuples as lists, and ``None`` dataclass fields omitted
    unless ``keep_none``."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            _camel(field.name): as_json(getattr(value, field.name), keep_none=keep_none)
            for field in dataclasses.fields(value)
            if keep_none or getattr(value, field.name) is not None
        }
    if isinstance(value, BaseModel):
        return value.model_dump(by_alias=True, exclude_none=True, mode="json")
    if isinstance(value, (list, tuple)):
        return [as_json(item, keep_none=keep_none) for item in value]
    if isinstance(value, dict):
        return {key: as_json(item, keep_none=keep_none) for key, item in value.items()}
    return value


def prepared_json(result: Any) -> dict[str, Any]:
    """A per-kind prepared result in its JSON shape: ``{ok: false, issues}``,
    or ``{ok: true, answerText}`` plus a worksheet's rows and grand total."""
    if not result.ok:
        return {"ok": False, "issues": as_json(list(result.issues))}
    shaped: dict[str, Any] = {"ok": True, "answerText": result.answer_text}
    rows = getattr(result, "rows", None)
    if rows:
        shaped["rows"] = as_json(list(rows), keep_none=True)
    grand_total = getattr(result, "grand_total", None)
    if grand_total is not None:
        shaped["grandTotal"] = grand_total
    return shaped


def prepare_result_json(result: PrepareResult) -> dict[str, Any]:
    """A dispatcher result in the fixtures' ``{ok, serializedText, issues}`` shape."""
    return {
        "ok": result.ok,
        "serializedText": result.answer_text,
        "issues": list(result.issues),
    }


def amount_json(result: AmountParse) -> dict[str, Any]:
    """A worksheet amount parse as ``{ok, value}`` or ``{ok, reason}``."""
    if isinstance(result, ParsedAmount):
        return {"ok": True, "value": result.value}
    return {"ok": False, "reason": result.reason}


def scenario_amount_json(result: AmountParse | None) -> dict[str, Any]:
    """A scenario amount parse as ``{present}`` plus the parse when present."""
    if result is None:
        return {"present": False}
    return {"present": True, **amount_json(result)}


def computed_cell_json(cell: float | None) -> dict[str, Any]:
    """A derived scenario cell as ``{present, value}``."""
    return {"present": cell is not None, "value": cell}
