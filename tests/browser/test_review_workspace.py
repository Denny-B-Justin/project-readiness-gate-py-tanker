"""The assessor workspace in a real browser, against the offline fake
provider with one second of latency per call: a submitted review's cards
fill live without the page being redrawn; findings are accepted, edited
(verdict, text and curated evidence) and dismissed; scores are accepted and
adjusted to the floor as not evidenced; the score summary moves from its
pending shell through provisional to final with the calculator's numbers;
the summary completes the review; every decision survives a reload; a
stale write is refused; the choosers and disclosures work from the
keyboard; Retry relaunches a failed card; the phone width never scrolls
sideways; and review-ui.js moves the adjustment draft as adjust_draft.py
does."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from pcn_clone.app.review.completion import completion, status_line
from pcn_clone.app.review.workspace.summary_state import (
    percent_text,
    select_mca_summary_state,
)
from pcn_clone.content import load_assessment, load_mca
from pcn_clone.content.models import McaMatrix
from pcn_clone.core.jsstr import number_to_string
from tests.browser.form_steps import open_default
from tests.browser.harness import AppServer, Chrome, Page, url_param
from tests.browser.review_steps import ON_REVIEW_URL
from tests.oracles.adjust_draft import (
    adjust_draft_issues,
    can_save_adjust_draft,
    initial_adjust_draft,
    to_adjusted_disposition,
    with_basis_kind,
    with_score,
)
from tests.review_records import (
    drafted_record,
    error_state,
)

DIMENSIONS = [d.id for d in load_assessment().dimensions]
CRITERIA = [c.id for c in load_mca().matrix.criteria]

TEST_HOOKS = "window.pcnTestHooks = true;"
"""Run before every document's scripts: review-ui.js then exposes
``window.pcnReviewUi`` (the adjustment transitions and the open editors'
drafts)."""

SETTLE = 30
"""Seconds a state may take to settle when the machine is under load."""

ALL_LANDED = (
    "(() => { const r = window.pcnReview && window.pcnReview.record();"
    " if (!r) return false;"
    " const states = Object.values(r.dimensions).concat(Object.values(r.mca.criteria));"
    " return states.every((s) => s.status !== 'pending'); })()"
)

SEEN = """(() => {
  window.__seen = new Set();
  const seen = window.__seen;
  const look = () => {
    for (const top of document.querySelectorAll('.rv-item-top > [data-rv-status]')) {
      const card = top.closest('[data-rv-card]').id;
      seen.add(card + ':' + top.getAttribute('data-rv-status'));
    }
    const hub = document.querySelector('[data-rv-open=findings]');
    if (hub && hub.textContent.includes('still drafting')) seen.add('hub:drafting');
    if (document.querySelector('.rv-summary.is-pending')) seen.add('summary:pending');
    if (document.querySelector('.rv-root[data-rv-drafting] .rv-memo-locked')) {
      seen.add('memo:locked');
    }
  };
  new MutationObserver(look).observe(document.body, {subtree: true, childList: true});
  look();
  return true;
})()"""
"""Records, from now on, every (card, status) pair the page shows and
whether it showed the hub drafting, the score summary's pending shell and
the locked memo panel."""

SHOWING = "document.querySelector('.rv-root').getAttribute('data-rv-showing')"
"""The opened component, or ``""`` on the hub."""

ALL_DRAWN = (
    "document.querySelectorAll('.rv-item-top > [data-rv-status=ok]').length === 9"
)
"""Every card shows its drafted state."""


@pytest.fixture(scope="module")
def workspace_server(
    chrome_binary: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[AppServer]:
    server = AppServer(
        tmp_path_factory.mktemp("workspace") / "uvicorn.log",
        {"PCN_AI_FAKE_DELAY_SECONDS": "1"},
    )
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="module")
def failing_server(
    chrome_binary: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[AppServer]:
    server = AppServer(
        tmp_path_factory.mktemp("failing") / "uvicorn.log",
        {"PCN_AI_FAKE_DELAY_SECONDS": "1", "PCN_AI_FAKE_FAIL": "cost_realism"},
    )
    server.start()
    yield server
    server.stop()


def _tab(chrome: Chrome, server: AppServer) -> Iterator[Page]:
    page = chrome.new_page(server.url)
    page.send("Page.addScriptToEvaluateOnNewDocument", {"source": TEST_HOOKS})
    page.goto("/?page=projects", ready="!!window.pcnStore")
    page.js("localStorage.clear(); sessionStorage.clear(); true")
    yield page
    errors = page.errors()
    page.close()
    assert errors == [], errors


@pytest.fixture
def tab(chrome: Chrome, workspace_server: AppServer) -> Iterator[Page]:
    """A fresh tab on the workspace server with empty storage; the test
    fails on any console error or uncaught exception."""
    yield from _tab(chrome, workspace_server)


@pytest.fixture
def failing_tab(chrome: Chrome, failing_server: AppServer) -> Iterator[Page]:
    yield from _tab(chrome, failing_server)


# --- Steps -------------------------------------------------------------------------


def submit_default(page: Page) -> str:
    """Submit the default project; return the review id once its workspace
    is drawn, with every card's status recorded from then on."""
    open_default(page)
    page.click("#pf-submit")
    page.wait_for(ON_REVIEW_URL, timeout=SETTLE)
    page.js(SEEN)
    page.wait_for("!!document.querySelector('.rv-workspace')", timeout=SETTLE)
    return str(page.js(url_param("review_id")))


