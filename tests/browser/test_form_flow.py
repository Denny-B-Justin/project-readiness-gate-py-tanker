"""The proposer workspace in a real browser, against the fake AI provider:
hydration, autosave and its guards, list and worksheet rows, the live
figures (checked against ``pcn_clone.core``), readiness (including clicks
that race an edit), evaluation with its states and staleness, the dialogs,
the jump menu and scroll chrome, recovery of lost inputs, markup drawn in
the browser against the Python components it mirrors, and narrow screens.

The app here runs with ``PCN_AI_PROVIDER=fake``, one second of fake latency,
and an injected failure for ``project_title``.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from pcn_clone.ai import readiness
from pcn_clone.app.form.context_bar import jump_item_props, jump_label
from pcn_clone.app.form.dialogs import dialog_heading
from pcn_clone.app.form.field_card import evaluate_button as evaluate_button_component
from pcn_clone.app.form.messages import EVALUATE_LABEL, field_action
from pcn_clone.app.form.section import idle_tally
from pcn_clone.app.form.signature import field_signature, worksheet_context
from pcn_clone.app.form.template import find_field
from pcn_clone.app.form.verdicts import VERDICTS, VerdictName, verdict_pill
from pcn_clone.app.projects_data import default_project_values
from pcn_clone.content import load_criteria, load_template
from pcn_clone.content.models import (
    ScenarioComparisonInput,
    TemplateField,
    WorksheetInput,
)
from pcn_clone.core.fields import coerce_string_record_array
from pcn_clone.core.numbers import (
    ParsedAmount,
    format_amount,
    parse_amount,
    to_amount,
)
from pcn_clone.core.scenario import compute_computed_cell
from pcn_clone.core.worksheet import (
    coerce_worksheet_answer,
    compute_category_summary,
    compute_row_total,
    derive_worksheet_rows,
    get_row_values,
)
from tests.browser.form_steps import (
    ALL_READY,
    READY,
    bound,
    control,
    count,
    dash_requests,
    dom_shape,
    evaluate_button,
    exists,
    footer,
    has_text,
    open_default,
    open_form,
    request_window,
    rows,
    saves,
    seed_default,
    set_value,
    shape,
    snapshot,
    spy_on_saves,
    status,
    tally,
    text,
    texts,
    type_at_end,
)
from tests.browser.harness import AppServer, Chrome, Page, dash_id

FAKE_DELAY = 1.0
FAILING_FIELD = "project_title"
WORKSHEET = "investment_cost_estimate"
SCOPE = "scope_of_the_project"
RISKS = "project_risks"
PERMITS = "documentation_and_permits"
FIRST_SECTION = "investment_identification"
FAILED = "Evaluation failed — The evaluation could not be completed. Please try again."
EVALUATIONS = "pf-evaluation"
"""What every evaluate request's output names."""
AUTOSAVE_DELAY = 0.5


