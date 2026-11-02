"""The proposer workspace's Python side: the layout renders every field with
its input kind, unique ids and accessible names; the client configuration
describes the template and carries every id, message and value form.js
shares with the server; no callback re-renders an ancestor of a control;
the signature rule; and the readiness and evaluate callbacks, which
delegate to ``pcn_clone.ai``. Behaviour in a browser is covered by
``tests/browser/test_form_flow.py``."""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from dash import Dash, dcc, html, no_update
from dash.development.base_component import Component

from pcn_clone.ai import FieldEvaluation, FieldEvaluationResponse, readiness
from pcn_clone.app.form import callbacks, form_view
from pcn_clone.app.form.config import LOCAL_READINESS_KINDS, client_config
from pcn_clone.app.form.ids import EVALUATE, EVALUATE_REQUEST, ISSUES
from pcn_clone.app.form.messages import NOT_READY, TRANSPORT_FAILURE
from pcn_clone.app.form.signature import field_signature, worksheet_context
from pcn_clone.app.form.template import find_field
from pcn_clone.app.projects_data import default_project_values
from pcn_clone.content import load_template
from pcn_clone.content.models import TemplateField
from pcn_clone.core.static_table import STATIC_TABLE_INERT_VALUE
from tests.app_helpers import walk

if TYPE_CHECKING:
    from starlette.testclient import TestClient

FORM_JS = (
    Path(__file__).resolve().parents[1] / "pcn_clone" / "app" / "assets" / "form.js"
).read_text(encoding="utf-8")

EXPECTED_KINDS = {
    "project_title": "text",
    "project_location": "text",
    "implementation_period": "group",
    "issues_and_justification": "textarea",
    "objectives": "textarea",
    "alternative_options_considered": "textarea",
    "scope_of_the_project": "list",
    "project_beneficiaries": "textarea",
    "project_social_impact": "textarea",
    "gender_equality": "textarea",
    "environmental_and_climate_impacts": "textarea",
    "climate_change_adaptation_and_mitigation": "textarea",
    "investment_cost_estimate": "worksheet",
    "operating_costs": "scenario_comparison",
    "revenues": "scenario_comparison",
    "project_risks": "list",
    "management_arrangements": "textarea",
    "documentation_and_permits": "static_table",
    "land_and_property_status": "static_table",
}

SERVER_DECIDED = [
    f for f, kind in EXPECTED_KINDS.items() if kind not in LOCAL_READINESS_KINDS
]

WILDCARDS = (["ALL"], ["MATCH"], ["ALLSMALLER"])

JS_OWNED = (
    "data-pf-path",
    "data-pf-input",
    "data-pf-control",
    "data-pf-rows",
    "data-pf-computed",
    "data-pf-sum",
)
"""Attributes of the elements form.js writes to directly (bound controls,
input slots, prototype controls, drawn rows and computed cells)."""


def props(component: Component) -> dict[str, Any]:
    result: dict[str, Any] = component.to_plotly_json()["props"]
    return result


def field(field_id: str) -> TemplateField:
    found = find_field(field_id)
    assert found is not None
    return found[1]


def section_of(field_id: str) -> str:
    found = find_field(field_id)
    assert found is not None
    return found[0].id


def request_for(field_id: str, values: dict[str, Any], n: int = 1) -> dict[str, Any]:
    """The request form.js sends for a field's answer in ``values``."""
    context = worksheet_context(field(field_id), values) or None
    return {"answer": values[field_id], "context": context, "n": n}


def store(kind: str, field_id: str) -> dict[str, str]:
    return {"type": kind, "field": field_id}


@pytest.fixture(scope="module")
def view(app: Dash) -> list[Component]:
    """The workspace for one project, rendered within the session's app."""
    return form_view({"id": "p-1", "title": "Upper Valley"})


def cards(view: list[Component]) -> dict[str, Component]:
    return {
        props(c)["data-pf-card"]: c for c in walk(view) if "data-pf-card" in props(c)
    }