def stored(page: Page, review_id: str) -> dict[str, Any]:
    record: dict[str, Any] = page.js(
        f"JSON.parse(localStorage.getItem('pcn:review:{review_id}'))"
    )
    return record


def element(selector: str) -> str:
    """A page expression for the first match of ``selector``."""
    return f"document.querySelector({json.dumps(selector)})"


def focus(page: Page, selector: str) -> None:
    page.js(f"{element(selector)}.focus(); true")


def text(page: Page, selector: str) -> str:
    return str(
        page.js(
            f"(document.querySelector({json.dumps(selector)}) || {{}}).innerText || ''"
        )
    )


def texts(page: Page, selector: str) -> list[str]:
    nodes = f"[...document.querySelectorAll({json.dumps(selector)})]"
    found: list[str] = page.js(f"{nodes}.map((n) => n.innerText)")
    return found


def replace_text(page: Page, selector: str, value: str) -> None:
    """Select a text control's content and type ``value`` over it."""
    page.js(f"document.querySelector({json.dumps(selector)}).select(); true")
    page.type(selector, value)


def key(page: Page, name: str) -> None:
    """Press a navigation key the harness's ``press`` does not cover."""
    codes = {"ArrowLeft": 37, "ArrowRight": 39, "ArrowDown": 40}
    event = {"key": name, "code": name, "windowsVirtualKeyCode": codes[name]}
    page.send("Input.dispatchKeyEvent", {"type": "rawKeyDown", **event})
    page.send("Input.dispatchKeyEvent", {"type": "keyUp", **event})


def activate(page: Page, selector: str) -> None:
    """Press Enter on a control: no pointer, so a layout shift while the
    page redraws cannot make it miss."""
    focus(page, selector)
    page.press("Enter")


def open_part(page: Page, part: str) -> None:
    activate(page, f"[data-rv-open={part}]")
    page.wait_for(f"{SHOWING} === '{part}' && window.scrollY === 0", timeout=SETTLE)


def back_to_hub(page: Page) -> None:
    activate(page, f".rv-view-{page.js(SHOWING)} [data-rv-close]")
    page.wait_for(f"{SHOWING} === ''", timeout=SETTLE)


def draft_of(page: Page, kind: str, item: str) -> Any:
    """The open editor's draft for an item, through the test hooks."""
    return page.js(f"window.pcnReviewUi.editor('{kind}', '{item}')")


def open_editor(page: Page, card: str) -> None:
    """Open a card's editor once the card is drawn, and wait until its form
    is drawn and filled."""
    edit = f"{card} .rv-item-foot [data-rv-action=edit]"
    page.wait_for(f"!!{element(edit)}", timeout=SETTLE)
    page.click(edit)
    wait_editor(page, card)


def wait_editor(page: Page, card: str) -> None:
    checked = f"{card}[data-rv-editing] .rv-card-edit input[type=radio]:checked"
    page.wait_for(f"!!{element(checked)}", timeout=SETTLE)


def decided(page: Page, card: str) -> str:
    """Wait for a card's decided footer and return its line."""
    page.wait_for(f"!!document.querySelector('{card} .rv-decided')", timeout=SETTLE)
    return text(page, f"{card} .rv-decided")


def summary_numbers(page: Page) -> list[str]:
    return texts(page, ".rv-view-scores .rv-summary .is-total")


def expected_summary(record: dict[str, Any]) -> tuple[str, list[str], str]:
    """The state, total and percent cells, and band the calculator gives for
    the stored record."""
    selected = select_mca_summary_state(
        McaMatrix.model_validate(record["mca"]["matrix"]), record["mca"]["criteria"]
    )
    assert selected.summary is not None
    summary = selected.summary
    cells = [
        f"{number_to_string(summary.total_weighted_points)} / "
        f"{number_to_string(summary.max_weighted_points)}",
        percent_text(summary.percent_of_maximum),
    ]
    return selected.state, cells, f"{summary.band.label} priority"


def reasons(page: Page) -> list[str]:
    return texts(page, ".rv-readiness-body li")