@pytest.fixture(scope="module")
def form_server(
    chrome_binary: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[AppServer]:
    """The app with the fake AI provider's latency and injected failure."""
    server = AppServer(
        tmp_path_factory.mktemp("form-server") / "uvicorn.log",
        env={
            "PCN_AI_FAKE_DELAY_SECONDS": str(FAKE_DELAY),
            "PCN_AI_FAKE_FAIL": FAILING_FIELD,
        },
    )
    server.start()
    yield server
    server.stop()


@pytest.fixture
def page(chrome: Chrome, form_server: AppServer) -> Iterator[Page]:
    """A new tab on the fake-provider app with empty storage. The test fails
    if the page threw or logged a console error."""
    tab = chrome.new_page(form_server.url)
    tab.goto("/?page=projects", ready="!!window.pcnStore")
    tab.js("localStorage.clear(); sessionStorage.clear(); true")
    yield tab
    errors = tab.errors()
    tab.close()
    assert errors == [], errors


def field(field_id: str) -> TemplateField:
    found = find_field(field_id)
    assert found is not None
    return found[1]


def notes_button(field_id: str) -> str:
    return f"{status(field_id)} [data-pf-notes]"


def graded(field_id: str) -> str:
    """An expression true once the field shows a verdict."""
    return exists(notes_button(field_id))


def evaluating(field_id: str) -> str:
    return has_text(status(field_id), "Evaluating…")


def state(page: Page, field_id: str) -> dict[str, Any]:
    result: dict[str, Any] = page.js(f"window.pcnForm.state({json.dumps(field_id)})")
    return result


def verdict_of(page: Page, field_id: str) -> VerdictName:
    verdict: VerdictName = state(page, field_id)["result"]["verdict"]
    return verdict


def label(verdict: VerdictName) -> str:
    return VERDICTS[verdict]["label"]


def evaluate_and_wait(page: Page, field_id: str) -> VerdictName:
    page.click(evaluate_button(field_id))
    page.wait_for(graded(field_id), timeout=5)
    return verdict_of(page, field_id)


def aria_label(page: Page, selector: str) -> str:
    result: str = page.js(
        f"document.querySelector({json.dumps(selector)}).getAttribute('aria-label')"
    )
    return result


def edit_then_click(page: Page, field_id: str, edit: str) -> bool:
    """Run the ``edit`` script and click the field's Evaluate button in the
    same task, then again 50 ms later; return whether the button still
    looked enabled at the first click (its disabled state trails the edit
    by a render)."""
    button = json.dumps(evaluate_button(field_id))
    enabled: bool = page.js(
        f"""(async () => {{
          const button = document.querySelector({button});
          {edit}
          const enabled = !button.disabled;
          button.click();
          await new Promise((resolve) => setTimeout(resolve, 50));
          button.click();
          return enabled;
        }})()"""
    )
    return enabled


def edit_script(selector: str, value: str, event: str = "input") -> str:
    """A script that sets a control's value as an edit would."""
    return (
        f"const control = document.querySelector({json.dumps(selector)});"
        f" control.value = {json.dumps(value)};"
        f" control.dispatchEvent(new Event({json.dumps(event)}, {{bubbles: true}}));"
    )


# --- Hydration and autosave --------------------------------------------------


def test_cloned_default_hydrates_every_field(page: Page) -> None:
    page.goto("/?page=projects", ready=exists("#projects-defaults-open"))
    page.click("#projects-defaults-open")
    page.wait_for(exists(".mantine-Modal-content .pj-default-card"))
    page.click(
        dash_id({"type": "projects-default-card", "id": "upper_valley_district_road"})
    )
    page.wait_for(READY, timeout=20)
    page.wait_for(ALL_READY)

    expected = default_project_values()
    assert snapshot(page) == expected
    assert count(page, "#pf-root [data-pf-card]") == 19
    assert control(page, "project_title", []) == expected["project_title"]
    period = "implementation_period"
    assert control(page, period, ["project_start_date"], "type") == "month"
    assert control(page, period, ["estimated_project_completion_date"]) == "2028-03"
    assert page.js(
        f"[...document.querySelectorAll({json.dumps(rows(SCOPE))})]"
        ".map((tr) => tr.dataset.pfRowId)"
    ) == ["comp-design", "comp-works", "comp-equipment"]
    assert count(page, rows(RISKS)) == 4
    assert count(page, rows(WORKSHEET, "worksheet")) == 3
    assert control(page, "revenues", ["rows", "with_project", "year_2"]) == "48000"
    assert control(page, PERMITS, ["rows", "building_permit", "status"]) == (
        "not_started"
    )
    assert text(page, "#pf-autosave") == "Changes save automatically"

    # The browser's signatures follow pcn_clone.app.form.signature's rule.
    for _, template_field in load_template().iter_fields():
        answer = expected[template_field.id]
        context = worksheet_context(template_field, expected) or None
        assert page.js(
            f"window.pcnForm.signature({json.dumps(template_field.id)})"
        ) == field_signature(template_field, answer, context), template_field.id


def test_edits_autosave_and_survive_a_reload(page: Page) -> None:
    project_id = open_default(page)
    project = f"window.pcnStore.getProject({json.dumps(project_id)})"
    edited_before = page.js(f"{project}.editedISO")

    type_at_end(page, bound("objectives", []), " Persisted.")
    page.wait_for(
        "document.getElementById('pf-autosave').textContent.startsWith('Last saved at')"
    )

    saved = page.js(f"window.pcnStore.loadDraft({json.dumps(project_id)}).objectives")
    assert saved.endswith(" Persisted.")
    assert page.js(f"{project}.editedISO") != edited_before

    page.reload(ready=READY)
    assert control(page, "objectives", []) == saved
    assert snapshot(page)["objectives"] == saved
    assert text(page, "#pf-autosave") == "Changes save automatically"


def test_a_failed_save_shows_the_warning_until_a_save_succeeds(page: Page) -> None:
    project_id = open_default(page)
    autosave = "#pf-autosave"
    page.js(
        """(() => {
          window.realSetItem = Storage.prototype.setItem;
          Storage.prototype.setItem = function () {
            throw new DOMException("full", "QuotaExceededError");
          };
          return true;
        })()"""
    )

    type_at_end(page, bound("objectives", []), " Lost?")
    page.wait_for(
        has_text(
            autosave,
            "Your draft couldn’t be saved — check your browser’s storage settings.",  # noqa: RUF001
        )
    )
    assert page.js("document.getElementById('pf-autosave').className") == (
        "pf-autosave is-failed"
    )

    page.js("Storage.prototype.setItem = window.realSetItem; true")
    type_at_end(page, bound("objectives", []), " Kept.")
    page.wait_for(
        "document.getElementById('pf-autosave').textContent.startsWith('Last saved at')"
    )
    saved = page.js(f"window.pcnStore.loadDraft({json.dumps(project_id)}).objectives")
    assert saved.endswith(" Lost? Kept.")


def test_nothing_is_saved_before_the_workspace_is_ready(page: Page) -> None:
    project_id = seed_default(page)
    spy_on_saves(page)
    page.send("Network.enable")
    since = len(page.events)

    open_form(page, project_id)
    page.pump(2 * AUTOSAVE_DELAY)

    assert saves(page) == []
    # Mount asks for the server-decided readiness of every field at once.
    assert len(dash_requests(page, "pf-readiness", since)) == 1

    type_at_end(page, bound("objectives", []), " Saved.")
    page.wait_for(
        "document.getElementById('pf-autosave').textContent.startsWith('Last saved at')"
    )
    recorded = saves(page)
    assert recorded
    assert all(save["ready"] for save in recorded)
    assert recorded[-1]["values"]["objectives"].endswith(" Saved.")


def test_a_pending_save_is_written_when_the_page_is_hidden(page: Page) -> None:
    project_id = seed_default(page)
    spy_on_saves(page)
    open_form(page, project_id)
    objectives = json.dumps(bound("objectives", []))

    result = page.js(
        f"""(() => {{
          const input = document.querySelector({objectives});
          input.value += " Hidden.";
          input.dispatchEvent(new Event("input", {{bubbles: true}}));
          const edited = performance.now();
          Object.defineProperty(document, "visibilityState", {{
            configurable: true, get: () => "hidden" }});
          document.dispatchEvent(new Event("visibilitychange"));
          delete document.visibilityState;
          return {{ edited, saved: window.pcnSaves.map((save) => save.at) }};
        }})()"""
    )

    (saved_at,) = result["saved"]
    assert saved_at - result["edited"] < AUTOSAVE_DELAY * 1000
    draft = f"window.pcnStore.loadDraft({json.dumps(project_id)}).objectives"
    assert page.js(draft).endswith(" Hidden.")


def test_a_pending_save_is_written_on_in_app_navigation(page: Page) -> None:
    project_id = seed_default(page)
    spy_on_saves(page)
    open_form(page, project_id)
    objectives = json.dumps(bound("objectives", []))

    result = page.js(
        f"""(() => {{
          const input = document.querySelector({objectives});
          input.value += " Left.";
          input.dispatchEvent(new Event("input", {{bubbles: true}}));
          const edited = performance.now();
          document.querySelector(".pf-crumb-link").click();
          return {{ edited, saved: window.pcnSaves.map((save) => save.at) }};
        }})()"""
    )

    (saved_at,) = result["saved"]
    assert saved_at - result["edited"] < AUTOSAVE_DELAY * 1000
    page.wait_for("location.search === '?page=projects'")
    page.wait_for("!window.pcnForm.hydrated()")
    draft = f"window.pcnStore.loadDraft({json.dumps(project_id)}).objectives"
    assert page.js(draft).endswith(" Left.")
    page.pump(2 * AUTOSAVE_DELAY)
    assert len(saves(page)) == 1


def test_feedback_is_kept_in_memory_only(page: Page) -> None:
    project_id = open_default(page)
    page.click(evaluate_button("objectives"))
    page.wait_for(graded("objectives"), timeout=5)

    draft = page.js(f"localStorage.getItem('pcn:project:{project_id}:answers')")
    assert "reasoning" not in draft

    page.reload(ready=READY)
    assert page.js("window.pcnForm.state('objectives')") == {"status": "idle"}
    assert text(page, tally("investment_rationale")) == "2 not evaluated"


# --- Lists and the worksheet -------------------------------------------------


def test_components_drive_the_worksheet_rows(page: Page) -> None:
    open_default(page)
    worksheet_rows = rows(WORKSHEET, "worksheet")

    page.click(f"[data-pf-add={SCOPE}]")
    page.wait_for(
        f"document.querySelectorAll({json.dumps(worksheet_rows)}).length === 4"
    )
    new_id = snapshot(page)[SCOPE][-1]["_rowId"]
    new_row = f"{worksheet_rows}[data-pf-row-id='{new_id}']"
    assert page.js("document.activeElement.getAttribute('aria-label')") == (
        "Component for Item 4"
    )
    assert text(page, f"{new_row} .pf-ws-row-label") == "(unnamed item)"
    assert page.js(
        f"document.querySelector({json.dumps(new_row)}).dataset.pfStart"
    ) == ("missing")
    first_cost = json.dumps(f"{new_row} input")
    assert page.js(f"document.querySelector({first_cost}).disabled") is True

    page.send("Input.insertText", {"text": "Bridge deck"})
    start = f"[data-pf-row-id='{new_id}'] [data-pf-control=expected_start_date]"
    set_value(page, start, "2027-05")
    page.wait_for(
        f"document.querySelector({json.dumps(new_row)}).dataset.pfStart === 'set'"
    )
    assert text(page, f"{new_row} .pf-ws-row-label") == "Bridge deck"
    assert text(page, f"{new_row} .pf-ws-row-years") == "years 2027–2031"
    assert page.js(f"document.querySelector({first_cost}).disabled") is False
    assert page.js(
        f"document.querySelector({first_cost}).getAttribute('aria-label')"
    ) == ("Year 1 for Bridge deck")
    assert snapshot(page)[SCOPE][-1] == {
        "_rowId": new_id,
        "component": "Bridge deck",
        "expected_start_date": "2027-05",
        "expected_end_date": "",
    }

    page.click(f"[data-pf-list={SCOPE}] [data-pf-remove='{new_id}']")
    page.wait_for(
        f"document.querySelectorAll({json.dumps(worksheet_rows)}).length === 3"
    )
    assert [item["_rowId"] for item in snapshot(page)[SCOPE]] == [
        "comp-design",
        "comp-works",
        "comp-equipment",
    ]


def test_without_components_the_worksheet_shows_its_hint(page: Page) -> None:
    open_default(page)
    for _ in range(3):
        page.click(f"{rows(SCOPE)}:first-child [data-pf-remove]")
    page.wait_for(
        f"document.querySelector('[data-pf-list={SCOPE}]').dataset.pfEmpty === 'true'"
    )

    assert text(page, f"[data-pf-list={SCOPE}] .pf-list-empty") == (
        "No items added yet."
    )
    assert page.js(
        f"getComputedStyle(document.querySelector('[data-pf-list={SCOPE}]"
        " .pf-list-empty')).display"
    ) == ("block")
    assert page.js(
        f"document.querySelector('[data-pf-worksheet={WORKSHEET}]').dataset.pfEmpty"
    ) == ("true")
    assert text(page, f"[data-pf-worksheet={WORKSHEET}] .pf-ws-empty") == (
        "Add items in Section 3.2 — Scope of the project. "
        "They carry over here automatically."
    )


def worksheet_figures(page: Page) -> dict[str, list[str]]:
    result: dict[str, list[str]] = page.js(
        f"""(() => {{
          const ws = document.querySelector("[data-pf-worksheet={WORKSHEET}]");
          const read = (s) => [...ws.querySelectorAll(s)].map((c) => c.textContent);
          return {{
            totals: read("tbody[data-pf-rows] [data-pf-total]"),
            summary: read("[data-pf-sum]"),
          }};
        }})()"""
    )
    return result


def python_figures(values: dict[str, Any]) -> dict[str, list[str]]:
    """The worksheet's figures as pcn_clone.core computes them, in DOM order."""
    worksheet = field(WORKSHEET).input
    assert isinstance(worksheet, WorksheetInput)
    derived = derive_worksheet_rows(
        worksheet, coerce_string_record_array(values[SCOPE])
    )
    answer = coerce_worksheet_answer(values[WORKSHEET])
    totals = [
        format_amount(compute_row_total(worksheet, get_row_values(answer, r.row_id)))
        if r.has_start_date
        else "—"
        for r in derived
    ]
    summary = compute_category_summary(worksheet, derived, answer)
    cells = [
        format_amount(value)
        for row in summary.rows
        for value in [*(row.per_column[c.id] for c in summary.columns), row.total]
    ]
    return {"totals": totals, "summary": cells}


def test_worksheet_figures_match_the_core_calculations(page: Page) -> None:
    open_default(page)
    assert worksheet_figures(page) == python_figures(default_project_values())
    assert worksheet_figures(page)["summary"][-1] == "6,200,000"

    edits = {
        ("comp-design", "year_2"): "1234.565",
        ("comp-works", "subsequent_years"): "0.105",
        ("comp-equipment", "year_1"): "-50",
        ("comp-equipment", "year_3"): "2.675e3",
        ("comp-works", "cost_category"): "land",
    }
    for (row_id, control_id), value in edits.items():
        path = ["componentCosts", row_id, control_id]
        set_value(page, bound(WORKSHEET, path), value)

    values = snapshot(page)
    costs = values[WORKSHEET]["componentCosts"]
    assert costs["comp-design"]["year_2"] == "1234.565"
    assert costs["comp-works"]["cost_category"] == "land"
    assert worksheet_figures(page) == python_figures(values)


def test_number_formatting_matches_the_core(page: Page) -> None:
    open_default(page)
    amounts = [
        0, -0.0, 1, 12, 999, 1000, 1234567, 1234567.891, 0.1 + 0.2, 1.005,
        2.675, 1.115, 8.345, 0.125, 1e-7, 0.005, 0.0049, 123456789012.345,
        1e21, 2.5e-3, -1234.5, -0.005, 999999.995, 5e15 + 0.5, 1100000.004,
    ]  # fmt: skip
    entries = [
        "", "  ", "12", " 1e3 ", "0x10", "0b101", "0o17", "1_000", "1,000",
        ".5", "5.", "+3", "-5", "Infinity", "-Infinity", "NaN", "abc",
        "\u00a07\u2003", "1e400", "00012", "1.2.3", "-0",
    ]  # fmt: skip
    browser = page.js(
        f"""(() => {{
          const n = window.pcnNumbers;
          const entries = {json.dumps(entries)};
          return {{
            formatted: {json.dumps(amounts)}.map(n.formatAmount),
            totals: entries.map(n.toAmount),
            parsed: entries.map((e) => {{
              const p = n.parseAmount(e);
              return p.ok ? "ok" : p.reason;
            }}),
          }};
        }})()"""
    )

    parsed = [parse_amount(entry) for entry in entries]
    assert browser["formatted"] == [format_amount(a) for a in amounts]
    assert browser["totals"] == [to_amount(entry) for entry in entries]
    assert browser["parsed"] == [
        "ok" if isinstance(p, ParsedAmount) else p.reason for p in parsed
    ]


# --- Scenario comparisons and static tables -------------------------------------


def computed_cells(page: Page, field_id: str) -> list[str]:
    return texts(page, f"[data-pf-scenario={field_id}] [data-pf-computed]")


def python_computed(field_id: str, answer: Any) -> list[str]:
    scenario = field(field_id).input
    assert isinstance(scenario, ScenarioComparisonInput)
    cells = []
    for row in scenario.computed_rows:
        for column in scenario.columns:
            value = compute_computed_cell(answer, row, column.id)
            cells.append("—" if value is None else format_amount(value))
    return cells


def test_scenario_difference_row(page: Page) -> None:
    open_default(page)
    costs = "operating_costs"
    assert computed_cells(page, costs) == ["30,000", "33,000", "35,000"]
    assert computed_cells(page, costs) == python_computed(
        costs, default_project_values()[costs]
    )

    set_value(page, bound(costs, ["rows", "without_project", "year_2"]), "")
    set_value(page, bound(costs, ["rows", "with_project", "year_3"]), "95000.5")
    assert computed_cells(page, costs) == ["30,000", "—", "0.50"]
    assert computed_cells(page, costs) == python_computed(costs, snapshot(page)[costs])


def test_revenue_gate_no_disables_the_rows(page: Page) -> None:
    open_default(page)
    gate = bound("revenues", ["applicability", "revenue_expected"])
    entered = json.dumps("[data-pf-scenario=revenues] [data-pf-path^='[\"rows\"']")
    all_disabled = f"[...document.querySelectorAll({entered})].every((i) => i.disabled)"
    none_disabled = (
        f"[...document.querySelectorAll({entered})].every((i) => !i.disabled)"
    )
    assert page.js(f"document.querySelectorAll({entered}).length") == 6
    assert page.js(none_disabled) is True
    assert computed_cells(page, "revenues") == ["40,000", "48,000", "55,000"]

    set_value(page, gate, "no")
    page.wait_for(all_disabled)
    assert computed_cells(page, "revenues") == ["—", "—", "—"]
    assert snapshot(page)["revenues"]["rows"]["with_project"]["year_1"] == "40000"

    set_value(page, gate, "yes")
    page.wait_for(none_disabled)
    assert computed_cells(page, "revenues") == ["40,000", "48,000", "55,000"]


def test_static_table_no_makes_the_row_inert(page: Page) -> None:
    open_default(page)
    row = ["rows", "preliminary_feasibility_study"]
    gate = bound(PERMITS, [*row, "required"])

    def state() -> dict[str, Any]:
        def disabled(column: str) -> bool:
            result: bool = control(page, PERMITS, [*row, column], "disabled")
            return result

        return {
            "gate": control(page, PERMITS, [*row, "required"], "disabled"),
            "status": disabled("status"),
            "empty": control(page, PERMITS, [*row, "status"], "options[0].textContent"),
            "date": disabled("expected_acquisition_date"),
            "comment": disabled("comment"),
        }

    editable = {
        "gate": False,
        "status": False,
        "empty": "—",
        "date": False,
        "comment": False,
    }
    assert state() == editable

    set_value(page, gate, "no")
    assert state() == {**editable, "status": True, "empty": "n/a", "date": True}
    other = ["rows", "other_permissions", "status"]
    assert control(page, PERMITS, other, "disabled") is True

    set_value(page, gate, "yes")
    assert state() == editable


# --- Dialogs -------------------------------------------------------------------


def test_guidance_and_criteria_dialogs(page: Page) -> None:
    open_default(page)
    criteria = load_criteria().get("investment_rationale", "objectives")
    assert criteria is not None
    dialog = ".mantine-Modal-content"

    page.click(dash_id({"type": "pf-guidance-open", "field": "objectives"}))
    page.wait_for(exists(f"{dialog} .pf-dialog-prose"))
    assert text(page, f"{dialog} .pf-dialog-title") == "Field guidance"
    assert text(page, f"{dialog} .pf-dialog-field") == (
        "2.2 — Objectives of the project"
    )
    assert text(page, f"{dialog} .pf-dialog-prose") == field("objectives").guidance
    naming = page.js(
        f"""(() => {{
          const dialog = document.querySelector({json.dumps(dialog)});
          const name = document.getElementById(dialog.getAttribute("aria-labelledby"));
          return [dialog.getAttribute("role"), dialog.hasAttribute("aria-describedby"),
                  name.textContent];
        }})()"""
    )
    assert naming == [
        "dialog",
        False,
        "Field guidance2.2 — Objectives of the project",
    ]
    page.press("Escape")
    page.wait_for(f"!{exists(dialog)}")

    page.click(dash_id({"type": "pf-criteria-open", "field": "objectives"}))
    page.wait_for(exists(f"{dialog} .pf-rubric"))
    assert text(page, f"{dialog} .pf-dialog-title") == "Assessment criteria"
    assert texts(page, f"{dialog} .pf-rubric dt") == ["Pass", "Not Clear", "Fail"]
    assert texts(page, f"{dialog} .pf-rubric dd") == [
        criteria.verdicts.pass_,
        criteria.verdicts.not_clear,
        criteria.verdicts.fail,
    ]
    assert page.js(
        f"[...document.querySelectorAll('{dialog} .pf-rubric .pill')]"
        ".map((p) => p.classList[1])"
    ) == ["pill-pass", "pill-nc", "pill-fail"]


# --- Readiness -------------------------------------------------------------------


def test_incomplete_risk_lists_its_issues_and_blocks_evaluation(page: Page) -> None:
    open_default(page)
    panel = dash_id({"type": "pf-issues", "field": RISKS}) + " .pf-issues"
    button_disabled = (
        f"document.querySelector({json.dumps(evaluate_button(RISKS))}).disabled"
    )

    page.click(f"[data-pf-add={RISKS}]")
    page.wait_for(exists(panel))
    page.wait_for(button_disabled)

    expected = readiness("project_management_and_risks", RISKS, snapshot(page)[RISKS])
    assert expected
    assert text(page, f"{panel} p") == "Complete the following before evaluating:"
    assert texts(page, f"{panel} li") == expected

    new_row = f"{rows(RISKS)}[data-pf-row-id='{snapshot(page)[RISKS][-1]['_rowId']}']"
    set_value(page, f"{new_row} [data-pf-control=risk_factor]", "Contractor failure.")
    set_value(page, f"{new_row} [data-pf-control=likelihood]", "1")
    set_value(page, f"{new_row} [data-pf-control=impact]", "2")
    page.wait_for(f"!{exists(panel)}")
    page.wait_for(f"!{button_disabled}")


def test_a_blank_text_field_is_not_ready_and_lists_nothing(page: Page) -> None:
    open_default(page)
    button = json.dumps(evaluate_button("project_location"))

    set_value(page, bound("project_location", []), "   ")
    page.wait_for(f"document.querySelector({button}).disabled")
    issues = dash_id({"type": "pf-issues", "field": "project_location"})
    assert count(page, f"{issues} > *") == 0


def test_a_click_right_after_blanking_a_field_sends_nothing(page: Page) -> None:
    open_default(page)
    location = "project_location"
    verdict = evaluate_and_wait(page, location)
    before = state(page, location)
    button = json.dumps(evaluate_button(location))
    page.send("Network.enable")
    since = len(page.events)

    enabled = edit_then_click(page, location, edit_script(bound(location, []), ""))

    page.wait_for(f"document.querySelector({button}).disabled")
    page.pump(FAKE_DELAY)
    assert enabled is True
    assert dash_requests(page, EVALUATIONS, since) == []
    assert state(page, location) == before
    assert footer(page, location) == {
        "status": f"{label(verdict)}Out of date · view notesFeedback out of date",
        "label": "Re-evaluate",
        "primary": True,
        "disabled": True,
    }


def test_a_click_right_after_breaking_a_graded_list_sends_nothing(page: Page) -> None:
    open_default(page)
    verdict = evaluate_and_wait(page, RISKS)
    before = state(page, RISKS)
    likelihood = f"{rows(RISKS)}:first-child [data-pf-control=likelihood]"
    panel = dash_id({"type": "pf-issues", "field": RISKS}) + " .pf-issues"
    page.send("Network.enable")
    since = len(page.events)

    enabled = edit_then_click(page, RISKS, edit_script(likelihood, "", "change"))

    page.wait_for(exists(panel))
    page.pump(FAKE_DELAY)
    assert enabled is True
    assert dash_requests(page, EVALUATIONS, since) == []
    assert state(page, RISKS) == before
    assert footer(page, RISKS) == {
        "status": f"{label(verdict)}Out of date · view notesFeedback out of date",
        "label": "Re-evaluate",
        "primary": True,
        "disabled": True,
    }
    assert texts(page, f"{panel} li") == readiness(
        "project_management_and_risks", RISKS, snapshot(page)[RISKS]
    )


def serve_paused(
    page: Page,
    since: int,
    rewrite: Callable[[dict[str, Any]], dict[str, Any]],
    until: str,
    timeout: float = 10,
) -> int:
    """Continue every Dash request the page pauses (``Fetch.enable``),
    passing each evaluate request's body through ``rewrite``, until ``until``
    holds after one was served; return how many were."""
    served = 0
    handled: set[str] = set()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for event in page.events[since:]:
            params = event["params"]
            if event["method"] != "Fetch.requestPaused":
                continue
            if params["requestId"] in handled:
                continue
            handled.add(params["requestId"])
            command: dict[str, Any] = {"requestId": params["requestId"]}
            body = json.loads(params["request"].get("postData") or "{}")
            if EVALUATIONS in body.get("output", ""):
                served += 1
                rewritten = json.dumps(rewrite(body)).encode()
                command["postData"] = base64.b64encode(rewritten).decode()
            page.send("Fetch.continueRequest", command)
        if served and page.js(until):
            return served
        page.pump(0.05)
    raise AssertionError(f"{until!r} did not hold within {timeout} s")


def test_an_answer_the_server_refuses_keeps_the_earlier_verdict(page: Page) -> None:
    """The server re-checks readiness before any model call; a refusal
    leaves the field as it was rather than failed."""
    open_default(page)
    location = "project_location"
    verdict = evaluate_and_wait(page, location)
    before = state(page, location)

    def blank_the_answer(body: dict[str, Any]) -> dict[str, Any]:
        body["inputs"][0]["value"]["answer"] = "   "
        return body

    page.send(
        "Fetch.enable",
        {"patterns": [{"urlPattern": "*_dash-update-component*"}]},
    )
    since = len(page.events)
    page.click(evaluate_button(location))
    served = serve_paused(
        page,
        since,
        blank_the_answer,
        f"window.pcnForm.state({json.dumps(location)}).status === 'graded'",
    )
    page.send("Fetch.disable")

    assert served == 1
    assert state(page, location) == before
    page.wait_for(
        f"!document.querySelector({json.dumps(evaluate_button(location))}).disabled"
    )
    assert footer(page, location) == {
        "status": f"{label(verdict)}View review notes",
        "label": "Re-evaluate",
        "primary": False,
        "disabled": False,
    }


# --- Evaluation ------------------------------------------------------------------


def test_evaluate_shows_the_verdict_review_notes_and_stale_feedback(
    page: Page,
) -> None:
    open_default(page)
    location = "project_location"

    button = evaluate_button(location)
    assert aria_label(page, button) == field_action(
        EVALUATE_LABEL, "1.2", "Project location"
    )

    page.click(button)
    page.wait_for(evaluating(location))
    assert footer(page, location) == {
        "status": "Evaluating…",
        "label": "Evaluating…",
        "primary": True,
        "disabled": True,
    }
    # The live region announces the state; the button keeps its action.
    assert page.js(
        f"document.querySelector({json.dumps(status(location))})"
        ".getAttribute('aria-live')"
    ) == ("polite")
    assert aria_label(page, button) == field_action(
        EVALUATE_LABEL, "1.2", "Project location"
    )
    assert text(page, tally(FIRST_SECTION)) == "1 evaluating2 not evaluated"

    page.wait_for(graded(location), timeout=5)
    result = page.js(f"window.pcnForm.state({json.dumps(location)})")["result"]
    verdict = {"pass": "Pass", "notClear": "Not Clear", "fail": "Fail"}[
        result["verdict"]
    ]
    assert footer(page, location) == {
        "status": f"{verdict}View review notes",
        "label": "Re-evaluate",
        "primary": False,
        "disabled": False,
    }
    assert aria_label(page, button) == field_action(
        "Re-evaluate", "1.2", "Project location"
    )
    assert text(page, tally(FIRST_SECTION)) == f"1 {verdict}2 not evaluated"

    notes = ".pf-notes-dialog"
    page.click(notes_button(location))
    page.wait_for(exists(f"{notes} .pf-notes-heading"))
    assert text(page, f"{notes} .pf-dialog-title") == "Review notes (AI)"
    assert text(page, f"{notes} .pf-dialog-field") == "1.2 — Project location"
    assert text(page, f"{notes} .mantine-Modal-header .pf-verdict") == verdict
    headings = ["Reasoning", "Suggestions"] if result["suggestions"] else ["Reasoning"]
    assert texts(page, f"{notes} .pf-notes-heading") == headings
    assert text(page, f"{notes} .pf-dialog-prose") == result["reasoning"]
    assert texts(page, f"{notes} .pf-notes-suggestions li") == result["suggestions"]
    assert page.js(exists(f"{notes} .pf-notes-stale")) is False
    page.press("Escape")
    page.wait_for(f"!{exists(notes)}")

    type_at_end(page, bound(location, []), " (edited)")
    page.wait_for(exists(f"{status(location)} .pf-badge.is-stale"))
    assert footer(page, location) == {
        "status": f"{verdict}Out of date · view notesFeedback out of date",
        "label": "Re-evaluate",
        "primary": True,
        "disabled": False,
    }
    page.click(notes_button(location))
    page.wait_for(exists(f"{notes} .pf-notes-stale"))
    assert text(page, f"{notes} .pf-notes-stale").startswith("Feedback is out of date")
    page.press("Escape")
    page.wait_for(f"!{exists(notes)}")

    # Restoring the evaluated answer makes the feedback current again.
    set_value(page, bound(location, []), default_project_values()[location])
    page.wait_for(f"!{exists(f'{status(location)} .pf-badge')}")
    assert footer(page, location)["status"] == f"{verdict}View review notes"


def test_a_failed_evaluation_can_be_retried(page: Page) -> None:
    open_default(page)

    page.click(evaluate_button(FAILING_FIELD))
    page.wait_for(exists(f"{status(FAILING_FIELD)} .pf-badge.is-failed"), timeout=5)
    assert footer(page, FAILING_FIELD) == {
        "status": FAILED,
        "label": "Evaluate field",
        "primary": True,
        "disabled": False,
    }
    assert page.js(exists(f"{status(FAILING_FIELD)} [role=alert]")) is True
    assert text(page, tally(FIRST_SECTION)) == "1 failed2 not evaluated"

    page.click(evaluate_button(FAILING_FIELD))
    page.wait_for(evaluating(FAILING_FIELD))
    page.wait_for(has_text(status(FAILING_FIELD), FAILED), timeout=5)


def test_two_fields_evaluate_at_once(page: Page) -> None:
    """Each fake model call sleeps ``FAKE_DELAY`` inside its request's
    network window. Had the calls run one after the other, one request would
    have to end at least ``2 * FAKE_DELAY`` after the other began; every
    such span is shorter, so the calls overlapped."""
    open_default(page)
    fields = ("project_location", "implementation_period")
    page.send("Network.enable")
    since = len(page.events)

    page.js(
        "["
        + ", ".join(json.dumps(evaluate_button(f)) for f in fields)
        + "].forEach((s) => document.querySelector(s).click()), true"
    )
    page.wait_for(" && ".join(evaluating(f) for f in fields))
    assert text(page, tally(FIRST_SECTION)) == "2 evaluating1 not evaluated"
    page.wait_for(" && ".join(graded(f) for f in fields), timeout=10)

    requests = dash_requests(page, EVALUATIONS, since)
    assert len(requests) == 2
    (sent_a, done_a), (sent_b, done_b) = (
        request_window(page, r["requestId"]) for r in requests
    )
    assert min(done_a - sent_a, done_b - sent_b) >= FAKE_DELAY
    assert max(done_a - sent_b, done_b - sent_a) < 2 * FAKE_DELAY


def test_a_late_result_is_kept_and_marked_stale(page: Page) -> None:
    open_default(page)

    page.click(evaluate_button("objectives"))
    page.wait_for(evaluating("objectives"))
    type_at_end(page, bound("objectives", []), " Typed while evaluating.")

    page.wait_for(graded("objectives"), timeout=5)
    assert page.js("window.pcnForm.state('objectives').status") == "graded"
    assert page.js(exists(f"{status('objectives')} .pf-badge.is-stale")) is True
    assert "Out of date · view notes" in footer(page, "objectives")["status"]


def test_the_server_grades_the_answer_on_screen(page: Page) -> None:
    """An evaluate request carries the field's answer (and a worksheet's
    row-source context) as it was when Evaluate was clicked, not the whole
    form."""
    open_default(page)
    button = json.dumps(evaluate_button("objectives"))
    set_value(page, bound("objectives", []), "")
    page.wait_for(f"document.querySelector({button}).disabled")
    set_value(page, bound("objectives", []), "Cut travel time to 35 minutes.")
    page.wait_for(f"!document.querySelector({button}).disabled")

    page.send("Network.enable")
    since = len(page.events)
    page.click(evaluate_button("objectives"))
    page.click(evaluate_button(WORKSHEET))
    page.wait_for(graded("objectives") + " && " + graded(WORKSHEET), timeout=5)

    sent = {
        r["body"]["inputs"][0]["id"]["field"]: r["body"]
        for r in dash_requests(page, EVALUATIONS, since)
    }
    values = snapshot(page)
    assert sent["objectives"]["inputs"][0]["value"] == {
        "answer": "Cut travel time to 35 minutes.",
        "context": None,
        "n": 1,
    }
    assert sent[WORKSHEET]["inputs"][0]["value"] == {
        "answer": values[WORKSHEET],
        "context": [
            {
                "sectionId": "project_description_and_impact",
                "fieldId": SCOPE,
                "answer": values[SCOPE],
            }
        ],
        "n": 1,
    }
    for body in sent.values():
        assert [s["id"] for s in body["state"]][1:] == ["pf-project"]
        assert "form-values" not in json.dumps(body)
    assert len(json.dumps(sent["objectives"])) < 1000


# --- Recovery and markup ---------------------------------------------------------


def remove_and_wait(page: Page, selector: str) -> None:
    """Remove a control from its slot and wait for form.js to restore it."""
    page.js(f"document.querySelector({json.dumps(selector)}).remove(), true")
    page.wait_for(exists(selector))


def test_a_slot_that_loses_its_input_gets_it_back(page: Page) -> None:
    open_default(page)
    expected = default_project_values()

    title = bound("project_title", [])
    remove_and_wait(page, title)
    assert control(page, "project_title", []) == expected["project_title"]
    set_value(page, title, "Renamed")
    assert snapshot(page)["project_title"] == "Renamed"

    # A cell of an inert row comes back disabled.
    date = ["rows", "other_permissions", "expected_acquisition_date"]
    assert control(page, PERMITS, date, "disabled") is True
    remove_and_wait(page, bound(PERMITS, date))
    assert control(page, PERMITS, date, "disabled") is True

    # Where the browser has no month picker, a month asks for typed YYYY-MM.
    start = ["project_start_date"]
    page.js(
        """(() => {
          window.realType = Object.getOwnPropertyDescriptor(
            HTMLInputElement.prototype, "type");
          Object.defineProperty(HTMLInputElement.prototype, "type", {
            configurable: true,
            get() { return "text"; },
            set(value) { this.setAttribute("type", value); },
          });
          return true;
        })()"""
    )
    try:
        remove_and_wait(page, bound("implementation_period", start))
    finally:
        page.js(
            "Object.defineProperty(HTMLInputElement.prototype, 'type',"
            " window.realType), true"
        )
    month = json.dumps(bound("implementation_period", start))
    assert page.js(
        f"(() => {{ const el = document.querySelector({month});"
        " return [el.placeholder, el.pattern, el.inputMode, el.value]; })()"
    ) == [
        "YYYY-MM",
        r"\d{4}-(0[1-9]|1[0-2])",
        "numeric",
        expected["implementation_period"]["project_start_date"],
    ]


def test_markup_drawn_in_the_browser_matches_the_python_components(
    page: Page,
) -> None:
    """form.js draws tallies, Evaluate buttons, verdict pills and the notes
    heading that the Python side also renders; both must agree."""
    open_default(page)

    idle = dom_shape(page, tally("investment_rationale"))
    assert idle[2:] == [shape(item) for item in idle_tally(2)]

    title_button = evaluate_button_component(field("project_title"))
    drawn = dom_shape(page, evaluate_button("project_title"))
    assert drawn[2:] == [shape(child) for child in title_button.children]
    assert {k: drawn[1][k] for k in ("class", "aria-label")} == {
        k: shape(title_button)[1][k] for k in ("class", "aria-label")
    }

    verdict = evaluate_and_wait(page, "objectives")
    pill = shape(verdict_pill(verdict, small=True))
    assert dom_shape(page, f"{status('objectives')} .pf-verdict") == pill

    page.click(notes_button("objectives"))
    heading = ".pf-notes-dialog .mantine-Modal-title"
    page.wait_for(exists(f"{heading} .pf-verdict"))
    expected = [
        *dialog_heading("sparkle", "blue", "Review notes (AI)", field("objectives")),
        verdict_pill(verdict, small=True),
    ]
    assert dom_shape(page, heading)[2:] == [shape(node) for node in expected]
    assert (
        page.js(
            "document.querySelector('.pf-notes-dialog').hasAttribute('aria-describedby')"
        )
        is False
    )


def test_submit_is_enabled_once_the_draft_is_restored(page: Page) -> None:
    open_default(page)

    state = page.js(
        """(() => {
          const submit = document.getElementById("pf-submit");
          return [submit.disabled, submit.hasAttribute("aria-disabled"),
                  submit.getAttribute("aria-busy"), window.pcnForm.hydrated()];
        })()"""
    )

    assert state == [False, False, "false", True]


# --- Chrome ---------------------------------------------------------------------


def test_jump_menu_scrolls_to_a_section_and_progress_grows(page: Page) -> None:
    open_default(page)
    page.send(
        "Emulation.setEmulatedMedia",
        {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]},
    )
    progress = (
        "parseFloat(document.documentElement.style"
        ".getPropertyValue('--scroll-progress') || '0')"
    )
    assert page.js(progress) == 0

    page.click("#pf-jump-trigger")
    page.wait_for(exists(".pf-jump-menu"))
    assert texts(page, ".pf-jump-menu .pf-jump-label") == ["Jump to section"]
    assert texts(page, ".pf-jump-menu .mantine-Menu-itemLabel") == [
        section.title for section in load_template().sections
    ]
    assert count(page, ".pf-jump-menu .pf-jump-item.is-active") == 1
    assert page.js(exists(".pf-jump-item.is-active [data-icon=check]")) is True

    page.click("[data-pf-jump=estimated_investment_costs_and_financing]")
    page.wait_for(has_text("#pf-jump-number", "4"))
    offset = page.js(
        """(() => {
          let chrome = 0;
          for (const el of document.querySelectorAll("[data-sticky-chrome]")) {
            chrome += el.getBoundingClientRect().height;
          }
          const anchor = document.getElementById(
            "section-estimated_investment_costs_and_financing");
          return anchor.getBoundingClientRect().top - chrome;
        })()"""
    )
    assert abs(offset - 18) <= 1
    assert text(page, "#pf-jump-title") == (
        "Estimated investment costs and expected financing"
    )
    section = load_template().sections[3]
    assert aria_label(page, "#pf-jump-trigger") == jump_label(section)
    assert aria_label(page, "#pf-jump-trigger") == (
        "Jump to section. Current: 4 Estimated investment costs and expected financing"
    )
    page.wait_for(
        "document.activeElement.matches("
        "'#section-estimated_investment_costs_and_financing h2')"
    )
    # Reopened in place: a pointer click would scroll the sticky trigger.
    page.js("document.getElementById('pf-jump-trigger').click(), true")
    page.wait_for(exists(".pf-jump-item.is-active [data-icon=check]"))
    assert text(page, ".pf-jump-item.is-active .mantine-Menu-itemLabel") == (
        section.title
    )
    assert dom_shape(page, ".pf-jump-item.is-active [data-icon=check]") == shape(
        jump_item_props(True)["rightSection"]
    )
    page.press("Escape")
    page.wait_for(f"!{exists('.pf-jump-menu')}")
    page.wait_for(f"{progress} > 30")
    fill = "document.querySelector('.pf-progress-fill').getBoundingClientRect().width"
    page.wait_for(f"{fill} > 0.3 * window.innerWidth")

    page.wait_for(
        "document.getElementById('pf-back-to-top').classList.contains('is-visible')"
    )
    assert page.js("document.getElementById('pf-back-to-top').tabIndex") == 0
    page.click("#pf-back-to-top")
    page.wait_for("window.scrollY === 0")
    page.wait_for(has_text("#pf-jump-number", "1"))
    page.wait_for(f"{progress} === 0")


def test_no_horizontal_scroll_on_a_narrow_screen(page: Page) -> None:
    project_id = seed_default(page)
    page.set_viewport(390, 844)
    open_form(page, project_id)
    no_overflow = "document.documentElement.scrollWidth <= window.innerWidth"

    assert page.js(no_overflow) is True
    for selector in ("[data-pf-worksheet]", f"[data-pf-static={PERMITS}]"):
        page.js(f"document.querySelector({json.dumps(selector)}).scrollIntoView(); 1")
        assert page.js(no_overflow) is True
    autosave = "getComputedStyle(document.getElementById('pf-autosave')).display"
    assert page.js(autosave) == "none"
