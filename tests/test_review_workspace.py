"""The assessor workspace's Python side: the views and cards drawn from a
record's structure, every card state drawn from fixture records, the score
summary's three states with the calculator's numbers, the memo panel's
reasons and completion, the hub's progress, and the discipline that keeps
Dash from redrawing an ancestor of a control and keeps ids and text out of
review-ui.js. Behaviour in a browser is covered by
``tests/browser/test_review_workspace.py``."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from dash import Dash, dcc, html
from dash.development.base_component import Component

from pcn_clone.app.review.workspace import workspace_view
from pcn_clone.app.review.workspace.config import client_config
from pcn_clone.app.review.workspace.ids import (
    EDITOR,
    ITEM_FOOT,
    ITEM_TOP,
    MEMO,
    REGION,
    ROOT,
)
from pcn_clone.app.review.workspace.layout import workspace_body
from pcn_clone.app.review.workspace.render import (
    editor_regions,
    item_regions,
    memo_regions,
    read_progress,
    view_regions,
)
from pcn_clone.app.review.workspace.summary_state import (
    percent_text,
    select_mca_summary_state,
)
from pcn_clone.content.models import McaMatrix
from tests.app_helpers import walk
from tests.review_records import (
    blank_record,
    criterion_ids,
    dimension_ids,
    drafted_record,
    error_state,
    finding_state,
    score_state,
)

if TYPE_CHECKING:
    from starlette.testclient import TestClient

REVIEW_UI_JS = (
    Path(__file__).resolve().parents[1]
    / "pcn_clone"
    / "app"
    / "assets"
    / "review-ui.js"
).read_text(encoding="utf-8")

WILDCARDS = (["ALL"], ["MATCH"], ["ALLSMALLER"])

JS_OWNED = (
    "data-rv-input",
    "data-rv-list",
    "data-rv-prototype",
    "data-rv-note",
    "data-rv-field",
    "data-rv-add-form",
)
"""Attributes of the elements review-ui.js writes to directly (input slots,
citation lists and their prototypes, notes, editor fields, the
add-citation form)."""


# --- Helpers -------------------------------------------------------------------


def props(component: Component) -> dict[str, Any]:
    result: dict[str, Any] = component.to_plotly_json()["props"]
    return result


def text_of(node: Any) -> str:
    """The text a component tree renders, sr-only text included."""
    if isinstance(node, str):
        return node
    if isinstance(node, list | tuple):
        return "".join(text_of(child) for child in node)
    if isinstance(node, Component):
        return text_of(getattr(node, "children", None))
    return ""


def classes(node: Component) -> set[str]:
    return set(str(props(node).get("className", "")).split())


def with_class(tree: Any, name: str) -> list[Component]:
    return [node for node in walk(tree) if name in classes(node)]


def buttons(tree: Any) -> list[tuple[str, str | None, bool]]:
    """``(label, action, disabled)`` of every button in ``tree``."""
    return [
        (
            text_of(node),
            props(node).get("data-rv-action"),
            bool(props(node).get("disabled")),
        )
        for node in walk(tree)
        if isinstance(node, html.Button)
    ]


def actions(tree: Any) -> list[str]:
    return [action for _, action, disabled in buttons(tree) if action and not disabled]


def shape_of(record: dict[str, Any]) -> dict[str, Any]:
    """The structure review-ui.js publishes for ``record``."""
    return {
        "key": f"{record['id']}:test",
        "reviewId": record["id"],
        "dimensionDefs": [
            {key: d[key] for key in ("id", "label", "description")}
            for d in record["dimensionDefs"]
        ],
        "mca": {"matrix": record["mca"]["matrix"]},
    }


def progress_of(
    record: dict[str, Any], memo: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The snapshot review-ui.js publishes, asking for every card."""
    return {
        "dimensionDefs": shape_of(record)["dimensionDefs"],
        "dimensions": record["dimensions"],
        "mca": {
            "matrix": record["mca"]["matrix"],
            "criteria": record["mca"]["criteria"],
        },
        "fields": record["fields"],
        "render": {
            "dimension": {item: f"k-{item}" for item in dimension_ids(record)},
            "criterion": {item: f"k-{item}" for item in criterion_ids(record)},
        },
        "memo": memo,
        "summary": True,
    }