def wait_reasons(page: Page, expected: list[str]) -> None:
    """Wait for the memo panel to list exactly ``expected``."""
    listed = "[...document.querySelectorAll('.rv-readiness-body li')]"
    shown = f"JSON.stringify({listed}.map((li) => li.textContent))"
    serial = json.dumps(expected, ensure_ascii=False, separators=(",", ":"))
    page.wait_for(f"{shown} === {json.dumps(serial)}", timeout=SETTLE)


# --- The flow ------------------------------------------------------------------------


def test_cards_fill_live_and_decisions_carry_the_review_to_completion(
    tab: Page,
) -> None:
    review_id = submit_default(tab)
    tab.js("document.querySelector('.rv-workspace').__drawn = true; true")
    # A component's cards are drawn once its view opens: open both at once.
    tab.wait_for("!!document.querySelector('[data-rv-open=scores]')", timeout=SETTLE)
    open_part(tab, "scores")
    back_to_hub(tab)
    open_part(tab, "findings")
    back_to_hub(tab)
    tab.wait_for(ALL_LANDED, timeout=SETTLE)
    tab.wait_for(ALL_DRAWN, timeout=SETTLE)
    seen = set(tab.js("[...window.__seen]"))
    assert {"hub:drafting", "summary:pending", "memo:locked"} <= seen
    for dimension in DIMENSIONS:
        assert {f"finding-{dimension}:pending", f"finding-{dimension}:ok"} <= seen
    for criterion in CRITERIA:
        assert {f"score-{criterion}:pending", f"score-{criterion}:ok"} <= seen
    assert tab.js("document.querySelector('.rv-workspace').__drawn === true")
    assert "0 of 5 decided" in text(tab, "[data-rv-open=findings]")
    assert tab.js("!document.querySelector('.rv-root[data-rv-drafting]')")
    wait_reasons(
        tab,
        [
            "5 findings await your decision.",
            "4 scores await your decision.",
            "The reviewer summary has not been written yet.",
        ],
    )

    # Findings: accept, edit, dismiss, accept the rest.
    open_part(tab, "findings")
    accepted, edited, dismissed = (f"#finding-{d}" for d in DIMENSIONS[:3])
    tab.click(f"{accepted} [data-rv-action=accept]")
    assert decided(tab, accepted) == "Accepted as drafted"

    record = stored(tab, review_id)
    draft = record["dimensions"][DIMENSIONS[1]]["finding"]
    new_verdict = "pass" if draft["verdict"] != "pass" else "fail"
    open_editor(tab, edited)
    tab.click(f"{edited} [data-rv-choice=verdict] .is-{new_verdict}")
    replace_text(tab, f"{edited} [data-rv-field=text]", "Coherent, with one gap.")
    tab.click(f"{edited} .rv-card-edit .rv-tray-summary")
    assert texts(tab, f"{edited} [data-rv-list] li .rv-location") == [
        f"{f['sectionLabel']} — {f['fieldLabel']}"
        for e in draft["evidence"]
        for f in record["fields"]
        if (f["sectionId"], f["fieldId"]) == (e["sectionId"], e["fieldId"])
    ]
    tab.click(
        f"{edited} [data-rv-list] li:first-child [data-rv-action=remove-citation]"
    )
    tab.click(f"{edited} [data-rv-action=open-add]")
    added = record["fields"][4]
    tab.js(
        f"(() => {{ const s = {element(edited + ' [data-rv-add-form] select')};"
        " s.value = '4'; s.dispatchEvent(new Event('change', {bubbles: true}));"
        " return true; })()"
    )
    tab.type(f"{edited} [data-rv-add-form] textarea", "  an excerpt  ")
    tab.type(f"{edited} [data-rv-add-form] input", "why it matters")
    tab.click(f"{edited} [data-rv-action=add-citation]")
    assert (
        text(tab, f"{edited} [data-rv-fill=citations]")
        == f"{len(draft['evidence'])} citations"
    )
    tab.click(f"{edited} [data-rv-action=save-edit]")
    assert decided(tab, edited) == "Edited by you"
    disposition = stored(tab, review_id)["dimensions"][DIMENSIONS[1]]["disposition"]
    kept = draft["evidence"][1:]
    assert disposition == {
        "kind": "edited",
        "finalVerdict": new_verdict,
        "finalText": "Coherent, with one gap.",
        "evidence": [
            {"sectionId": e["sectionId"], "fieldId": e["fieldId"], "quote": e["quote"]}
            for e in kept
        ]
        + [
            {
                "sectionId": added["sectionId"],
                "fieldId": added["fieldId"],
                "quote": "an excerpt",
                "note": "why it matters",
            }
        ],
    }
    assert "Coherent, with one gap." in text(tab, edited)
    assert tab.js(f"!document.querySelector('{edited}[data-rv-editing]')")

    tab.click(f"{dismissed} [data-rv-action=dismiss]")
    assert decided(tab, dismissed) == "Dismissed — not in the memo"
    # Decisions in quick succession each land, none lost to a newer redraw.
    for dimension in DIMENSIONS[3:]:
        activate(tab, f"#finding-{dimension} [data-rv-action=accept]")
    for dimension in DIMENSIONS[3:]:
        assert decided(tab, f"#finding-{dimension}") == "Accepted as drafted"

    # A note on a decision is saved when the field is left.
    tab.click(f"{accepted} [data-rv-action=add-note]")
    tab.wait_for(f"document.activeElement === {element(accepted + ' [data-rv-note]')}")
    tab.type(f"{accepted} [data-rv-note]", "Grounded and fair.")
    tab.click(f"{accepted} .rv-card-title")
    tab.wait_for(
        f"JSON.parse(localStorage.getItem('pcn:review:{review_id}'))"
        f".dimensions['{DIMENSIONS[0]}'].disposition.note === 'Grounded and fair.'",
        timeout=SETTLE,
    )
    wait_reasons(
        tab,
        [
            "4 scores await your decision.",
            "The reviewer summary has not been written yet.",
        ],
    )
    back_to_hub(tab)
    assert text(tab, "[data-rv-open=findings] .rv-meter-caption") == "5 of 5 decided"
    assert len(texts(tab, "[data-rv-open=findings] .rv-tick")) == 5

    # Scores: provisional, then accept one, adjust one to the floor.
    open_part(tab, "scores")
    record = stored(tab, review_id)
    state, cells, band = expected_summary(record)
    assert state == "provisional"
    tab.wait_for("!!document.querySelector('.rv-view-scores .rv-provisional')")
    assert summary_numbers(tab) == cells
    assert text(tab, ".rv-view-scores .rv-summary .rv-band-pill") == band

    criteria = record["mca"]["criteria"]
    adjusted = next(c for c in CRITERIA[1:] if criteria[c]["scoreFinding"]["score"] > 1)
    first, second = f"#score-{CRITERIA[0]}", f"#score-{adjusted}"
    draft_score = criteria[CRITERIA[0]]["scoreFinding"]["score"]
    tab.click(f"{first} [data-rv-action=accept]")
    labels = {e["value"]: e["label"] for e in record["mca"]["matrix"]["scale"]}
    assert decided(tab, first) == (
        f"Accepted as drafted — {draft_score} ({labels[draft_score]})"
    )

    ai = criteria[adjusted]["scoreFinding"]["score"]
    raised = 5 if ai != 5 else 4
    open_editor(tab, second)
    assert text(tab, f"{second} [data-rv-value='{ai}'][data-rv-ai] .rv-ai-tag") == "AI"
    assert "Saving without a change endorses the AI's score of" in text(
        tab, f"{second} .rv-editor-hint"
    )
    tab.click(f"{second} [data-rv-choice=score] [data-rv-value='{raised}']")
    silence = f"{second} [data-rv-choice=basis] input[value=not_evidenced]"
    assert tab.js(f"{element(silence)}.disabled")
    assert tab.js(
        f"document.querySelector('{second} [data-rv-action=save-score]').disabled"
    )
    assert "needs your rationale" in text(tab, f"{second} [data-rv-error=rationale]")
    tab.click(f"{second} [data-rv-choice=score] [data-rv-value='1']")
    tab.click(f"{second} .rv-card-edit [data-rv-when=changed] .rv-tray-summary")
    tab.click(f"{second} [data-rv-choice=basis] .is-basis:nth-child(2)")
    basis = f"{element(second + ' .rv-card-edit')}.getAttribute('data-rv-basis')"
    assert tab.js(basis) == "not_evidenced"
    tab.type(
        f"{second} [data-rv-field=rationale]", "Nothing in the submission speaks to it."
    )
    assert text(tab, f"{second} .rv-editor-hint") == (
        f"Your score of 1 replaces the AI draft of {ai} in the memo."
    )
    tab.click(f"{second} [data-rv-action=save-score]")
    assert decided(tab, second) == (
        f"Adjusted by you — 1 (Very low) replaces the AI's draft of {ai}"
    )
    assert stored(tab, review_id)["mca"]["criteria"][adjusted]["disposition"] == {
        "kind": "adjusted",
        "finalScore": 1,
        "rationale": "Nothing in the submission speaks to it.",
        "basis": {"kind": "not_evidenced"},
    }
    assert "scored on absent evidence" in text(tab, second).lower()

    rest = [c for c in CRITERIA[1:] if c != adjusted]
    for criterion in rest:
        activate(tab, f"#score-{criterion} [data-rv-action=accept]")
    for criterion in rest:
        assert decided(tab, f"#score-{criterion}").startswith("Accepted as drafted")
    record = stored(tab, review_id)
    state, cells, band = expected_summary(record)
    assert state == "final"
    tab.wait_for("!document.querySelector('.rv-view-scores .rv-provisional')")
    assert "Endorsed" in text(tab, ".rv-view-scores .rv-summary .rv-card-marks")
    assert summary_numbers(tab) == cells
    assert text(tab, ".rv-view-scores .rv-summary .rv-band-pill") == band
    wait_reasons(tab, ["The reviewer summary has not been written yet."])

    # The summary completes the review.
    back_to_hub(tab)
    tab.type("#rv-ws-summary", "Fundable once the cost phasing is reconciled.")
    tab.wait_for("!document.querySelector('.rv-readiness-body li')", timeout=SETTLE)
    completion = text(tab, ".rv-readiness-body .rv-complete")
    assert completion == (
        f"Assessment complete: 4 findings endorsed, 1 dismissed; final "
        f"prioritisation score {cells[1]} — {band}."
    )
    assert text(tab, "#rv-ws-autosave").startswith("Last saved at ")

    # Everything survives a reload.
    tab.reload(ready="!!document.querySelector('[data-rv-open=findings]')")
    tab.wait_for(
        "!!document.querySelector('.rv-readiness-body .rv-complete')", timeout=SETTLE
    )
    assert tab.js("document.getElementById('rv-ws-summary').value") == (
        "Fundable once the cost phasing is reconciled."
    )
    open_part(tab, "findings")
    tab.wait_for(
        "document.querySelectorAll('.rv-view-findings .rv-decided').length === 5",
        timeout=SETTLE,
    )
    lines = texts(tab, ".rv-view-findings .rv-decided")
    assert lines == [
        "Accepted as drafted",
        "Edited by you",
        "Dismissed — not in the memo",
        "Accepted as drafted",
        "Accepted as drafted",
    ]
    assert tab.js(f"document.querySelector('{accepted} [data-rv-note]').value") == (
        "Grounded and fair."
    )
    assert tab.js(
        f"document.querySelector('{accepted}').hasAttribute('data-rv-note-open')"
    )
    back_to_hub(tab)
    open_part(tab, "scores")
    tab.wait_for(
        "!!document.querySelector('.rv-view-scores .rv-summary')", timeout=SETTLE
    )
    assert summary_numbers(tab) == cells

    # A write for a superseded generation is refused and changes nothing.
    stale = tab.js(
        f"window.pcnReview.decide('{review_id}', 'dimension', '{DIMENSIONS[0]}', 1,"
        " {kind: 'dismissed'})"
    )
    assert stale is False
    after = stored(tab, review_id)["dimensions"][DIMENSIONS[0]]
    assert after["disposition"] == {"kind": "accepted", "note": "Grounded and fair."}
    back_to_hub(tab)
    open_part(tab, "findings")
    assert decided(tab, accepted) == "Accepted as drafted"


