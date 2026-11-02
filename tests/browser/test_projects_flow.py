"""The Projects workflow in a real browser: the list, the create, defaults and
delete dialogs, the project gate, persistence across reloads, recovery from
corrupt or failing storage, keyboard access and narrow screens."""

from __future__ import annotations

import json
import time

from pcn_clone.app.routing import CONTENT_ID, page_url
from tests.browser.harness import Page, dash_id, url_param
from tests.browser.projects_steps import (
    INDEX,
    LIST_READY,
    META,
    UUID_V4,
    modal_open,
    open_projects,
    rows,
    seed,
    storage_keys,
)

DEFAULT_CARD = dash_id(
    {"type": "projects-default-card", "id": "upper_valley_district_road"}
)
PROJECT_URL = (
    "location.pathname === '/'"
    " && location.search.startsWith('?page=project&project_id=')"
    f" && /^[0-9a-f-]{{36}}$/.test({url_param('project_id')})"
)
ON_PROJECT_PAGE = "!!document.querySelector('.pf-crumb-title')"


def delete_button(project_id: str) -> str:
    return dash_id({"type": "projects-delete", "id": project_id})


def suggestion(tag: str) -> str:
    return dash_id({"type": "projects-tag-suggest", "tag": tag})


def chips(page: Page) -> list[str]:
    result: list[str] = page.js(
        "[...document.querySelectorAll('.tag-entry-chip')].map((c) => c.textContent)"
    )
    return result


def current_project_id(page: Page) -> str:
    return str(page.js(url_param("project_id")))


def clone_default(page: Page) -> str:
    """Clone the default from the Defaults dialog and return the new id."""
    page.click("#projects-defaults-open")
    page.wait_for(modal_open("projects-defaults-list"))
    before = page.js("location.href")
    page.click(DEFAULT_CARD)
    page.wait_for(f"location.href !== {json.dumps(before)} && {PROJECT_URL}")
    page.wait_for(ON_PROJECT_PAGE)
    return current_project_id(page)


# --- List --------------------------------------------------------------------


def test_empty_state(page: Page) -> None:
    open_projects(page)

    assert page.js("document.getElementById('projects-empty').hidden") is False
    assert page.js("document.getElementById('projects-table-wrap').hidden") is True
    assert page.js("document.getElementById('projects-count').textContent") == "0"
    assert page.js("document.title") == "Projects — PIM-PAM"


def test_reload_keeps_projects_newest_first(page: Page) -> None:
    seed(page, "Older", ["Rural"], days_ago=42)
    seed(page, "Newer")
    open_projects(page)
    before = rows(page)

    page.reload(ready=LIST_READY)

    after = rows(page)
    assert [r["title"] for r in after] == ["Newer", "Older"]
    assert after == before
    assert after[1]["tags"] == ["Rural"]
    assert after[1]["ago"] == "42 days ago"
    assert page.js("document.getElementById('projects-count').textContent") == "2"


def test_loading_the_list_costs_one_table_render(page: Page) -> None:
    seed(page, "One", ["Health"])
    seed(page, "Two")
    page.send("Network.enable")
    since = len(page.events)

    open_projects(page)
    page.pump(0.5)

    outputs = page.callback_outputs(since)
    table_renders = [o for o in outputs if "projects-rows.children" in o]
    assert len(table_renders) == 1
    others = [o for o in outputs if o not in table_renders]
    assert all(f"{CONTENT_ID}.children" in o for o in others), others


# --- Create ------------------------------------------------------------------