def finding_regions(record: dict[str, Any], index: int = 0) -> tuple[Any, Any]:
    regions = item_regions(
        read_progress(progress_of(record)), "dimension", dimension_ids(record)[index]
    )
    assert regions is not None
    return regions


def score_regions(record: dict[str, Any], index: int = 0) -> tuple[Any, Any]:
    regions = item_regions(
        read_progress(progress_of(record)), "criterion", criterion_ids(record)[index]
    )
    assert regions is not None
    return regions


def editing_of(record: dict[str, Any]) -> dict[str, Any]:
    """The request review-ui.js sends to draw every editor of ``record``."""
    criteria = {c["id"]: c for c in record["mca"]["matrix"]["criteria"]}
    return {
        "draw": [
            {"kind": "dimension", "item": d["id"], "definition": d}
            for d in shape_of(record)["dimensionDefs"]
        ]
        + [
            {
                "kind": "criterion",
                "item": item,
                "criterion": criteria[item],
                "state": record["mca"]["criteria"][item],
            }
            for item in criterion_ids(record)
        ],
        "clear": [],
        "scale": record["mca"]["matrix"]["scale"],
        "fields": record["fields"],
    }


def score_editor_of(record: dict[str, Any], index: int = 0) -> Any:
    editors = editor_regions(editing_of(record))
    return editors[("criterion", criterion_ids(record)[index])]


@pytest.fixture(scope="module")
def body(app: Dash) -> html.Div:
    """Every view for the default project's review, within the session's
    app."""
    return workspace_body(shape_of(blank_record()))


# --- Views and cards -------------------------------------------------------------


def test_the_view_mounts_its_stores_and_an_empty_root(app: Dash) -> None:
    view = workspace_view()
    stores = [c for c in view if isinstance(c, dcc.Store)]
    assert {s.id for s in stores} == {
        "rv-ws-config",
        "rv-ws-shape",
        "rv-ws-progress",
        "rv-ws-editing",
    }
    root = view[-1]
    assert root.id == ROOT
    assert getattr(root, "children", None) is None


def test_the_body_draws_the_hub_and_both_components(body: html.Div) -> None:
    record = blank_record()
    assert props(body)["data-rv-shape"] == "rv-test:test"
    assert len(with_class(body, "rv-view-hub")) == 1
    findings = with_class(body, "rv-view-findings")[0]
    scores = with_class(body, "rv-view-scores")[0]
    finding_cards = [
        props(c)["data-rv-card"] for c in walk(findings) if "data-rv-card" in props(c)
    ]
    score_cards = [
        props(c)["data-rv-card"] for c in walk(scores) if "data-rv-card" in props(c)
    ]
    assert finding_cards == dimension_ids(record)
    assert score_cards == criterion_ids(record)
    region_ids = [
        node.id
        for node in walk(body)
        if isinstance(getattr(node, "id", None), dict) and node.id.get("type") == REGION
    ]
    assert {(r["view"], r["slot"]) for r in region_ids} == {
        ("findings", "hub"),
        ("findings", "trail"),
        ("findings", "aside"),
        ("scores", "hub"),
        ("scores", "trail"),
        ("scores", "aside"),
        ("scores", "summary"),
    }
    assert "5 qualitative dimensions evaluated for your review" in text_of(findings)
    assert "4 weighted criteria scored 1–5 against their descriptors" in text_of(scores)


def test_each_hub_card_is_a_lasting_button_around_its_live_region(
    body: html.Div,
) -> None:
    """The cards' content is redrawn as states change; the buttons are not,
    so a keyboard user's focus on one survives every redraw."""
    cards = [
        n
        for n in walk(body)
        if isinstance(n, html.Button) and "data-rv-open" in props(n)
    ]
    assert [(props(c)["data-rv-open"], props(c)["aria-label"]) for c in cards] == [
        ("findings", "Open Assessment findings"),
        ("scores", "Open Prioritisation scoring"),
    ]
    for card in cards:
        (region,) = [n for n in walk(card) if getattr(n, "id", None) is not None]
        assert region.id == {
            "type": REGION,
            "view": props(card)["data-rv-open"],
            "slot": "hub",
        }