def test_the_choosers_and_disclosures_work_from_the_keyboard(tab: Page) -> None:
    submit_default(tab)
    tab.wait_for(ALL_LANDED, timeout=SETTLE)
    open_part(tab, "findings")
    card = f"#finding-{DIMENSIONS[0]}"
    tab.wait_for(
        f"!!{element(card + ' .rv-item-foot [data-rv-action=edit]')}", timeout=SETTLE
    )

    # The evidence tray opens and closes from the keyboard.
    tab.js(
        f"document.querySelector('{card} .rv-card-view .rv-tray-summary').focus(); true"
    )
    tab.press("Enter")
    assert tab.js(f"document.querySelector('{card} .rv-card-view .rv-tray').open")
    tab.press(" ")
    assert not tab.js(f"document.querySelector('{card} .rv-card-view .rv-tray').open")

    # The verdict chooser takes the focus and moves with the arrows.
    focus(tab, f"{card} .rv-item-foot [data-rv-action=edit]")
    tab.press("Enter")
    wait_editor(tab, card)
    before = draft_of(tab, "dimension", DIMENSIONS[0])["verdict"]
    assert tab.js(
        "document.activeElement.type === 'radio' && document.activeElement.checked"
        f" && document.activeElement.value === '{before}'"
    )
    order = ["fail", "notClear", "pass"]
    key(tab, "ArrowRight")
    after = order[(order.index(before) + 1) % 3]
    assert draft_of(tab, "dimension", DIMENSIONS[0])["verdict"] == after
    assert tab.js(
        f"{element(f'{card} [data-rv-choice=verdict] input[value={after}]')}.checked"
    )
    tab.click(f"{card} [data-rv-action=cancel-edit]")
    assert tab.js(f"!document.querySelector('{card}[data-rv-editing]')")

    # The score chooser: off the floor "not evidenced" is skipped, at it
    # the basis chooser reaches it.
    back_to_hub(tab)
    open_part(tab, "scores")
    record = tab.js("window.pcnReview.record()")
    criterion = next(
        c for c in CRITERIA if record["mca"]["criteria"][c]["scoreFinding"]["score"] > 1
    )
    score = f"#score-{criterion}"
    open_editor(tab, score)
    current = int(draft_of(tab, "criterion", criterion)["score"])
    for _ in range(current - 1):
        key(tab, "ArrowLeft")
    assert draft_of(tab, "criterion", criterion)["score"] == 1
    focus(tab, f"{score} [data-rv-when=changed] .rv-tray-summary")
    tab.press("Enter")
    focus(tab, f"{score} [data-rv-choice=basis] input[value=documented]")
    key(tab, "ArrowRight")
    assert draft_of(tab, "criterion", criterion)["basisKind"] == "not_evidenced"
    focus(tab, f"{score} [data-rv-choice=score] input:checked")
    key(tab, "ArrowRight")
    draft = draft_of(tab, "criterion", criterion)
    assert (draft["score"], draft["basisKind"]) == (2, "documented")
    silence = f"{score} [data-rv-choice=basis] input[value=not_evidenced]"
    assert tab.js(f"{element(silence)}.disabled")


