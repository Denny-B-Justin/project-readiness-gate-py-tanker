"""``window.pcnStore`` in a real browser: drafts, updates, blocked storage and
the id fallback for non-secure contexts."""

from __future__ import annotations

import json

from tests.browser.harness import Page
from tests.browser.projects_steps import INDEX, META, UUID_V4, seed


def test_drafts_round_trip_and_reject_foreign_shapes(page: Page) -> None:
    project_id = seed(page, "Drafted")
    key = f"pcn:project:{project_id}:answers"

    page.js(f"window.pcnStore.saveDraft('{project_id}', {{project_title: 'X'}}); true")
    assert page.js(f"JSON.parse(localStorage.getItem('{key}'))") == {
        "schemaVersion": 1,
        "values": {"project_title": "X"},
    }
    assert page.js(f"window.pcnStore.loadDraft('{project_id}')") == {
        "project_title": "X"
    }

    for stored in (
        '{"schemaVersion": 2, "values": {}}',
        '{"schemaVersion": 1, "values": []}',
        "nope",
    ):
        page.js(f"localStorage.setItem('{key}', {json.dumps(stored)}); true")
        assert page.js(f"window.pcnStore.loadDraft('{project_id}')") is None

    page.js(f"window.pcnStore.clearDraft('{project_id}'); true")
    assert page.js(f"localStorage.getItem('{key}')") is None


def test_update_patches_title_and_tags_and_restamps_edited(page: Page) -> None:
    project_id = seed(page, "Before", days_ago=5)
    (before,) = page.js(INDEX)

    patch = json.dumps({"title": "After", "tags": ["Urban"]})
    updated = page.js(f"window.pcnStore.updateProject('{project_id}', {patch})")

    assert updated["title"] == "After"
    assert updated["tags"] == ["Urban"]
    assert updated["createdISO"] == before["createdISO"]
    assert updated["editedISO"] > before["editedISO"]
    error = page.js(
        "(() => { try { window.pcnStore.updateProject('missing'); }"
        " catch (e) { return e.message; } })()"
    )
    assert error == 'Cannot update unknown project "missing".'


def test_blocked_storage_reads_empty_and_writes_throw_unavailable(page: Page) -> None:
    seed(page, "Hidden by the block")

    new_project = json.dumps({**META, "title": "T"})
    result = page.js(
        f"""(() => {{
          Object.defineProperty(window, "localStorage", {{
            configurable: true,
            get() {{ throw new DOMException("blocked", "SecurityError"); }},
          }});
          const store = window.pcnStore;
          const failure = (write) => {{
            try {{ write(); return null; }}
            catch (e) {{ return [e.name, e.kind, e instanceof store.StoreError]; }}
          }};
          return {{
            list: store.listProjects(),
            get: store.getProject("x"),
            draft: store.loadDraft("x"),
            create: failure(() => store.createProject({new_project})),
            save: failure(() => store.saveDraft("x", {{}})),
          }};
        }})()"""
    )

    assert result == {
        "list": [],
        "get": None,
        "draft": None,
        "create": ["StoreError", "unavailable", True],
        "save": ["StoreError", "unavailable", True],
    }


def test_ids_fall_back_to_v4_uuids_without_random_uuid(page: Page) -> None:
    ids = page.js(
        """(() => {
          delete Crypto.prototype.randomUUID;
          return typeof crypto.randomUUID === "undefined"
            ? Array.from({length: 50}, () => window.pcnStore.newId())
            : null;
        })()"""
    )

    assert ids is not None
    assert len(set(ids)) == 50
    assert page.js(f"{json.dumps(ids)}.every((id) => {UUID_V4}.test(id))") is True
    project_id = seed(page, "Made without randomUUID")
    assert page.js(f"{UUID_V4}.test({json.dumps(project_id)})") is True


def test_invalid_input_is_refused_before_anything_is_written(page: Page) -> None:
    errors = page.js(
        f"""(() => {{
          const store = window.pcnStore;
          const attempt = (input) => {{
            try {{ store.createProject(input); return null; }}
            catch (e) {{ return e.name; }}
          }};
          return [
            attempt({json.dumps({**META, "title": ""})}),
            attempt({json.dumps({**META, "title": "T", "tags": "Health"})}),
            attempt({{title: "No template"}}),
          ];
        }})()"""
    )

    assert errors == ["TypeError", "TypeError", "TypeError"]
    assert page.js(INDEX) is None