def test_create_with_two_tags(page: Page) -> None:
    open_projects(page)
    page.click("#projects-new-open")
    page.wait_for(modal_open("projects-new-title"))
    assert page.js("document.getElementById('projects-new-create').disabled") is True

    page.type("#projects-new-title", "Rural Health Clinic Expansion")
    page.wait_for("!document.getElementById('projects-new-create').disabled")

    page.type("#projects-new-tag-input", "Health")
    page.press("Enter")
    page.wait_for("document.querySelectorAll('.tag-entry-chip').length === 1")
    page.click(suggestion("Transport"))
    page.wait_for("document.querySelectorAll('.tag-entry-chip').length === 2")
    page.type("#projects-new-tag-input", "Temp,")
    page.wait_for("document.querySelectorAll('.tag-entry-chip').length === 3")
    page.type("#projects-new-tag-input", "health")
    page.press("Enter")
    page.wait_for("document.getElementById('projects-new-tag-input').value === ''")
    assert chips(page) == ["Health", "Transport", "Temp"]
    page.press("Backspace")
    page.wait_for("document.querySelectorAll('.tag-entry-chip').length === 2")
    assert chips(page) == ["Health", "Transport"]
    hidden = page.js(
        f"""[{json.dumps(suggestion("Health"))}, {json.dumps(suggestion("Transport"))},
             {json.dumps(suggestion("Energy"))}]
            .map((s) => document.querySelector(s).hidden)"""
    )
    assert hidden == [True, True, False]

    page.send("Network.enable")
    since = len(page.events)
    page.click("#projects-new-create")
    page.wait_for(PROJECT_URL)
    page.wait_for(ON_PROJECT_PAGE)
    page.pump(0.3)
    assert not [o for o in page.callback_outputs(since) if "projects-new-tag" in o]

    stored = page.js(INDEX)
    assert len(stored) == 1
    assert stored[0]["title"] == "Rural Health Clinic Expansion"
    assert stored[0]["tags"] == ["Health", "Transport"]
    assert stored[0]["id"] == current_project_id(page)


def test_record_field_order_and_no_tags_key_when_untagged(page: Page) -> None:
    open_projects(page)
    page.click("#projects-new-open")
    page.wait_for(modal_open("projects-new-title"))
    page.type("#projects-new-title", "Untagged note")
    page.wait_for("!document.getElementById('projects-new-create').disabled")
    page.click("#projects-new-create")
    page.wait_for(ON_PROJECT_PAGE)

    (stored,) = page.js(INDEX)
    assert list(stored) == [
        "schemaVersion",
        "id",
        "title",
        "templateId",
        "templateVersion",
        "criteriaSetId",
        "criteriaVersion",
        "createdISO",
        "editedISO",
    ]
    assert stored["schemaVersion"] == 1
    assert {k: stored[k] for k in META} == META
    assert stored["createdISO"] == stored["editedISO"]
    assert page.js(f"{UUID_V4}.test({json.dumps(stored['id'])})") is True
    assert (
        page.js(f"new Date({json.dumps(stored['editedISO'])}).toISOString()")
        == stored["editedISO"]
    )


def test_cancel_closes_and_resets_the_create_dialog(page: Page) -> None:
    open_projects(page)
    page.click("#projects-new-open")
    page.wait_for(modal_open("projects-new-title"))
    page.type("#projects-new-title", "Draft title")
    page.click(suggestion("Energy"))
    page.wait_for("document.querySelectorAll('.tag-entry-chip').length === 1")

    page.click("#projects-new-cancel")
    page.wait_for(f"!{modal_open('projects-new-title')}")
    page.click("#projects-new-open")
    page.wait_for(modal_open("projects-new-title"))

    assert page.js("document.getElementById('projects-new-title').value") == ""
    assert chips(page) == []
    assert page.js(INDEX) is None


def test_new_query_opens_dialog_focuses_title_and_strips_only_new(page: Page) -> None:
    page.goto("/?view=compact&page=projects&new=1#notes", ready=LIST_READY)

    page.wait_for(modal_open("projects-new-title"))
    page.wait_for("document.activeElement.id === 'projects-new-title'")
    time.sleep(0.4)
    assert page.js("document.activeElement.id") == "projects-new-title"
    assert page.js("location.search") == "?view=compact&page=projects"
    assert page.js("location.hash") == "#notes"