def test_retry_relaunches_a_failed_card(failing_tab: Page) -> None:
    review_id = submit_default(failing_tab)
    failing_tab.wait_for(ALL_LANDED, timeout=SETTLE)
    open_part(failing_tab, "findings")
    card = "#finding-cost_realism"
    failing_tab.wait_for(
        f"!!{element(card + ' [data-rv-action=retry]')}", timeout=SETTLE
    )
    assert "Failed" in text(failing_tab, f"{card} .rv-card-marks")
    failing_tab.wait_for(
        "[...document.querySelectorAll('.rv-readiness-body li')]"
        ".some((li) => li.textContent === '1 dimension failed — retry it above.')",
        timeout=SETTLE,
    )
    item = f"window.pcnReviews.getReview('{review_id}').review.dimensions.cost_realism"
    generation = failing_tab.js(f"{item}.generation")
    failing_tab.js("window.__seen.clear(); true")
    failing_tab.click(f"{card} [data-rv-action=retry]")
    failing_tab.wait_for(
        f"{item}.generation === {generation + 1} && {item}.status === 'error'",
        timeout=SETTLE,
    )
    failing_tab.wait_for(
        f"!!{element(card + ' .rv-item-top > [data-rv-status=error]')}", timeout=SETTLE
    )
    assert "finding-cost_realism:pending" in failing_tab.js("[...window.__seen]")