def test_ids_are_unique(body: html.Div) -> None:
    every_editor = list(editor_regions(editing_of(drafted_record())).values())
    tree = [body, *every_editor]
    ids = [
        json.dumps(node.id, sort_keys=True)
        for node in walk(tree)
        if getattr(node, "id", None) is not None
    ]
    slot_ids = [
        json.loads(props(node)["data-rv-input"]).get("id")
        for node in walk(tree)
        if "data-rv-input" in props(node)
    ]
    every = ids + [json.dumps(i) for i in slot_ids if i]
    assert [i for i, n in Counter(every).items() if n > 1] == []


def test_the_editors_offer_every_choice_and_the_field_snapshot() -> None:
    record = drafted_record()
    body = list(editor_regions(editing_of(record)).values())
    radios = Counter(
        (
            json.loads(props(node)["data-rv-input"])["name"].rsplit("-", 1)[1],
            json.loads(props(node)["data-rv-input"])["value"],
        )
        for node in walk(body)
        if "data-rv-input" in props(node)
        and json.loads(props(node)["data-rv-input"])["type"] == "radio"
    )
    assert radios[("verdict", "fail")] == 5
    assert radios[("score", "5")] == 4
    assert radios[("basis", "not_evidenced")] == 4
    groups = [props(n) for n in walk(body) if props(n).get("role") == "radiogroup"]
    assert Counter(g["aria-label"] for g in groups) == {
        "Final verdict": 5,
        "Endorsed score": 4,
        "Basis": 4,
    }
    pickers = [n for n in walk(body) if isinstance(n, html.Select)]
    assert len(pickers) == 9
    first = pickers[0].children
    assert len(first) == len(record["fields"])
    field = record["fields"][0]
    assert text_of(first[0]) == f"{field['sectionLabel']} — {field['fieldLabel']}"


def test_every_card_frame_holds_a_note_and_an_empty_editor_slot(
    body: html.Div,
) -> None:
    cards = [n for n in walk(body) if "data-rv-card" in props(n)]
    assert len(cards) == 9
    for card in cards:
        assert len(with_class(card, "rv-note")) == 1
        (slot,) = with_class(card, "rv-card-edit-slot")
        assert slot.id["type"] == EDITOR
        assert getattr(slot, "children", None) is None


def test_editors_are_drawn_and_cleared_only_as_asked() -> None:
    record = drafted_record()
    first, second = dimension_ids(record)[:2]
    request = editing_of(record)
    request["draw"] = request["draw"][:1]
    request["clear"] = [{"kind": "dimension", "item": second}]
    regions = editor_regions(request)
    assert set(regions) == {("dimension", first), ("dimension", second)}
    assert regions[("dimension", second)] is None
    editor = regions[("dimension", first)]
    assert props(editor)["data-rv-editor"] == "dimension"
    assert [action for _, action, _ in buttons(editor)][-2:] == [
        "save-edit",
        "cancel-edit",
    ]


def _fits(pattern: Any, component_id: Any) -> bool:
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
    references: list[str] = []
    for dependency in client.get("/_dash-dependencies").json():
        output = dependency["output"]
        if not dependency["no_output"]:
            references += (
                output[2:-2].split("...") if output.startswith("..") else [output]
            )
    outputs = []
    for reference in references:
        raw = reference.split("@", 1)[0].rsplit(".", 1)[0]
        outputs.append(json.loads(raw) if raw.startswith("{") else raw)
    return outputs


def test_nothing_redraws_an_ancestor_of_a_control(
    body: html.Div, client: TestClient
) -> None:
    """review-ui.js creates inputs in slots, draws citation rows and owns
    the notes, editor fields and summary; a component a callback redraws
    holds none of them. (An editor slot holds its form only while the editor
    is open, and is never redrawn meanwhile: see
    ``test_editors_are_drawn_and_cleared_only_as_asked``.)"""
    outputs = callback_outputs(client)
    targets = [
        node
        for node in walk(body)
        if getattr(node, "id", None) is not None
        and any(_fits(output, node.id) for output in outputs)
    ]
    owners = [
        (node.id, attribute)
        for target in targets
        for node in list(walk(target))[1:]
        for attribute in JS_OWNED
        if attribute in props(node)
    ]
    controls = [
        target.id
        for target in targets
        for node in list(walk(target))[1:]
        if isinstance(node, html.Textarea | html.Select)
    ]
    assert {t.id["type"] for t in targets if isinstance(t.id, dict)} == {
        ITEM_TOP,
        ITEM_FOOT,
        REGION,
        MEMO,
        EDITOR,
    }
    assert owners == []
    assert controls == []