# --- Project page and gate ---------------------------------------------------


def test_row_opens_the_project_behind_the_gate(page: Page) -> None:
    project_id = seed(page, "Bridge Repair", ["Transport"])
    open_projects(page)
    link = page.js(
        "(() => { const a = document.querySelector('#projects-rows a.cell-title');"
        " return [a.getAttribute('href'),"
        " a.closest('tr').getAttribute('data-href')]; })()"
    )
    href = page_url("project", project_id=project_id)
    assert link == [href, href]

    page.click("#projects-rows tr:first-child .cell-strong")
    page.wait_for(f"location.search === {json.dumps(href)}")
    page.wait_for(ON_PROJECT_PAGE)

    crumb = page.js(
        "(() => { const nav = document.querySelector('nav.pf-bar-start');"
        " return [nav.getAttribute('aria-label'),"
        " nav.querySelector('a').getAttribute('href'),"
        " nav.querySelector('[aria-current=page]').textContent]; })()"
    )
    assert crumb == ["Breadcrumb", "?page=projects", "Bridge Repair"]

    page.click(".pf-crumb-link")
    page.wait_for("location.search === '?page=projects'")
    page.wait_for(LIST_READY)


def test_row_click_that_ends_a_text_selection_does_not_navigate(page: Page) -> None:
    seed(page, "Selectable")
    open_projects(page)

    page.js(
        """(() => {
          const cell = document.querySelector(
            "#projects-rows tr:first-child .cell-strong");
          window.getSelection().selectAllChildren(cell);
          cell.dispatchEvent(new MouseEvent("click", {bubbles: true, button: 0}));
          return true;
        })()"""
    )
    time.sleep(0.4)
    assert page.js("location.search") == "?page=projects"


def test_gate_template_mismatch_and_unknown_id_show_not_found(page: Page) -> None:
    good = seed(page, "Right template")
    page.js(
        """(() => {
          const index = JSON.parse(localStorage.getItem("pcn:projects"));
          index.push(Object.assign({}, index[0], {id: "other-template-id",
            title: "Wrong template", templateId: "pcn_other"}));
          localStorage.setItem("pcn:projects", JSON.stringify(index));
          return true;
        })()"""
    )

    for project_id in ("other-template-id", "no-such-project"):
        page.goto("/" + page_url("project", project_id=project_id))
        page.wait_for("!!document.querySelector('.pj-gate-missing')")
        assert page.js("!!document.querySelector('.pf-bar')") is False
        assert (
            page.js("document.querySelector('.pj-gate-link').getAttribute('href')")
            == "?page=projects"
        )

    page.goto("/" + page_url("project", project_id=good))
    page.wait_for(ON_PROJECT_PAGE)


# --- Defaults ----------------------------------------------------------------


def test_clone_default_writes_record_and_full_draft(page: Page) -> None:
    open_projects(page)

    first = clone_default(page)
    draft = page.js(f"JSON.parse(localStorage.getItem('pcn:project:{first}:answers'))")
    assert draft["schemaVersion"] == 1
    assert len(draft["values"]) == 19
    assert [r["_rowId"] for r in draft["values"]["scope_of_the_project"]] == [
        "comp-design",
        "comp-works",
        "comp-equipment",
    ]
    assert page.js(f"Object.keys(window.pcnStore.loadDraft('{first}')).length") == 19

    page.click(".pf-crumb-link")
    page.wait_for(LIST_READY)
    second = clone_default(page)

    assert second != first
    assert storage_keys(page) == sorted(
        [
            "pcn:projects",
            f"pcn:project:{first}:answers",
            f"pcn:project:{second}:answers",
        ]
    )
    titles_and_tags = [(r["title"], r["tags"]) for r in page.js(INDEX)]
    assert (
        titles_and_tags
        == [("Upper Valley District Road Rehabilitation", ["Transport"])] * 2
    )