def test_the_workspace_never_scrolls_sideways_at_phone_width(tab: Page) -> None:
    submit_default(tab)
    tab.wait_for(ALL_LANDED, timeout=SETTLE)
    tab.set_viewport(390, 844)
    fits = "document.documentElement.scrollWidth <= window.innerWidth"
    tab.wait_for("!!document.querySelector('[data-rv-open=scores]')")
    assert tab.js(fits)
    open_part(tab, "findings")
    card = f"#finding-{DIMENSIONS[1]}"
    open_editor(tab, card)
    tab.click(f"{card} .rv-card-edit .rv-tray-summary")
    tab.click(f"{card} [data-rv-action=open-add]")
    assert tab.js(fits)
    back_to_hub(tab)
    open_part(tab, "scores")
    guide = f"#score-{CRITERIA[0]} .rv-card-view .rv-guide-tray .rv-tray-summary"
    tab.wait_for(f"!!{element(guide)}", timeout=SETTLE)
    tab.click(guide)
    open_editor(tab, f"#score-{CRITERIA[1]}")
    assert tab.js(fits)
    tab.set_viewport(1280, 900)


def test_a_failed_save_leaves_the_card_usable_and_a_blurring_click_still_acts(
    tab: Page,
) -> None:
    review_id = submit_default(tab)
    tab.wait_for(ALL_LANDED, timeout=SETTLE)
    open_part(tab, "findings")
    item = DIMENSIONS[0]
    card = f"#finding-{item}"
    accept = f"{card} .rv-item-foot [data-rv-action=accept]"
    tab.wait_for(f"!!{element(accept)}", timeout=SETTLE)

    # A write the session refuses leaves the card as it was, and usable.
    tab.js(
        "window.__decide = window.pcnReview.decide;"
        " window.pcnReview.decide = () => false; true"
    )
    tab.click(accept)
    assert tab.js(f"!{element(card)}.hasAttribute('data-rv-saving')")
    assert tab.js(f"!{element(card + ' [aria-disabled]')}")
    assert "disposition" not in stored(tab, review_id)["dimensions"][item]
    tab.js("window.pcnReview.decide = window.__decide; true")

    # From the keyboard it then decides, and the focus lands on Change.
    focus(tab, accept)
    tab.press("Enter")
    assert decided(tab, card) == "Accepted as drafted"
    change = f"{card} .rv-item-foot [data-rv-action=change]"
    tab.wait_for(f"document.activeElement === {element(change)}", timeout=SETTLE)

    # With writes slowed down, a click on Change that ends a note's edit is
    # queued while the note saves on blur (the buttons aria-disabled
    # meanwhile), then replayed at the generation the note's save left.
    generation = stored(tab, review_id)["dimensions"][item]["generation"]
    tab.js(
        "window.pcnReview.decide = (...args) => new Promise((resolve) =>"
        " setTimeout(() => resolve(window.__decide(...args)), 400)); true"
    )
    tab.click(f"{card} [data-rv-action=add-note]")
    tab.type(f"{card} [data-rv-note]", "Checked twice.")
    tab.click(change)
    assert tab.js(f"{element(change)}.getAttribute('aria-disabled')") == "true"
    state = f"window.pcnReviews.getReview('{review_id}').review.dimensions['{item}']"
    tab.wait_for(
        f"{state}.generation === {generation + 2} && !{state}.disposition",
        timeout=SETTLE,
    )
    tab.wait_for(f"document.activeElement === {element(accept)}", timeout=SETTLE)
    assert not tab.js("document.body.innerText.includes('had moved on')")
    assert tab.js(f"!{element(card + ' [aria-disabled]')}")
    tab.js("window.pcnReview.decide = window.__decide; true")