def controls(card: Component) -> list[tuple[str, Any]]:
    """The card's controls as ``(kind, binding)``: a bound control's binding
    is its path, a prototype control's its control id."""
    found: list[tuple[str, Any]] = []
    for node in walk(card):
        attributes = props(node)
        if "data-pf-input" in attributes:
            declared = json.loads(attributes["data-pf-input"])
            kind = f"input:{declared['type']}"
        elif isinstance(node, html.Textarea):
            kind, declared = "textarea", attributes
        elif isinstance(node, html.Select):
            kind, declared = "select", attributes
        else:
            continue
        if "data-pf-path" in declared:
            found.append((kind, json.loads(declared["data-pf-path"])))
        else:
            found.append((kind, declared["data-pf-control"]))
    return found


def text_of(node: Any) -> str:
    """The text a component tree renders, sr-only text included."""
    if isinstance(node, str):
        return node
    if isinstance(node, list | tuple):
        return "".join(text_of(child) for child in node)
    if isinstance(node, Component):
        return text_of(getattr(node, "children", None))
    return ""


# --- Layout ------------------------------------------------------------------


def test_layout_renders_all_nineteen_fields_with_their_kinds(
    view: list[Component],
) -> None:
    found = cards(view)

    assert list(found) == [f.id for _, f in load_template().iter_fields()]
    assert {fid: props(c)["data-pf-kind"] for fid, c in found.items()} == (
        EXPECTED_KINDS
    )


def test_each_kind_renders_its_controls(view: list[Component]) -> None:
    found = {fid: controls(card) for fid, card in cards(view).items()}

    assert found["project_title"] == [("input:text", [])]
    assert found["objectives"] == [("textarea", [])]
    assert found["implementation_period"] == [
        ("input:month", ["project_start_date"]),
        ("input:month", ["estimated_project_completion_date"]),
    ]
    assert found["scope_of_the_project"] == [
        ("input:text", "component"),
        ("input:month", "expected_start_date"),
        ("input:month", "expected_end_date"),
    ]
    assert found["project_risks"] == [
        ("textarea", "risk_factor"),
        ("select", "likelihood"),
        ("select", "impact"),
        ("textarea", "risk_reduction_measures"),
    ]
    years = ["year_1", "year_2", "year_3", "year_4", "year_5", "subsequent_years"]
    assert found["investment_cost_estimate"] == [
        ("textarea", ["narratives", "estimation_basis"]),
        ("textarea", ["narratives", "financing_sources"]),
        *(("input:number", control) for control in years),
        ("select", "cost_category"),
    ]
    cells = [
        ("input:number", ["rows", row, column])
        for row in ("with_project", "without_project")
        for column in ("year_1", "year_2", "year_3")
    ]
    assert found["operating_costs"] == [
        *cells,
        ("textarea", ["narratives", "justification"]),
        ("textarea", ["narratives", "financing_approach"]),
    ]
    assert found["revenues"] == [
        ("select", ["applicability", "revenue_expected"]),
        *cells,
        ("textarea", ["narratives", "justification"]),
    ]
    assert found["land_and_property_status"] == [
        ("select", ["rows", "land_ownership", "required"]),
        ("select", ["rows", "land_ownership", "status"]),
        ("input:month", ["rows", "land_ownership", "expected_acquisition_date"]),
        ("textarea", ["rows", "land_ownership", "comment"]),
    ]
    assert len(found["documentation_and_permits"]) == 8 * 4


def test_ids_are_unique(view: list[Component]) -> None:
    ids = [
        json.dumps(c.id, sort_keys=True) if isinstance(c.id, dict) else c.id
        for c in walk(view)
        if getattr(c, "id", None) is not None
    ]
    slot_ids = [
        json.loads(props(c)["data-pf-input"]).get("id")
        for c in walk(view)
        if "data-pf-input" in props(c)
    ]
    every = ids + [i for i in slot_ids if i]

    assert [i for i, n in Counter(every).items() if n > 1] == []
    for field_id in EXPECTED_KINDS:
        assert json.dumps({"field": field_id, "type": EVALUATE}, sort_keys=True) in ids