# --- Finding cards -----------------------------------------------------------------


def test_a_drafting_finding_shows_its_skeleton_and_a_disabled_strip() -> None:
    top, foot = finding_regions(blank_record())
    assert props(top)["data-rv-status"] == "pending"
    assert props(top)["data-rv-key"] == f"k-{dimension_ids(blank_record())[0]}"
    assert "Drafting verdict" in text_of(top)
    assert with_class(top, "rv-sk-lines")
    assert "Locating citations in the submitted answers" in text_of(top)
    assert [(label, disabled) for label, _, disabled in buttons(top)] == [
        ("Accept", True),
        ("Edit…", True),
        ("Dismiss", True),
    ]
    assert actions(top) == []
    assert foot is None


def test_a_retryable_failure_offers_retry() -> None:
    record = blank_record()
    record["dimensions"][dimension_ids(record)[0]] = error_state(retryable=True)
    top, foot = finding_regions(record)
    assert props(top)["data-rv-status"] == "error"
    assert "Failed" in text_of(top)
    assert "The retryable failure's own message." in text_of(top)
    assert actions(top) == ["retry"]
    assert foot is None


@pytest.mark.parametrize(
    ("code", "explanation"),
    [
        ("model_mismatch", "This dimension can no longer be assessed"),
        ("invalid_result", "internally inconsistent and was not kept"),
    ],
)
def test_a_terminal_failure_explains_itself_without_retry(
    code: str, explanation: str
) -> None:
    record = blank_record()
    record["dimensions"][dimension_ids(record)[0]] = error_state(False, code)
    top, _ = finding_regions(record)
    assert explanation in text_of(top)
    assert "The terminal failure's own message." in text_of(top)
    assert actions(top) == []


def test_an_undecided_finding_reads_and_offers_the_three_decisions() -> None:
    record = drafted_record()
    first = dimension_ids(record)[0]
    record["dimensions"][first] = finding_state(
        record, first, "notClear", questions=("Is it costed?", "By whom?")
    )
    top, foot = finding_regions(record)
    pills = with_class(top, "pill")
    assert [text_of(p) for p in pills] == ["Concerns"]
    assert "pill-nc" in classes(pills[0])
    assert f"Drafted reasoning for {first}." in text_of(top)
    tray = with_class(top, "rv-tray")[0]
    assert "2 citations" in text_of(tray)
    citations = with_class(tray, "rv-citation")
    assert len(citations) == 2
    assert "Quote verified" in text_of(citations[0])
    assert "View the answer as assessed" in text_of(citations[0])
    field = record["fields"][0]
    assert field["serializedText"] in text_of(citations[0])
    assert f"{field['sectionLabel']} — {field['fieldLabel']}" in text_of(citations[0])
    assert "Questions for the proposer" in text_of(top)
    assert "Is it costed?" in text_of(top)
    assert "Your decision" in text_of(foot)
    assert actions(foot) == ["accept", "edit", "dismiss"]


def test_an_unverified_quote_says_so() -> None:
    record = drafted_record()
    first = dimension_ids(record)[0]
    record["dimensions"][first]["finding"]["evidence"][0]["verified"] = False
    top, _ = finding_regions(record)
    assert "Quote not found verbatim" in text_of(top)


def test_an_accepted_finding_keeps_the_draft_and_offers_note_and_change() -> None:
    record = drafted_record()
    first = dimension_ids(record)[0]
    record["dimensions"][first]["disposition"] = {"kind": "accepted"}
    top, foot = finding_regions(record)
    assert [text_of(p) for p in with_class(top, "pill")] == ["Adequate"]
    assert "Accepted as drafted" in text_of(foot)
    assert actions(foot) == ["add-note", "change"]