def test_unchanged_edits_are_saved_as_acceptances(tab: Page) -> None:
    review_id = submit_default(tab)
    tab.wait_for(ALL_LANDED, timeout=SETTLE)
    open_part(tab, "findings")
    item = DIMENSIONS[0]
    card = f"#finding-{item}"
    original = stored(tab, review_id)["dimensions"][item]["finding"]["reasoning"]
    disposition = (
        f"window.pcnReviews.getReview('{review_id}').review.dimensions['{item}']"
        ".disposition"
    )

    # An edit, then a note on it.
    open_editor(tab, card)
    replace_text(tab, f"{card} [data-rv-field=text]", "A sharper finding.")
    tab.click(f"{card} [data-rv-action=save-edit]")
    assert decided(tab, card) == "Edited by you"
    tab.click(f"{card} [data-rv-action=add-note]")
    tab.type(f"{card} [data-rv-note]", "Keep this.")
    tab.click(f"{card} .rv-card-title")
    tab.wait_for(f"{disposition}.note === 'Keep this.'", timeout=SETTLE)

    # Edit again back to the draft: an acceptance that keeps the note.
    open_editor(tab, card)
    replace_text(tab, f"{card} [data-rv-field=text]", original)
    tab.click(f"{card} [data-rv-action=save-edit]")
    tab.wait_for(f"{disposition}.kind === 'accepted'", timeout=SETTLE)
    assert stored(tab, review_id)["dimensions"][item]["disposition"] == {
        "kind": "accepted",
        "note": "Keep this.",
    }
    tab.wait_for(
        f"{element(card + ' .rv-decided')}.textContent === 'Accepted as drafted'",
        timeout=SETTLE,
    )

    # A score saved unchanged with a rationale: accepted, the rationale its
    # note.
    back_to_hub(tab)
    open_part(tab, "scores")
    criterion = CRITERIA[0]
    score = f"#score-{criterion}"
    open_editor(tab, score)
    tab.type(f"{score} [data-rv-field=rationale]", "The draft holds up.")
    tab.click(f"{score} [data-rv-action=save-score]")
    criterion_state = (
        f"window.pcnReviews.getReview('{review_id}').review.mca.criteria['{criterion}']"
    )
    tab.wait_for(f"!!{criterion_state}.disposition", timeout=SETTLE)
    assert stored(tab, review_id)["mca"]["criteria"][criterion]["disposition"] == {
        "kind": "accepted",
        "note": "The draft holds up.",
    }
    tab.wait_for(f"{element(score)}.hasAttribute('data-rv-note-open')", timeout=SETTLE)
    assert tab.js(f"{element(score + ' [data-rv-note]')}.value") == (
        "The draft holds up."
    )


SAVED = {"text": "Fundable.", "persisted": True, "saveFailed": False}

CONDITIONS = ("pending", "retryable", "moved_on", "invalid_result", "undecided")


def _condition(state: dict[str, Any], condition: str) -> dict[str, Any]:
    """A decided item's ``state`` put in ``condition``."""
    if condition == "pending":
        return {"status": "pending", "generation": 1}
    if condition == "retryable":
        return error_state(retryable=True)
    if condition == "moved_on":
        return error_state(False, "model_mismatch")
    if condition == "invalid_result":
        return error_state(False, "invalid_result")
    return {key: value for key, value in state.items() if key != "disposition"}