def test_project_answer_and_readiness_stores(view: list[Component]) -> None:
    stores = {
        c.id: c
        for c in walk(view)
        if isinstance(c, dcc.Store) and isinstance(c.id, str)
    }

    assert stores["pf-project"].data == {"id": "p-1", "title": "Upper Valley"}
    assert stores["form-values"].storage_type == "memory"
    assert getattr(stores["form-values"], "data", None) is None
    assert stores["pf-config"].data == client_config()
    for name in ("pf-readiness-request", "pf-readiness"):
        assert stores[name].storage_type == "memory"
    panels = [
        c.id["field"]
        for c in walk(view)
        if isinstance(getattr(c, "id", None), dict) and c.id["type"] == ISSUES
    ]
    assert panels == SERVER_DECIDED


def test_the_template_body_is_built_once(app: Dash) -> None:
    first = form_view({"id": "p-1", "title": "One"})
    second = form_view({"id": "p-2", "title": "Two"})

    first_root, second_root = first[-1], second[-1]
    assert first_root.children[0] is not second_root.children[0]
    assert all(
        a is b
        for a, b in zip(first_root.children[1:], second_root.children[1:], strict=True)
    )


def test_evaluate_buttons_open_disabled_until_readiness_is_known(
    view: list[Component],
) -> None:
    buttons = [c for c in walk(view) if "data-pf-evaluate" in props(c)]

    assert len(buttons) == 19
    assert all(b.disabled is True for b in buttons)


def test_field_buttons_are_named_by_their_field(view: list[Component]) -> None:
    names: dict[str, list[str]] = {}
    for card_id, card in cards(view).items():
        number, title = field(card_id).number, field(card_id).title
        for node in walk(card):
            if isinstance(node, html.Button) and "aria-label" in props(node):
                label = props(node)["aria-label"]
                if label.endswith(f": {number} {title}"):
                    names.setdefault(card_id, []).append(label)

    assert len(names) == 19
    assert names["objectives"] == [
        "Field guidance: 2.2 Objectives of the project",
        "Assessment criteria: 2.2 Objectives of the project",
        "Evaluate field: 2.2 Objectives of the project",
    ]
    every = [label for labels in names.values() for label in labels]
    assert len(every) == len(set(every)) == 57


def test_dialog_names_separate_number_and_title(view: list[Component]) -> None:
    dialogs = [
        c
        for c in walk(view)
        if isinstance(getattr(c, "id", None), dict)
        and c.id["type"] in ("pf-guidance-dialog", "pf-criteria-dialog")
    ]
    objectives = [d for d in dialogs if d.id["field"] == "objectives"]

    assert len(dialogs) == 38
    assert [text_of(d.title) for d in objectives] == [
        "Field guidance2.2 — Objectives of the project",
        "Assessment criteria2.2 — Objectives of the project",
    ]
    separators = [
        c for d in objectives for c in walk(d.title) if c.className == "sr-only"
    ]
    assert [c.children for c in separators] == [" — ", " — "]


def test_section_headings_take_the_focus_after_a_jump(view: list[Component]) -> None:
    headings = [c for c in walk(view) if isinstance(c, html.H2)]

    assert len(headings) == len(load_template().sections)
    assert all(h.tabIndex == "-1" for h in headings)


def test_submit_opens_focusable_and_waits_for_the_draft(
    view: list[Component],
) -> None:
    (submit,) = [c for c in walk(view) if getattr(c, "id", None) == "pf-submit"]
    present = {c.id for c in walk(view) if isinstance(getattr(c, "id", None), str)}

    assert getattr(submit, "disabled", None) is None
    assert props(submit)["aria-disabled"] == "true"
    assert props(submit)["aria-busy"] == "false"
    assert props(submit)["aria-label"] == "Submit for assessment"
    assert [c.className for c in walk(submit) if c is not submit] == [
        "icon",
        "spinner pf-submit-spinner",
        "pf-submit-label",
    ]
    assert {"pf-submit-request", "pf-submit-snapshot", "pf-nav"} <= present