def test_a_decision_with_a_note_drops_add_note() -> None:
    record = drafted_record()
    first = dimension_ids(record)[0]
    record["dimensions"][first]["disposition"] = {"kind": "accepted", "note": "Fair."}
    _, foot = finding_regions(record)
    assert actions(foot) == ["change"]


def test_an_edited_finding_shows_the_reviewers_version() -> None:
    record = drafted_record()
    first = dimension_ids(record)[0]
    second_field = record["fields"][2]
    record["dimensions"][first]["disposition"] = {
        "kind": "edited",
        "finalVerdict": "fail",
        "finalText": "The reviewer's own finding.",
        "evidence": [
            {
                "sectionId": second_field["sectionId"],
                "fieldId": second_field["fieldId"],
                "quote": "an excerpt",
                "note": "why it matters",
            }
        ],
    }
    top, foot = finding_regions(record)
    assert [text_of(p) for p in with_class(top, "pill")] == ["Inadequate"]
    assert "The reviewer's own finding." in text_of(top)
    assert "Drafted reasoning" not in text_of(top)
    assert "1 citation" in text_of(top)
    curated = with_class(top, "rv-curated")[0]
    assert text_of(curated) == (
        f"{second_field['sectionLabel']} — {second_field['fieldLabel']}"
        "“an excerpt”Note: why it matters"
    )
    assert not with_class(top, "rv-quote-status")
    assert "Edited by you" in text_of(foot)
    assert actions(foot) == ["add-note", "edit", "change"]


def test_a_dismissed_finding_says_it_is_not_in_the_memo() -> None:
    record = drafted_record()
    first = dimension_ids(record)[0]
    record["dimensions"][first]["disposition"] = {"kind": "dismissed"}
    _, foot = finding_regions(record)
    assert "Dismissed — not in the memo" in text_of(foot)
    assert with_class(foot, "is-dismissed")
    assert actions(foot) == ["add-note", "change"]


# --- Score cards -------------------------------------------------------------------


def test_a_drafting_score_shows_its_weight_and_a_disabled_strip() -> None:
    record = blank_record()
    top, foot = score_regions(record)
    assert props(top)["data-rv-status"] == "pending"
    assert "weight 30" in text_of(top)
    assert "Drafting score" in text_of(top)
    assert [(label, disabled) for label, _, disabled in buttons(top)] == [
        ("Accept score", True),
        ("Adjust…", True),
    ]
    assert foot is None


def test_an_undecided_score_argues_its_draft() -> None:
    record = drafted_record()
    top, foot = score_regions(record)
    pill = with_class(top, "rv-score-pill")[0]
    assert text_of(pill) == "4High"
    assert "Why this score" in text_of(top)
    assert "1 citation" in text_of(top)
    guide = with_class(top, "rv-guide-tray")[0]
    assert "All 5 descriptors for this criterion" in text_of(guide)
    rows = with_class(guide, "rv-guide-row")
    assert len(rows) == 5
    assert [i for i, row in enumerate(rows) if "is-current" in classes(row)] == [3]
    assert actions(foot) == ["accept", "edit"]
    reference = with_class(score_editor_of(record), "rv-item-ref")[0]
    assert "1 citation" in text_of(reference)


def test_an_accepted_score_names_the_draft_it_endorses() -> None:
    record = drafted_record()
    first = criterion_ids(record)[0]
    record["mca"]["criteria"][first]["disposition"] = {"kind": "accepted"}
    _, foot = score_regions(record)
    assert "Accepted as drafted — 4 (High)" in text_of(foot)
    assert actions(foot) == ["add-note", "edit", "change"]
    assert [label for label, _, _ in buttons(foot)] == ["Add note", "Adjust…", "Change"]


