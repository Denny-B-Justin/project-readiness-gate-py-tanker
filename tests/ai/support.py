"""Shared inputs for the AI-layer tests: the default project's answers and
its serialized submission, plus a client that records requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from typing import Any

from pcn_clone.ai.provider import ModelReply
from pcn_clone.content import load_default_project, load_template
from pcn_clone.core.serialize import (
    SerializedField,
    canonicalize_submission,
    serialize_submission,
)


@cache
def default_answers() -> tuple[dict[str, Any], ...]:
    """The default project's canonical answers as JSON-shaped entries."""
    template = load_template()
    canonical = canonicalize_submission(template, load_default_project().submission)
    return tuple(canonical["answers"])


def default_answer(field_id: str) -> Any:
    """The default project's answer to one field."""
    return next(a["answer"] for a in default_answers() if a["fieldId"] == field_id)


def section_of(field_id: str) -> str:
    """The section id of a template field."""
    return next(
        section.id
        for section, field in load_template().iter_fields()
        if field.id == field_id
    )


@cache
def default_fields() -> tuple[SerializedField, ...]:
    """The default project's serialized submission."""
    template = load_template()
    canonical = canonicalize_submission(template, load_default_project().submission)
    return tuple(serialize_submission(template, canonical))


@dataclass
class RecordingClient:
    """A model client that records each request and replies with ``data``."""

    data: dict[str, Any]
    model: str = "test/model"
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def complete(
        self, *, system: str, user: str, schema: dict[str, Any], format_name: str
    ) -> ModelReply:
        self.calls.append(
            {
                "system": system,
                "user": user,
                "schema": schema,
                "format_name": format_name,
            }
        )
        return ModelReply(data=self.data, model=self.model)