# --- Callback targets ----------------------------------------------------------


def _fits(pattern: Any, component_id: Any) -> bool:
    """Whether a callback's output id addresses the component with
    ``component_id``."""
    if isinstance(pattern, str):
        return pattern == component_id
    return (
        isinstance(component_id, dict)
        and set(pattern) == set(component_id)
        and all(
            value in WILDCARDS or component_id[key] == value
            for key, value in pattern.items()
        )
    )


def callback_outputs(client: TestClient) -> list[Any]:
    """Every component id a callback writes to, its running outputs
    included."""
    references: list[str] = []
    for dependency in client.get("/_dash-dependencies").json():
        output = dependency["output"]
        if not dependency["no_output"]:
            references += (
                output[2:-2].split("...") if output.startswith("..") else [output]
            )
        for running in ("running", "runningOff"):
            references += list(dependency.get(running) or {})
    outputs = []
    for reference in references:
        raw = reference.split("@", 1)[0].rsplit(".", 1)[0]
        outputs.append(json.loads(raw) if raw.startswith("{") else raw)
    return outputs


def test_nothing_rerenders_an_ancestor_of_a_control(
    view: list[Component], client: TestClient
) -> None:
    """form.js creates the inputs inside slots, draws rows and computes
    cells in elements Dash rendered; a component that a callback (or
    form.js through ``set_props``) re-renders must hold none of them."""
    outputs = callback_outputs(client)
    script_ids = [
        value
        for name, value in client_config()["ids"].items()
        if name not in ("root", "anchorPrefix")
    ]

    def targeted(component: Component) -> bool:
        component_id = getattr(component, "id", None)
        if component_id is None:
            return False
        if any(_fits(output, component_id) for output in outputs):
            return True
        if isinstance(component_id, dict):
            return component_id.get("type") in script_ids
        return component_id in script_ids

    targets = [c for c in walk(view) if targeted(c)]
    owners = [
        (getattr(target, "id", None), attribute)
        for target in targets
        for node in list(walk(target))[1:]
        for attribute in JS_OWNED
        if attribute in props(node)
    ]

    assert len(targets) > 19 * 3
    assert owners == []


# --- Configuration -------------------------------------------------------------


def test_defaults_follow_each_kind() -> None:
    defaults = {
        field_id: spec["default"]
        for field_id, spec in client_config()["fields"].items()
    }

    assert defaults["project_title"] == ""
    assert defaults["implementation_period"] == {
        "project_start_date": "",
        "estimated_project_completion_date": "",
    }
    assert defaults["scope_of_the_project"] == []
    assert defaults["investment_cost_estimate"] == {
        "componentCosts": {},
        "narratives": {},
    }
    assert defaults["revenues"] == {"applicability": {}, "rows": {}, "narratives": {}}
    assert defaults["land_and_property_status"] == {"rows": {}}
    assert set(defaults) == set(EXPECTED_KINDS)


def test_client_config_carries_the_live_calculation_facts() -> None:
    config = client_config()
    fields = config["fields"]
    worksheet = fields["investment_cost_estimate"]
    revenues = fields["revenues"]

    assert config["sections"][0]["fieldIds"] == [
        "project_title",
        "project_location",
        "implementation_period",
    ]
    assert worksheet["rowSource"]["fieldId"] == "scope_of_the_project"
    assert worksheet["rowSource"]["number"] == "3.2"
    assert worksheet["requiredSpan"] == 5
    assert worksheet["sum"][-1] == "subsequent_years"
    assert worksheet["categories"][0]["value"] == "preparatory_documentation"
    assert revenues["gate"] == {"id": "revenue_expected", "activeValue": "yes"}
    assert fields["operating_costs"]["gate"] is None
    assert fields["land_and_property_status"]["gateColumn"] == "required"
    assert fields["land_and_property_status"]["inertValue"] == STATIC_TABLE_INERT_VALUE
    assert config["verdicts"]["notClear"] == {"label": "Not Clear", "pill": "pill-nc"}
    assert [f for f, spec in fields.items() if spec["readiness"] == "server"] == (
        SERVER_DECIDED
    )