def test_an_adjusted_score_shows_the_reviewers_score_and_basis() -> None:
    record = drafted_record()
    first = criterion_ids(record)[0]
    field = record["fields"][5]
    record["mca"]["criteria"][first]["disposition"] = {
        "kind": "adjusted",
        "finalScore": 2,
        "rationale": "Weaker than drafted.",
        "basis": {
            "kind": "documented",
            "evidence": [
                {"sectionId": field["sectionId"], "fieldId": field["fieldId"]}
            ],
        },
    }
    top, foot = score_regions(record)
    assert text_of(with_class(top, "rv-score-pill")[0]) == "2Low"
    assert "Your justification" in text_of(top)
    assert "Weaker than drafted." in text_of(top)
    assert "Drafted justification" not in text_of(top)
    assert text_of(with_class(top, "rv-curated")[0]) == (
        f"{field['sectionLabel']} — {field['fieldLabel']}"
    )
    rows = with_class(top, "rv-guide-row")
    assert [i for i, row in enumerate(rows) if "is-current" in classes(row)] == [1]
    assert "Adjusted by you — 2 (Low) replaces the AI's draft of 4" in text_of(foot)
    assert [label for label, _, _ in buttons(foot)] == ["Adjust again", "Change"]


def test_a_score_on_absent_evidence_is_badged() -> None:
    record = drafted_record()
    first = criterion_ids(record)[0]
    record["mca"]["criteria"][first] = score_state(record, first, 1, citations=())
    top, _ = score_regions(record)
    assert "Scored on absent evidence" in text_of(top)
    assert not with_class(top, "rv-tray-body") or "Evidence" not in text_of(
        with_class(top, "rv-tray")[0]
    )
    reference = with_class(score_editor_of(record), "rv-item-ref")[0]
    assert "Scored on absent evidence" in text_of(reference)


def test_an_adjustment_to_the_floor_not_evidenced_owns_its_basis() -> None:
    record = drafted_record()
    first = criterion_ids(record)[0]
    record["mca"]["criteria"][first]["disposition"] = {
        "kind": "adjusted",
        "finalScore": 1,
        "rationale": "Nothing in the submission supports urgency.",
        "basis": {"kind": "not_evidenced"},
    }
    top, foot = score_regions(record)
    assert text_of(with_class(top, "rv-score-pill")[0]) == "1Very low"
    assert "Scored on absent evidence" in text_of(top)
    assert "Adjusted by you — 1 (Very low) replaces the AI's draft of 4" in text_of(
        foot
    )


def test_a_failed_score_follows_the_error_taxonomy() -> None:
    record = blank_record()
    first = criterion_ids(record)[0]
    record["mca"]["criteria"][first] = error_state(retryable=True)
    top, _ = score_regions(record)
    assert actions(top) == ["retry"]
    record["mca"]["criteria"][first] = error_state(False, "invalid_result")
    top, _ = score_regions(record)
    assert "The score returned for this criterion was internally inconsistent" in (
        text_of(top)
    )
    assert actions(top) == []


def test_only_requested_cards_are_drawn() -> None:
    record = drafted_record()
    payload = progress_of(record)
    payload["render"] = {"dimension": {dimension_ids(record)[1]: "k"}}
    progress = read_progress(payload)
    assert item_regions(progress, "dimension", dimension_ids(record)[0]) is None
    assert item_regions(progress, "dimension", dimension_ids(record)[1]) is not None
    assert item_regions(progress, "criterion", criterion_ids(record)[0]) is None


# --- Components on the hub -----------------------------------------------------------


def test_the_hub_meters_drafts_while_the_run_streams() -> None:
    record = blank_record()
    first = dimension_ids(record)[0]
    record["dimensions"][first] = finding_state(record, first, "pass")
    regions = view_regions(read_progress(progress_of(record)))
    hub = regions[("findings", "hub")]
    assert "is-loading" in classes(hub)
    assert "4 of 5 still drafting" in text_of(hub)
    assert with_class(hub, "rv-meter-fill")[0].style == {"width": "20%"}
    assert "is-loading" in classes(with_class(hub, "rv-meter-fill")[0])
    assert "1 of 5 drafted" in text_of(hub)
    assert "Review as they arrive" in text_of(hub)
    assert len(with_class(hub, "rv-drafting-pill")) == 1 + 4
    assert text_of(regions[("findings", "trail")]) == "1 of 5 drafted"
    assert "4 of 5 still drafting" in text_of(regions[("findings", "aside")])
    scores = regions[("scores", "hub")]
    assert "Open component" in text_of(scores)
    assert not with_class(scores, "rv-band-pill")