def test_defaults_dialog_is_locked_while_the_default_loads(page: Page) -> None:
    open_projects(page)
    page.click("#projects-defaults-open")
    page.wait_for(modal_open("projects-defaults-list"))
    page.send(
        "Fetch.enable", {"patterns": [{"urlPattern": "*_dash-update-component*"}]}
    )
    since = len(page.events)

    page.click(DEFAULT_CARD)
    paused = page.wait_event(
        "Fetch.requestPaused",
        lambda p: "projects-default-payload" in p["request"].get("postData", ""),
        since=since,
    )

    locked = page.js(
        """(() => {
          const list = document.getElementById("projects-defaults-list");
          return {
            fieldset: list.disabled,
            busy: list.getAttribute("aria-busy"),
            cancel: document.getElementById("projects-defaults-cancel").disabled,
            close: document.querySelector(
              ".pj-dialog-defaults .mantine-Modal-close").disabled,
          };
        })()"""
    )
    assert locked == {"fieldset": True, "busy": "true", "cancel": True, "close": True}
    page.press("Escape")
    page.click(DEFAULT_CARD)
    page.pump(0.5)
    assert page.js(modal_open("projects-defaults-list")) is True
    loads = [
        e
        for e in page.events[since:]
        if e["method"] == "Fetch.requestPaused"
        and "projects-default-payload" in e["params"]["request"].get("postData", "")
    ]
    assert len(loads) == 1

    page.send("Fetch.continueRequest", {"requestId": paused["requestId"]})
    page.send("Fetch.disable")
    page.wait_for(ON_PROJECT_PAGE)
    assert len(page.js(INDEX)) == 1


def test_clone_rolls_back_when_the_draft_write_hits_the_quota(page: Page) -> None:
    seed(page, "Existing")
    open_projects(page)
    page.js(
        """(() => {
          const realSetItem = Storage.prototype.setItem;
          Storage.prototype.setItem = function (key, value) {
            if (key.endsWith(":answers")) {
              throw new DOMException("full", "QuotaExceededError");
            }
            return realSetItem.call(this, key, value);
          };
          window.storeErrors = [];
          window.addEventListener(
            "pcn:store-error", (e) => window.storeErrors.push(e.detail));
          return true;
        })()"""
    )
    page.click("#projects-defaults-open")
    page.wait_for(modal_open("projects-defaults-list"))
    page.click(DEFAULT_CARD)

    toast = page.wait_for(
        "[...document.querySelectorAll('.mantine-Notification-root.toast-error')]"
        ".map((n) => n.textContent).join(' ')"
    )
    assert "Couldn’t create a project from this default" in toast  # noqa: RUF001
    assert "Browser storage is full" in toast
    assert [r["title"] for r in page.js(INDEX)] == ["Existing"]
    assert [k for k in storage_keys(page) if k.endswith(":answers")] == []
    assert page.js("location.search") == "?page=projects"
    assert page.js("window.storeErrors.map((e) => e.kind)") == ["quota"]


# --- Delete ------------------------------------------------------------------


def test_delete_with_confirmation(page: Page) -> None:
    keep = seed(page, "Keep me", draft={"project_title": "Keep"})
    drop = seed(page, "Drop me", draft={"project_title": "Drop"})
    open_projects(page)

    page.click(delete_button(drop))
    page.wait_for(modal_open("projects-delete-confirm"))
    heading = page.js(
        "document.querySelector('.pj-dialog-delete .mantine-Modal-title').textContent"
    )
    assert heading == "Delete “Drop me”?"
    assert page.js("location.search") == "?page=projects"
    page.click("#projects-delete-cancel")
    page.wait_for(f"!{modal_open('projects-delete-confirm')}")
    assert len(page.js(INDEX)) == 2

    page.click(delete_button(drop))
    page.wait_for(modal_open("projects-delete-confirm"))
    page.click("#projects-delete-confirm")
    page.wait_for("document.querySelectorAll('#projects-rows tr').length === 1")

    assert [r["id"] for r in page.js(INDEX)] == [keep]
    assert storage_keys(page) == ["pcn:project:" + keep + ":answers", "pcn:projects"]
    page.wait_for(
        "[...document.querySelectorAll('.mantine-Notification-root.toast-success')]"
        ".some((n) => n.textContent.includes('“Drop me” deleted'))"
    )
    page.wait_for(
        "document.activeElement && document.activeElement.id === 'projects-new-open'"
    )


