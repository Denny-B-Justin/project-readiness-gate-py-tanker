"""Template lookups the workspace needs by field id alone (field ids are
unique across the template)."""

from __future__ import annotations

from pcn_clone.content import load_template
from pcn_clone.content.models import Section, TemplateField


def find_field(field_id: str) -> tuple[Section, TemplateField] | None:
    """The section and field with this id, or ``None``."""
    for section, field in load_template().iter_fields():
        if field.id == field_id:
            return section, field
    return None