def test_the_hub_counts_decisions_with_ticks_and_the_band() -> None:
    record = drafted_record()
    first = dimension_ids(record)[0]
    record["dimensions"][first]["disposition"] = {"kind": "dismissed"}
    regions = view_regions(read_progress(progress_of(record)))
    hub = regions[("findings", "hub")]
    assert "is-loading" not in classes(hub)
    assert "1 of 5 decided" in text_of(hub)
    assert "Review findings" in text_of(hub)
    items = with_class(hub, "rv-hub-item")
    assert ["Decided" in text_of(item) for item in items] == [True] + [False] * 4
    assert [text_of(p) for p in with_class(hub, "pill")] == [
        "Adequate",
        "Concerns",
        "Adequate",
        "Inadequate",
        "Adequate",
    ]
    scores = regions[("scores", "hub")]
    assert text_of(with_class(scores, "rv-band-pill")[0]) == "Medium priority"
    assert "0 of 4 endorsed" in text_of(scores)
    assert [text_of(p) for p in with_class(scores, "rv-score-pill")] == [
        "4High",
        "2Low",
        "4High",
        "3Moderate",
    ]
    assert text_of(regions[("scores", "aside")]) == "Medium priority"


def test_every_decision_made_invites_a_revisit() -> None:
    record = drafted_record()
    for item in dimension_ids(record):
        record["dimensions"][item]["disposition"] = {"kind": "accepted"}
    hub = view_regions(read_progress(progress_of(record)))[("findings", "hub")]
    assert "Revisit findings" in text_of(hub)
    assert with_class(hub, "rv-meter-fill")[0].style == {"width": "100%"}


# --- The score summary ----------------------------------------------------------------


def summary_of(record: dict[str, Any]) -> Component:
    region = view_regions(read_progress(progress_of(record)))[("scores", "summary")]
    assert region is not None
    return region


def test_the_summary_is_drawn_once_the_scores_view_has_opened() -> None:
    payload = progress_of(drafted_record())
    payload["summary"] = False
    regions = view_regions(read_progress(payload))
    assert ("scores", "summary") not in regions
    assert ("scores", "hub") in regions


def test_the_summary_shows_its_shell_while_scores_draft() -> None:
    record = drafted_record()
    record["mca"]["criteria"][criterion_ids(record)[3]] = {
        "status": "pending",
        "generation": 1,
    }
    record["mca"]["criteria"][criterion_ids(record)[2]] = error_state(retryable=True)
    summary = summary_of(record)
    assert "is-pending" in classes(summary)
    assert "2 of 4 scores in" in text_of(summary)
    cells = [text_of(td) for td in walk(summary) if isinstance(td, html.Td)]
    assert cells[:3] == ["30", "4", "—"]
    assert "Failed to score" in text_of(summary)
    assert "Still drafting" in text_of(summary)
    assert "No band yet" in text_of(summary)
    assert "2 of 4 have returned." in text_of(summary)
    assert not with_class(summary, "rv-gauge-fill")
    ticks = [text_of(t) for t in with_class(summary, "rv-gauge-label")]
    assert ticks == ["High 80", "Medium 60"]


def test_a_provisional_summary_carries_the_calculators_numbers() -> None:
    record = drafted_record()
    first = criterion_ids(record)[0]
    record["mca"]["criteria"][first]["disposition"] = {"kind": "accepted"}
    summary = summary_of(record)
    selected = select_mca_summary_state(
        McaMatrix.model_validate(record["mca"]["matrix"]), record["mca"]["criteria"]
    )
    assert selected.summary is not None
    assert "Provisional" in text_of(summary)
    totals = [text_of(td) for td in with_class(summary, "is-total")]
    # Scores 4, 2, 4, 3 at weights 30, 30, 20, 20: 320 of 500, 64%.
    assert totals == ["320 / 500", "64.0%"]
    assert totals[1] == percent_text(selected.summary.percent_of_maximum)
    assert "Accepted" in text_of(summary)
    assert text_of(summary).count("Drafted — awaiting your decision") == 3
    assert text_of(with_class(summary, "rv-band-pill")[0]) == "Medium priority"
    assert with_class(summary, "rv-gauge-fill")[0].style == {"width": "64%"}
    assert "it becomes final when every score carries your decision" in text_of(summary)