# --- Corrupt storage ---------------------------------------------------------


def test_corrupt_entries_are_quarantined_then_dropped_on_next_write(page: Page) -> None:
    seed(page, "Healthy")
    broken = seed(page, "Broken")
    page.js(
        f"""(() => {{
          const index = JSON.parse(localStorage.getItem("pcn:projects"));
          index.find((r) => r.id === "{broken}").title = "";
          index.push("not a record", {{schemaVersion: 2, id: "x"}});
          localStorage.setItem("pcn:projects", JSON.stringify(index));
          return true;
        }})()"""
    )

    open_projects(page)
    assert [r["title"] for r in rows(page)] == ["Healthy"]
    assert page.js("document.getElementById('projects-count').textContent") == "1"
    assert len(page.js(INDEX)) == 4

    seed(page, "Fresh")
    stored = page.js(INDEX)
    assert [r["title"] for r in stored] == ["Healthy", "Fresh"]


# --- Keyboard, labels, narrow screens ----------------------------------------


def test_sortable_headers_are_keyboard_operable_with_aria_sort(page: Page) -> None:
    seed(page, "alpha", days_ago=3)
    seed(page, "Bravo", days_ago=1)
    open_projects(page)
    page.send("Network.enable")
    aria = (
        "['name', 'updated'].map((c) =>"
        " document.getElementById(`projects-sort-${c}-th`).getAttribute('aria-sort'))"
    )
    assert page.js(aria) == ["none", "descending"]

    page.js("document.getElementById('projects-new-open').focus(); true")
    page.press("Tab")
    assert page.js("document.activeElement.id") == "projects-sort-name"
    assert page.js("getComputedStyle(document.activeElement).boxShadow") != "none"

    since = len(page.events)
    page.press("Enter")
    page.wait_for(f'JSON.stringify({aria}) === \'["ascending","none"]\'')
    assert [r["title"] for r in rows(page)] == ["alpha", "Bravo"]
    page.pump(0.3)
    outputs = page.callback_outputs(since)
    assert len(outputs) == 1
    assert "projects-rows.children" in outputs[0]

    page.press(" ")
    page.wait_for(f'JSON.stringify({aria}) === \'["descending","none"]\'')
    assert [r["title"] for r in rows(page)] == ["Bravo", "alpha"]


def test_dialog_close_buttons_are_labelled(page: Page) -> None:
    open_projects(page)
    for trigger, inside in (
        ("#projects-new-open", "projects-new-title"),
        ("#projects-defaults-open", "projects-defaults-list"),
    ):
        page.click(trigger)
        page.wait_for(modal_open(inside))
        label = page.js(
            "document.querySelector('.mantine-Modal-content .mantine-Modal-close')"
            ".getAttribute('aria-label')"
        )
        assert label == "Close"
        page.press("Escape")
        page.wait_for(f"!{modal_open(inside)}")


def test_no_horizontal_scroll_at_390px(page: Page) -> None:
    project_id = seed(
        page,
        "Upper Valley District Road Rehabilitation and Drainage Works",
        ["Transport", "Climate Adaptation", "Rural"],
    )
    page.set_viewport(390, 844)
    no_overflow = "document.documentElement.scrollWidth <= window.innerWidth"

    open_projects(page)
    assert page.js(no_overflow) is True

    page.goto("/" + page_url("project", project_id=project_id))
    page.wait_for(ON_PROJECT_PAGE)
    assert page.js(no_overflow) is True