def test_form_js_takes_ids_messages_and_the_inert_value_from_the_config() -> None:
    """Component ids, the text both sides show and the static table's inert
    value reach form.js through the client configuration only."""
    literal_ids = [
        r"getElementById\(\s*[\"'`]",
        r"\bsetProps\(\s*[\"'`]",
        r"\bsetPropsOnce\(\s*[^,]+,\s*[\"'`]",
        r"\bfieldKey\(\s*[\"'`]",
        r"type:\s*[\"'`]pf-",
        r"[\"'`]#[\w-]",
    ]
    assert [p for p in literal_ids if re.search(p, FORM_JS)] == []

    config = client_config()
    assert config["ids"]["anchorPrefix"] not in FORM_JS
    for name, message in config["messages"].items():
        assert message not in FORM_JS, name
        for fragment in re.split(r"\{\w+\}", message):
            if len(fragment) > 3:
                assert fragment not in FORM_JS, (name, fragment)
    assert f'"{STATIC_TABLE_INERT_VALUE}"' not in FORM_JS
    assert config["messages"]["transportFailure"] == TRANSPORT_FAILURE


# --- Signatures ----------------------------------------------------------------


def test_plain_signature_is_the_serialized_text() -> None:
    text = "  Road \u2019000 \u2014  "
    assert field_signature(field("project_title"), text) == text
    assert field_signature(field("objectives"), "") == ""
    assert field_signature(
        field("implementation_period"),
        {"project_start_date": "2026-03", "estimated_project_completion_date": ""},
    ) == ("Project Start Date: 2026-03\nEstimated Project Completion Date: ")


def test_composite_signatures_are_their_json() -> None:
    items = [
        {
            "_rowId": "r1",
            "component": 'Road "A"\n',
            "expected_start_date": "2026-03",
            "expected_end_date": "",
        }
    ]
    assert field_signature(field("scope_of_the_project"), items) == (
        '[{"_rowId":"r1","component":"Road \\"A\\"\\n",'
        '"expected_start_date":"2026-03","expected_end_date":""}]'
    )
    assert field_signature(field("project_risks"), None) == "null"
    assert field_signature(
        field("revenues"), {"applicability": {"revenue_expected": "no"}}
    ) == ('{"applicability":{"revenue_expected":"no"}}')
    assert field_signature(
        field("documentation_and_permits"), {"rows": {"x": {"1": "a", "b": "é"}}}
    ) == ('{"rows":{"x":{"1":"a","b":"é"}}}')


def test_worksheet_signature_includes_its_row_source() -> None:
    values = default_project_values()
    worksheet = field("investment_cost_estimate")
    context = worksheet_context(worksheet, values)

    assert context == [
        {
            "sectionId": "project_description_and_impact",
            "fieldId": "scope_of_the_project",
            "answer": values["scope_of_the_project"],
        }
    ]
    signature = field_signature(worksheet, values["investment_cost_estimate"], context)
    assert signature.startswith('{"answer":{"componentCosts":{"comp-design":')
    assert '"context":[{"sectionId":"project_description_and_impact",' in signature
    assert worksheet_context(field("revenues"), values) == []


# --- Readiness -------------------------------------------------------------------


def panel_ids() -> list[dict[str, str]]:
    return [store(ISSUES, field_id) for field_id in SERVER_DECIDED]


def panel_texts(panel: Component) -> list[Any]:
    return [c.children for c in walk(panel) if isinstance(c, html.P | html.Li)]