def _decided() -> dict[str, Any]:
    """Every item decided, with only what completion reads."""
    record = drafted_record()
    for state in [*record["dimensions"].values(), *record["mca"]["criteria"].values()]:
        state["disposition"] = {"kind": "accepted"}
    return {key: record[key] for key in ("id", "dimensionDefs", "dimensions", "mca")}


def completion_cases() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Every blocking reason alone, once and twice; each summary state; and
    every reason at once."""
    cases = []
    for condition in CONDITIONS:
        for kind in ("dimension", "criterion"):
            for count in (1, 2):
                record = _decided()
                states = (
                    record["dimensions"]
                    if kind == "dimension"
                    else record["mca"]["criteria"]
                )
                for item in list(states)[:count]:
                    states[item] = _condition(states[item], condition)
                cases.append((record, SAVED))
    for summary in (
        SAVED,
        {"text": " \n ", "persisted": True, "saveFailed": False},
        {"text": "Fundable.", "persisted": False, "saveFailed": False},
        {"text": "Fundable.", "persisted": False, "saveFailed": True},
    ):
        cases.append((_decided(), summary))
    record = _decided()
    for states in (record["dimensions"], record["mca"]["criteria"]):
        for item, condition in zip(states, CONDITIONS, strict=False):
            states[item] = _condition(states[item], condition)
    cases.append((record, {"text": "", "persisted": True, "saveFailed": False}))
    return cases


def test_completion_in_the_browser_matches_the_session_module(tab: Page) -> None:
    """On a review page, ``pcnReview.completion`` and ``status`` give the
    reasons and line ``pcn_clone.app.review.completion`` gives, slot by
    slot, singular and plural."""
    cases = completion_cases()
    submit_default(tab)
    tab.wait_for("!!window.pcnReview.record()", timeout=SETTLE)
    shown = tab.js(
        f"{json.dumps(cases)}.map(([record, summary]) =>"
        " [window.pcnReview.completion(record, summary),"
        " window.pcnReview.status(record, summary)])"
    )
    reasons_seen = set()
    for (record, summary), (done, line) in zip(cases, shown, strict=True):
        expected = completion(record, summary)  # type: ignore[arg-type]
        assert done == {"ready": expected.ready, "reasons": list(expected.reasons)}
        assert line == status_line(record, summary)  # type: ignore[arg-type]
        reasons_seen.update(expected.reasons)
    # 10 slots in both numbers, and the three summary reasons.
    assert len(reasons_seen) == 10 * 2 + 3


def test_review_ui_moves_the_adjustment_draft_as_adjust_draft_does(tab: Page) -> None:
    finding = {
        "score": 3,
        "justification": "Some merit.",
        "basis": {
            "kind": "documented",
            "evidence": [
                {"sectionId": "s1", "fieldId": "f1", "quote": "q", "verified": True}
            ],
        },
    }
    silent = {
        "score": 1,
        "justification": "Silent.",
        "basis": {"kind": "not_evidenced"},
    }
    prior = {
        "kind": "adjusted",
        "finalScore": 1,
        "rationale": "None.",
        "basis": {"kind": "not_evidenced"},
    }
    tab.wait_for("!!(window.pcnReviewUi && window.pcnReviewUi.adjust)")
    js = "window.pcnReviewUi.adjust"
    for source, initial in ((finding, None), (silent, None), (finding, prior)):
        draft = initial_adjust_draft(source, initial)
        assert (
            tab.js(
                f"{js}.initialAdjustDraft({json.dumps(source)}, {json.dumps(initial)})"
            )
            == draft
        )
        for score in (1, 2, 5):
            moved = with_score(draft, score, 1)
            assert tab.js(f"{js}.withScore({json.dumps(draft)}, {score}, 1)") == moved
            for kind in ("documented", "not_evidenced"):
                picked = with_basis_kind(moved, kind, 1)  # type: ignore[arg-type]
                assert (
                    tab.js(f"{js}.withBasisKind({json.dumps(moved)}, '{kind}', 1)")
                    == picked
                )
                for rationale in ("", " \n", "Because."):
                    written = {**picked, "rationale": rationale}
                    issues = adjust_draft_issues(written)  # type: ignore[arg-type]
                    assert (
                        tab.js(f"{js}.adjustDraftIssues({json.dumps(written)})")
                        == issues
                    )
                    if can_save_adjust_draft(written):  # type: ignore[arg-type]
                        assert tab.js(
                            f"{js}.toAdjustedDisposition({json.dumps(written)})"
                        ) == to_adjusted_disposition(written)  # type: ignore[arg-type]