def test_a_final_summary_is_endorsed() -> None:
    record = drafted_record()
    ids = criterion_ids(record)
    for item in ids:
        record["mca"]["criteria"][item]["disposition"] = {"kind": "accepted"}
    record["mca"]["criteria"][ids[0]]["disposition"] = {
        "kind": "adjusted",
        "finalScore": 5,
        "rationale": "Immediate.",
        "basis": {
            "kind": "documented",
            "evidence": [{"sectionId": "a", "fieldId": "b"}],
        },
    }
    summary = summary_of(record)
    assert "Endorsed" in text_of(summary)
    assert "Adjusted by you" in text_of(summary)
    totals = [text_of(td) for td in with_class(summary, "is-total")]
    # 5×30 + 2×30 + 4×20 + 3×20 = 350 of 500.
    assert totals == ["350 / 500", "70.0%"]
    assert "this is the score the memo carries" in text_of(summary)


# --- The memo panel ---------------------------------------------------------


def test_the_memo_panel_speaks_of_completion_not_export(body: html.Div) -> None:
    memo = with_class(body, "rv-memo")[0]
    text = text_of(memo)
    assert "Your written review of the submitted PCN." in text
    assert "Assessment readiness" in text
    assert "export" not in text.lower()
    assert "Memo readiness" not in text


def test_the_locked_memo_counts_sections_in() -> None:
    record = blank_record()
    first = dimension_ids(record)[0]
    record["dimensions"][first] = finding_state(record, first)
    count, readiness = memo_regions(read_progress(progress_of(record)))
    assert count == "1 of 9 sections in."
    assert readiness == []


def test_the_memo_lists_every_blocking_reason() -> None:
    reasons = [
        "5 findings await your decision.",
        "The reviewer summary has not been written yet.",
    ]
    _, readiness = memo_regions(
        read_progress(
            progress_of(drafted_record(), {"ready": False, "reasons": reasons})
        )
    )
    assert [text_of(li) for li in walk(readiness) if isinstance(li, html.Li)] == reasons


def test_a_complete_review_states_what_stands() -> None:
    record = drafted_record()
    for index, item in enumerate(dimension_ids(record)):
        kind = "dismissed" if index == 4 else "accepted"
        record["dimensions"][item]["disposition"] = {"kind": kind}
    for item in criterion_ids(record):
        record["mca"]["criteria"][item]["disposition"] = {"kind": "accepted"}
    _, readiness = memo_regions(
        read_progress(progress_of(record, {"ready": True, "reasons": []}))
    )
    text = text_of(readiness)
    assert "Every finding is decided, every criterion score endorsed" in text
    assert (
        "Assessment complete: 4 findings endorsed, 1 dismissed; final "
        "prioritisation score 64.0% — Medium priority."
    ) in text


# --- The browser's configuration --------------------------------------------


def test_review_ui_js_takes_ids_and_text_from_the_config() -> None:
    literal_ids = [
        r"getElementById\(\s*[\"'`]",
        r"\bsetProps\(\s*[\"'`]",
        r"\bsetPropsOnce\(\s*[^,]+,\s*[\"'`]",
        r"[\"']rv-(ws|part|record|summary|completion)",
        r"[\"'`]#[\w-]",
        r"window\.pcnReview\b",
        r"window\[\s*[\"'`]",
    ]
    assert [p for p in literal_ids if re.search(p, REVIEW_UI_JS)] == []
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", REVIEW_UI_JS, flags=re.DOTALL)
    literals = "\n".join(re.findall(r"\"[^\"\n]*\"|'[^'\n]*'|`[^`]*`", code))
    config = client_config()
    for name, message in config["messages"].items():
        for fragment in re.split(r"\{\w+\}", message):
            if len(fragment) > 3:
                assert fragment not in literals, (name, fragment)
    assert config["viewOfKind"] == {"dimension": "findings", "criterion": "scores"}
    assert config["ids"]["view"] == "rv-part"