def test_readiness_runs_each_validator_once_and_redraws_requested_panels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    item = {"_rowId": "r1", "risk_factor": "Floods"}

    def fake_readiness(*args: Any) -> list[str]:
        calls.append(tuple(map(json.dumps, args)))
        return ["Item 1: Likelihood is required."]

    def never(*_args: Any) -> bool:
        raise AssertionError("a validator-backed kind is ready when it has no issues")

    monkeypatch.setattr(callbacks, "readiness", fake_readiness)
    monkeypatch.setattr(callbacks, "is_field_ready", never)

    panels, data = callbacks.check_readiness(
        {"project_risks": {"answer": [item], "context": None, "n": 3}}, panel_ids()
    )

    assert calls == [
        (
            '"project_management_and_risks"',
            '"project_risks"',
            json.dumps([item]),
            "null",
        )
    ]
    assert data == {
        "project_risks": {
            "ready": False,
            "issues": ["Item 1: Likelihood is required."],
            "n": 3,
        }
    }
    drawn = dict(zip(SERVER_DECIDED, panels, strict=True))
    assert all(drawn[f] is no_update for f in SERVER_DECIDED if f != "project_risks")
    assert panel_texts(drawn["project_risks"]) == [
        "Complete the following before evaluating:",
        "Item 1: Likelihood is required.",
    ]


def test_one_readiness_request_answers_every_owed_field() -> None:
    values = default_project_values()
    request = {f: request_for(f, values, n=1) for f in SERVER_DECIDED}
    request["project_risks"] = {
        "answer": [*values["project_risks"], {"_rowId": "new"}],
        "context": None,
        "n": 2,
    }
    request["investment_cost_estimate"]["context"] = None

    panels, data = callbacks.check_readiness(request, panel_ids())

    assert set(data) == set(SERVER_DECIDED)
    not_ready = {f for f, answer in data.items() if not answer["ready"]}
    assert not_ready == {"project_risks", "investment_cost_estimate"}
    assert data["project_risks"]["n"] == 2
    assert data["project_risks"]["issues"]
    drawn = dict(zip(SERVER_DECIDED, panels, strict=True))
    assert [f for f, panel in drawn.items() if panel is not None] == [
        "investment_cost_estimate",
        "project_risks",
    ]


def test_readiness_of_unknown_and_local_fields() -> None:
    _, data = callbacks.check_readiness(
        {
            "nope": {"answer": "", "n": 1},
            "project_title": {"answer": "  ", "n": 4},
            "objectives": {"answer": "Cut travel time.", "n": 5},
        },
        [],
    )

    assert data == {
        "nope": {"ready": False, "issues": ['Unknown field "nope".'], "n": 1},
        "project_title": {"ready": False, "issues": [], "n": 4},
        "objectives": {"ready": True, "issues": [], "n": 5},
    }


# --- Evaluation ------------------------------------------------------------------


Evaluated = list[tuple[Any, ...]]


@pytest.fixture
def evaluated(monkeypatch: pytest.MonkeyPatch) -> Evaluated:
    """The calls that reach the model, each answered with a Pass."""
    received: Evaluated = []

    async def fake_evaluate(
        section_id: str, field_id: str, answer: Any, context: Any = None
    ) -> FieldEvaluationResponse:
        received.append((section_id, field_id, answer, context))
        return FieldEvaluationResponse(
            ok=True,
            result=FieldEvaluation(verdict="pass", reasoning="Fine.", suggestions=[]),
            model="fake",
            section_id=section_id,
            field_id=field_id,
        )

    monkeypatch.setattr(callbacks, "evaluate_field", fake_evaluate)
    return received


def evaluate(field_id: str, request: Any, project: Any = None) -> dict[str, Any]:
    return asyncio.run(
        callbacks.evaluate(
            request, store(EVALUATE_REQUEST, field_id), project or {"id": "p-1"}
        )
    )


