"""Steps shared by the Projects browser tests: seeding the store, opening the
list, and reading the table and storage back."""

from __future__ import annotations

import json
from typing import Any

from tests.browser.harness import Page

META = {
    "templateId": "pcn_global",
    "templateVersion": "1.5.0",
    "criteriaSetId": "pcn_global_default",
    "criteriaVersion": "1.4.0",
}
"""The template identity every project of the one template records."""

UUID_V4 = r"/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/"
"""A JavaScript regex literal matching a lower-case v4 UUID."""

LIST_READY = """(() => {
  const table = document.getElementById("projects-table-wrap");
  const empty = document.getElementById("projects-empty");
  return !!table && !!empty && (!table.hidden || !empty.hidden);
})()"""
"""True once the Projects page has read the index and shown table or empty."""

ROWS = """[...document.querySelectorAll("#projects-rows tr")].map((tr) => ({
  title: tr.querySelector(".cell-title").textContent,
  tags: [...tr.querySelectorAll(".pj-tag")].map((t) => t.textContent),
  date: tr.querySelector(".cell-strong").textContent,
  ago: tr.querySelector(".cell-sub").textContent,
  href: tr.getAttribute("data-href"),
}))"""

INDEX = 'JSON.parse(localStorage.getItem("pcn:projects") || "null")'


def modal_open(element_id: str) -> str:
    """An expression true while a dialog containing ``element_id`` is open."""
    return f'!!document.querySelector(".mantine-Modal-content #{element_id}")'


def open_projects(page: Page) -> None:
    page.goto("/?page=projects", ready=LIST_READY)


def seed(
    page: Page,
    title: str,
    tags: list[str] | None = None,
    days_ago: float = 0,
    draft: dict[str, Any] | None = None,
) -> str:
    """Create a project through ``pcnStore`` (optionally dated ``days_ago``
    and with a draft) and return its id."""
    payload = {**META, "title": title, "tags": tags or []}
    return str(
        page.js(
            f"""(() => {{
              const store = window.pcnStore;
              const project = store.createProject({json.dumps(payload)});
              const days = {json.dumps(days_ago)};
              if (days) {{
                const index = JSON.parse(localStorage.getItem("pcn:projects"));
                const entry = index.find((r) => r.id === project.id);
                const when = new Date(Date.now() - days * 86400000).toISOString();
                entry.createdISO = when;
                entry.editedISO = when;
                localStorage.setItem("pcn:projects", JSON.stringify(index));
              }}
              const draft = {json.dumps(draft)};
              if (draft) store.saveDraft(project.id, draft);
              return project.id;
            }})()"""
        )
    )


def rows(page: Page) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = page.js(ROWS)
    return result


def storage_keys(page: Page) -> list[str]:
    keys: list[str] = page.js("Object.keys(localStorage).sort()")
    return keys
