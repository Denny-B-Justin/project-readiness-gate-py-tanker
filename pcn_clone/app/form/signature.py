"""Answer signatures: the fingerprint a verdict is graded against.

A verdict is stale once its field's current signature differs from the one
captured when the evaluation was requested. ``assets/form.js`` computes
signatures in the browser; this module is the same rule in Python, so tests
can pin it:

- a worksheet: ``JSON.stringify({answer, context})``, where the context is
  its row-source list answer as ``[{sectionId, fieldId, answer}]``;
- a list, scenario comparison or static table: ``JSON.stringify(answer)``
  (``null`` when absent);
- any other field: its serialized answer text (a string as typed, a group as
  ``Label: value`` lines).
"""

from __future__ import annotations

from typing import Any

from pcn_clone.content.models import (
    ListInput,
    ScenarioComparisonInput,
    StaticTableInput,
    TemplateField,
    WorksheetInput,
)
from pcn_clone.core.fields import serialize_field_answer
from pcn_clone.core.jsstr import js_json_stringify

ContextEntry = dict[str, Any]
"""One context answer: ``{"sectionId", "fieldId", "answer"}``."""


def worksheet_context(
    field: TemplateField, values: dict[str, Any]
) -> list[ContextEntry]:
    """The context a worksheet is evaluated with: its row-source list answer
    read from ``values``. Empty for any other kind."""
    if not isinstance(field.input, WorksheetInput):
        return []
    source = field.input.row_source
    return [
        {
            "sectionId": source.section_id,
            "fieldId": source.field_id,
            "answer": values.get(source.field_id),
        }
    ]


def field_signature(
    field: TemplateField, answer: Any, context: list[ContextEntry] | None = None
) -> str:
    """The signature of ``answer`` (and, for a worksheet, ``context``)."""
    if isinstance(field.input, WorksheetInput):
        return js_json_stringify({"answer": answer, "context": context or []})
    if isinstance(field.input, ListInput | ScenarioComparisonInput | StaticTableInput):
        return js_json_stringify(answer)
    return serialize_field_answer(field, answer)