def test_evaluate_grades_the_requested_snapshot(evaluated: Evaluated) -> None:
    values = default_project_values()
    worksheet = "investment_cost_estimate"

    response = evaluate(worksheet, request_for(worksheet, values, n=2))

    assert evaluated == [
        (
            "estimated_investment_costs_and_financing",
            worksheet,
            values[worksheet],
            [
                {
                    "sectionId": "project_description_and_impact",
                    "fieldId": "scope_of_the_project",
                    "answer": values["scope_of_the_project"],
                }
            ],
        )
    ]
    assert response["ok"] is True
    assert response["result"]["verdict"] == "pass"
    assert response["n"] == 2
    assert "notReady" not in response


@pytest.mark.parametrize("answer", ["", "   ", None])
def test_a_blank_text_answer_reaches_no_model_call(
    evaluated: Evaluated, answer: Any
) -> None:
    request = {"n": 7} if answer is None else {"answer": answer, "n": 7}

    response = evaluate("project_location", request)

    assert evaluated == []
    assert response == {
        "ok": False,
        "sectionId": "investment_identification",
        "fieldId": "project_location",
        "errorMessage": NOT_READY,
        "issues": [],
        "retryable": False,
        "n": 7,
        "notReady": True,
    }


def test_an_incomplete_composite_is_refused_with_its_issues(
    evaluated: Evaluated,
) -> None:
    risks = default_project_values()["project_risks"]
    broken = [{**risks[0], "likelihood": ""}, *risks[1:]]

    response = evaluate("project_risks", {"answer": broken, "n": 3})

    assert evaluated == []
    assert response["notReady"] is True
    assert response["n"] == 3
    assert response["issues"] == readiness(
        "project_management_and_risks", "project_risks", broken
    )
    assert len(response["issues"]) == 1


def test_evaluate_reports_a_failure_as_a_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(*_args: Any) -> FieldEvaluationResponse:
        raise RuntimeError("boom")

    monkeypatch.setattr(callbacks, "evaluate_field", broken)

    response = evaluate("objectives", {"answer": "x", "n": 1})
    unknown = evaluate("nope", {"answer": "x", "n": 2})

    assert response["ok"] is False
    assert response["errorMessage"] == TRANSPORT_FAILURE
    assert response["retryable"] is True
    assert unknown["errorMessage"] == 'Unknown field "nope".'
    assert unknown["retryable"] is False
    assert unknown["n"] == 2


def peak_concurrency(
    monkeypatch: pytest.MonkeyPatch, project_of: Callable[[int], str]
) -> int:
    """How many model calls ran at once when seven ready fields were
    evaluated together, the i-th for project ``project_of(i)``."""
    running = 0
    peak = 0

    async def slow(*_args: Any) -> FieldEvaluationResponse:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.02)
        running -= 1
        return FieldEvaluationResponse(ok=False, error_message="x")

    monkeypatch.setattr(callbacks, "evaluate_field", slow)
    values = default_project_values()
    fields = list(EXPECTED_KINDS)[:7]

    async def run_all() -> None:
        await asyncio.gather(
            *(
                callbacks.evaluate(
                    request_for(f, values),
                    store(EVALUATE_REQUEST, f),
                    {"id": project_of(index)},
                )
                for index, f in enumerate(fields)
            )
        )

    asyncio.run(run_all())
    return peak


def test_one_project_runs_at_most_four_evaluations_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    peak = peak_concurrency(monkeypatch, lambda _index: "p")

    assert peak == callbacks.MAX_CONCURRENT_EVALUATIONS == 4


def test_the_process_caps_evaluations_across_projects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(callbacks, "_process_limit", asyncio.Semaphore(3))

    peak = peak_concurrency(monkeypatch, lambda index: f"p-{index}")

    assert peak == 3
    assert callbacks.MAX_PROCESS_EVALUATIONS > callbacks.MAX_CONCURRENT_EVALUATIONS
