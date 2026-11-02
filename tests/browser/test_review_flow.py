"""The review flow in a real browser, against the offline fake provider with
one second of latency per call and a retryable failure injected for the
``cost_realism`` dimension: Submit freezes the default project into a review
and opens it (and gives up, re-enabled, when the snapshot never comes); the
run drafts all nine items and each result is merged into the stored record
at the generation its launch wrote, only while that item is still pending;
Retry relaunches the failed item alone; a reload restarts only what is
pending; a page mounted again waits for the run in flight; results keep
landing, and the list keeps up, while the reviewer is elsewhere; two
results written in one tick are both merged; late or repeated results never
overwrite; an item the live content no longer has fails terminally;
decisions, the summary's autosave and the completion reasons follow; the
list deletes payload first; the gate and the provenance popover render the
record. A last test drops the server mid-run and sees the items fail
retryably once the run's heartbeats stop."""

from __future__ import annotations

import json
import os
import signal
from collections.abc import Iterator

import pytest

from pcn_clone.app.routing import page_url
from pcn_clone.content import load_assessment, load_mca
from tests.browser.form_steps import open_default
from tests.browser.harness import AppServer, Chrome, Page, url_param
from tests.browser.review_steps import (
    FAILED,
    HOOKS,
    INPUT,
    ITEMS,
    LANDED,
    ON_REVIEW_URL,
    STATUS,
    decide,
    post,
    result,
    states,
    stored,
    submit_default,
    toasts,
    wait_idle,
)
from tests.helpers import load_fixture

SERVER_ENV = {"PCN_AI_FAKE_DELAY_SECONDS": "1", "PCN_AI_FAKE_FAIL": "cost_realism"}

LIST_ROW = "#assess-rows tr.row-link"


@pytest.fixture(scope="module")
def review_server(
    chrome_binary: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[AppServer]:
    server = AppServer(tmp_path_factory.mktemp("review") / "uvicorn.log", SERVER_ENV)
    server.start()
    yield server
    server.stop()


def fresh_tab(chrome: Chrome, server: AppServer) -> Page:
    page = chrome.new_page(server.url)
    page.goto("/?page=projects", ready="!!window.pcnStore")
    page.js("localStorage.clear(); sessionStorage.clear(); true")
    return page


@pytest.fixture
def tab(chrome: Chrome, review_server: AppServer) -> Iterator[Page]:
    """A fresh tab on the review server's origin with empty storage."""
    page = fresh_tab(chrome, review_server)
    yield page
    errors = page.errors()
    page.close()
    assert errors == [], errors


def wait_status(page: Page, text: str, timeout: float = 15) -> None:
    page.wait_for(f"({STATUS}) === {json.dumps(text)}", timeout=timeout)


def results_in_inbox(page: Page) -> list[dict[str, object]]:
    found: list[dict[str, object]] = page.js(
        "window.__inbox.filter((m) => m.type === 'result')"
    )
    return found


# --- Submit and the run ----------------------------------------------------------


def test_submit_freezes_the_project_and_the_run_drafts_every_item(tab: Page) -> None:
    open_default(tab)
    assert (
        tab.js("document.getElementById('pf-submit').hasAttribute('aria-disabled')")
        is False
    )
    tab.js(HOOKS)
    tab.click("#pf-submit")
    tab.wait_for(ON_REVIEW_URL, timeout=15)
    review_id = tab.js(url_param("review_id"))

    created = tab.js("window.__created")
    expected = load_fixture("serialized_default.json")
    assert created["id"] == review_id
    assert created["schemaVersion"] == 2
    assert created["projectTitle"] == "Upper Valley District Road Rehabilitation"
    assert (
        created["sourceProjectTemplateVersion"] == created["templateVersion"] == "1.5.0"
    )
    assert created["fields"] == expected["fields"]
    assert created["submission"]["answers"] == expected["canonicalAnswers"]
    assert created["assessmentInputDigest"] == expected["digest"]
    assert created["assessmentInputDigest"].startswith("aiv1-9c67")
    assert created["dimensionDefs"] == [
        d.to_json() for d in load_assessment().dimensions
    ]
    assert created["mca"]["matrix"] == load_mca().matrix.to_json()
    assert (created["mca"]["setId"], created["mca"]["setVersion"]) == (
        "pcn_global_mca_default",
        "0.1.0",
    )
    assert created["model"] == "fake/pcn-reviewer"
    assert created["reviewerSummary"] == ""
    assert states(created) == {item: ("pending", 0) for _, item in ITEMS}

    wait_status(tab, "Drafting all 9 sections in parallel — 0 returned")
    (launch,) = tab.js("window.__launches")
    assert launch["items"] == [
        {"kind": kind, "id": item, "generation": 1} for kind, item in ITEMS
    ]
    assert states(stored(tab, review_id)) == {item: ("pending", 1) for _, item in ITEMS}

    wait_idle(tab, review_id)
    record = stored(tab, review_id)
    delivered = results_in_inbox(tab)
    assert sorted((m["kind"], m["itemId"]) for m in delivered) == sorted(ITEMS)
    assert {m["generation"] for m in delivered} == {1}
    assert tab.js("window.__inbox[0].type") == "started"
    assert tab.js("window.__inbox.at(-1).type") == "done"
    assert states(record) == {
        item: ("error" if item == "cost_realism" else "ok", 1) for _, item in ITEMS
    }
    failure = record["dimensions"]["cost_realism"]
    assert failure["error"] == {"kind": "retryable", "code": "provider_error"}
    assert failure["errorMessage"] == (
        "The assessment could not be completed. Please try again."
    )
    finding = record["dimensions"]["internal_coherence"]["finding"]
    assert finding["dimensionId"] == "internal_coherence"
    assert finding["model"] == "fake/pcn-reviewer"
    wait_status(tab, "1 dimension failed — retry it above.")


def test_retry_relaunches_the_failed_item_alone(tab: Page) -> None:
    review_id = submit_default(tab)
    wait_idle(tab, review_id)
    before = states(stored(tab, review_id))

    retry = f"window.pcnReview.retry('{review_id}', 'dimension', "
    assert tab.js(retry + "'internal_coherence')") is False
    assert tab.js(retry + "'cost_realism')") is True
    assert tab.js(retry + "'cost_realism')") is False
    assert tab.js("window.__launches.at(-1).items") == [
        {"kind": "dimension", "id": "cost_realism", "generation": 2}
    ]
    wait_status(tab, "Drafting all 9 sections in parallel — 8 returned")
    wait_idle(tab, review_id)

    assert states(stored(tab, review_id)) == {**before, "cost_realism": ("error", 2)}
    assert len(tab.js("window.__launches")) == 2


def test_a_reload_mid_run_restarts_only_what_is_pending(tab: Page) -> None:
    review_id = submit_default(tab)
    wait_idle(tab, review_id)
    assert (
        tab.js(f"window.pcnReview.retry('{review_id}', 'dimension', 'cost_realism')")
        is True
    )
    assert states(stored(tab, review_id))["cost_realism"] == ("pending", 2)

    tab.reload(ready=f"({STATUS}).length > 0")

    record = stored(tab, review_id)
    assert record["dimensions"]["cost_realism"]["generation"] == 3
    assert {
        item: state for item, state in states(record).items() if item != "cost_realism"
    } == {item: ("ok", 1) for _, item in ITEMS if item != "cost_realism"}
    wait_idle(tab, review_id)
    assert states(stored(tab, review_id))["cost_realism"] == ("error", 3)


def test_a_page_mounted_again_mid_run_waits_instead_of_launching(tab: Page) -> None:
    review_id = submit_default(tab)
    tab.wait_for(f"({STATUS}).startsWith('Drafting')")

    record = tab.js(
        f"window.dash_clientside.pcnReview.mount({{reviewId: '{review_id}'}}, null)"
    )

    assert states(record) == {item: ("pending", 1) for _, item in ITEMS}
    assert states(stored(tab, review_id)) == {item: ("pending", 1) for _, item in ITEMS}
    wait_idle(tab, review_id)
    assert len(tab.js("window.__launches")) == 1
    assert {state[1] for state in states(stored(tab, review_id)).values()} == {1}


def test_results_land_and_the_list_keeps_up_while_the_reviewer_is_elsewhere(
    tab: Page,
) -> None:
    review_id = submit_default(tab)
    tab.wait_for(f"({STATUS}).startsWith('Drafting')")

    tab.click(".pf-crumb-link")
    tab.wait_for(f"!!document.querySelector('{LIST_ROW}')", timeout=10)
    tab.wait_for(
        f"document.querySelector('{LIST_ROW} .as-progress').textContent"
        " === '5/5 dimensions · 4/4 criteria · 1 failed'",
        timeout=15,
    )
    wait_idle(tab, review_id, on_page=False)
    tab.click(f"{LIST_ROW} .cell-title")
    tab.wait_for(LANDED)

    assert len(tab.js("window.__launches")) == 1
    assert states(stored(tab, review_id))["internal_coherence"] == ("ok", 1)


def test_two_results_for_one_item_in_one_tick_are_both_merged(tab: Page) -> None:
    tab.goto("/?page=assess", ready="!document.getElementById('assess-empty').hidden")
    first, second = tab.js(
        f"""(() => {{
          const R = window.pcnReviews, input = {json.dumps(INPUT)};
          return [R.createReview(input), R.createReview(input)]
            .map((record) => {{
              R.launchItem(record.id, "dimension", "internal_coherence", 0);
              return record.id;
            }});
        }})()"""
    )
    finding = {
        "dimensionId": "internal_coherence",
        "model": INPUT["model"],
        "verdict": "pass",
        "reasoning": "Coherent.",
        "evidence": [],
        "questions": [],
    }

    post(
        tab,
        result(
            first,
            "dimension",
            "internal_coherence",
            1,
            {"ok": True, "finding": finding},
        ),
        result(second, "dimension", "internal_coherence", 1, FAILED),
    )
    tab.wait_for(
        f"JSON.parse(localStorage.getItem('pcn:review:{second}'))"
        ".dimensions.internal_coherence.status === 'error'"
    )

    assert stored(tab, first)["dimensions"]["internal_coherence"]["status"] == "ok"
    tab.wait_for(f"document.querySelectorAll('{LIST_ROW}').length === 2")


def test_late_or_repeated_results_never_overwrite(tab: Page) -> None:
    review_id = submit_default(tab)
    wait_idle(tab, review_id)
    before = stored(tab, review_id)

    post(tab, result(review_id, "dimension", "internal_coherence", 0, FAILED))
    tab.wait_for("document.querySelectorAll('.mantine-Notification-root').length === 1")
    post(tab, result(review_id, "dimension", "internal_coherence", 1, FAILED))
    tab.wait_for("document.querySelectorAll('.mantine-Notification-root').length === 2")
    wait_idle(tab, review_id)
    assert stored(tab, review_id) == before
    assert (
        toasts(tab)
        == ["A superseded result for “Internal coherence” was discarded."] * 2
    )

    assert decide(
        tab, review_id, "dimension", "internal_coherence", 1, {"kind": "accepted"}
    )
    decided = stored(tab, review_id)
    post(tab, result(review_id, "dimension", "internal_coherence", 2, FAILED))
    tab.wait_for("document.querySelectorAll('.mantine-Notification-root').length === 3")
    wait_idle(tab, review_id)
    assert stored(tab, review_id) == decided
    assert decided["dimensions"]["internal_coherence"]["disposition"] == {
        "kind": "accepted"
    }


def test_an_item_the_live_content_lacks_fails_terminally(tab: Page) -> None:
    retired = dict(INPUT["dimensionDefs"][0]) | {
        "id": "retired_dimension",
        "label": "Retired dimension",
    }
    review_id = tab.js(
        "window.pcnReviews.createReview("
        f"{json.dumps(INPUT | {'dimensionDefs': [*INPUT['dimensionDefs'], retired]})}"
        ").id"
    )

    tab.goto(
        "/" + page_url("review", review_id=review_id), ready=f"({STATUS}).length > 0"
    )
    wait_idle(tab, review_id)

    state = stored(tab, review_id)["dimensions"]["retired_dimension"]
    assert state["status"] == "error"
    assert state["error"] == {"kind": "terminal", "code": "unknown_dimension"}
    assert (
        tab.js(
            f"window.pcnReview.retry('{review_id}', 'dimension', 'retired_dimension')"
        )
        is False
    )
    reasons = tab.js(
        "window.pcnReview.completion(window.pcnReview.record(),"
        " {text: 'x', persisted: true, saveFailed: false}).reasons"
    )
    assert reasons[:2] == [
        "1 dimension failed — retry it above.",
        "1 dimension can no longer be assessed — submit the project again from its "
        "editor.",
    ]


# --- Decisions, the summary and completion ----------------------------------------


def test_decisions_and_the_summary_carry_the_review_to_completion(tab: Page) -> None:
    review_id = submit_default(tab)
    wait_idle(tab, review_id)
    finding = stored(tab, review_id)["dimensions"]["internal_coherence"]["finding"]
    assert (
        tab.js(f"window.pcnReview.retry('{review_id}', 'dimension', 'cost_realism')")
        is True
    )
    post(
        tab,
        result(
            review_id,
            "dimension",
            "cost_realism",
            2,
            {"ok": True, "finding": {**finding, "dimensionId": "cost_realism"}},
        ),
    )
    wait_status(tab, "5 findings await your decision.")
    wait_idle(tab, review_id)
    assert stored(tab, review_id)["dimensions"]["cost_realism"]["status"] == "ok"
    assert "A superseded result for “Cost realism” was discarded." in toasts(tab)

    generations = {
        item: state[1] for item, state in states(stored(tab, review_id)).items()
    }
    for kind, item in ITEMS:
        assert decide(
            tab, review_id, kind, item, generations[item], {"kind": "accepted"}
        )
    late = decide(
        tab, review_id, "dimension", "evidence_quality", 1, {"kind": "dismissed"}
    )
    assert late is False
    assert (
        "“Evidence quality” had moved on — the view was refreshed; please decide again."
        in toasts(tab)
    )
    assert states(stored(tab, review_id)) == {
        item: ("ok", generations[item] + 1) for _, item in ITEMS
    }
    wait_status(tab, "The reviewer summary has not been written yet.")

    tab.js(
        f"window.pcnReview.changeSummary('{review_id}', 'Fundable as drafted.'); true"
    )
    wait_status(tab, "The reviewer summary is still saving.")
    summary = tab.js(f"window.pcnReview.summaryState('{review_id}')")
    assert (summary["persisted"], summary["saveFailed"]) == (False, False)
    assert stored(tab, review_id)["reviewerSummary"] == ""
    wait_status(tab, "All sections decided — assessment complete", timeout=5)

    assert stored(tab, review_id)["reviewerSummary"] == "Fundable as drafted."
    summary = tab.js(f"window.pcnReview.summaryState('{review_id}')")
    assert summary["persisted"] is True
    assert isinstance(summary["lastSavedISO"], str)
    assert tab.js("window.pcnReview.record().reviewerSummary") == "Fundable as drafted."
    reasons = tab.js(
        "window.pcnReview.completion(window.pcnReview.record(), "
        "{text: '', persisted: true, saveFailed: false})"
    )
    assert reasons == {
        "ready": False,
        "reasons": ["The reviewer summary has not been written yet."],
    }


# --- Submit giving up -------------------------------------------------------------


def test_submit_gives_up_when_the_snapshot_never_comes(tab: Page) -> None:
    open_default(tab)
    tab.js(
        """(() => {
          const ns = window.dash_clientside.pcnReview;
          const start = ns.startSubmit;
          ns.startSubmit = function (clicks, project, config) {
            return start.call(this, clicks, project,
              Object.assign({}, config, {submitTimeoutMs: 800}));
          };
          return true;
        })()"""
    )
    tab.send("Fetch.enable", {"patterns": [{"urlPattern": "*_dash-update-component*"}]})
    since = len(tab.events)
    tab.click("#pf-submit")
    paused = tab.wait_event(
        "Fetch.requestPaused",
        lambda params: "pf-submit-snapshot" in params["request"].get("postData", ""),
        since=since,
    )
    submit = "document.getElementById('pf-submit')"
    tab.wait_for(
        f"!{submit}.hasAttribute('aria-disabled')"
        f" && {submit}.getAttribute('aria-busy') === 'false'",
        timeout=5,
    )
    assert toasts(tab) == [
        "Couldn’t submit for assessment"  # noqa: RUF001
        "The server did not answer. Please try again."
    ]

    tab.send("Fetch.continueRequest", {"requestId": paused["requestId"]})
    tab.send("Fetch.disable")
    tab.pump(1.0)
    assert tab.js("location.search").startswith("?page=project&project_id=")
    assert tab.js("localStorage.getItem('pcn:reviews')") is None


# --- The list, the gate and the provenance ------------------------------------------


def test_the_list_shows_progress_and_delete_removes_payload_then_index(
    tab: Page,
) -> None:
    review_id = submit_default(tab)
    wait_idle(tab, review_id)
    tab.click(".pf-crumb-link")
    tab.wait_for(f"!!document.querySelector('{LIST_ROW}')", timeout=10)

    cells = tab.js(
        f"[...document.querySelectorAll('{LIST_ROW} td')].map((td) => td.textContent)"
    )
    assert cells[:3] == [
        "1",
        "Upper Valley District Road Rehabilitation",
        "5/5 dimensions · 4/4 criteria · 1 failed",
    ]
    assert tab.js("document.getElementById('assess-count').textContent") == "1"

    tab.js(
        """(() => {
          window.__writes = [];
          const proto = Object.getPrototypeOf(localStorage);
          const remove = proto.removeItem, set = proto.setItem;
          proto.removeItem = function (key) {
            window.__writes.push(["remove", key]);
            return remove.call(this, key);
          };
          proto.setItem = function (key, value) {
            window.__writes.push(["set", key]);
            return set.call(this, key, value);
          };
          return true;
        })()"""
    )
    tab.click(f"{LIST_ROW} button")
    tab.wait_for(
        "!!document.querySelector('.mantine-Modal-content #assess-delete-confirm')"
    )
    tab.click("#assess-delete-confirm")
    tab.wait_for("!document.getElementById('assess-empty').hidden", timeout=10)

    assert tab.js("window.__writes") == [
        ["remove", f"pcn:review:{review_id}"],
        ["set", "pcn:reviews"],
    ]
    assert tab.js(f"localStorage.getItem('pcn:review:{review_id}')") is None
    assert tab.js("JSON.parse(localStorage.getItem('pcn:reviews'))") == []
    assert "Assessment session deleted" in toasts(tab)


def test_unreadable_sessions_are_listed_and_gated(tab: Page) -> None:
    tab.js(
        """(() => {
          const old = {schemaVersion: 1, id: "old"};
          localStorage.setItem("pcn:review:old", JSON.stringify(old));
          localStorage.setItem("pcn:reviews", JSON.stringify([old]));
          return true;
        })()"""
    )
    tab.goto("/?page=assess", ready="!!document.querySelector('#assess-rows tr')")

    assert (
        tab.js("document.querySelector('#assess-rows tr').className") == "as-unreadable"
    )
    assert tab.js("document.querySelector('#assess-rows tr').textContent") == (
        "Unreadable assessment session"
        "This review was saved by a different version of the app and cannot be opened."
    )
    assert tab.js("document.getElementById('assess-count').textContent") == "0"

    tab.goto(
        "/?page=review&review_id=old",
        ready="!!document.querySelector('.pj-gate-unreadable')",
    )
    assert tab.js("document.querySelector('.pj-gate-card').textContent") == (
        "This assessment session can’t be opened."  # noqa: RUF001
        "This review was saved by a different version of the app and cannot be opened."
        "← Back to Assessment"
    )
    tab.goto(
        "/?page=review&review_id=nowhere",
        ready="!!document.querySelector('.pj-gate-missing')",
    )


def test_the_details_popover_shows_the_provenance(tab: Page) -> None:
    review_id = submit_default(tab)
    wait_idle(tab, review_id)
    tab.click("#rv-details")
    tab.wait_for("!!document.querySelector('.rv-prov .rv-prov-row')")

    rows = tab.js(
        "[...document.querySelectorAll('.rv-prov-row')].map((row) =>"
        " [row.querySelector('dt').textContent, row.querySelector('dd').textContent])"
    )
    created = stored(tab, review_id)["createdISO"]
    submitted = tab.js(
        f"""(() => {{ const d = new Date({json.dumps(created)});
          const p = (n) => String(n).padStart(2, "0");
          return `${{p(d.getMonth() + 1)}}.${{p(d.getDate())}}.${{d.getFullYear()}}, `
            + `${{p(d.getHours())}}:${{p(d.getMinutes())}}`; }})()"""
    )
    assert rows == [
        ["Template", "Global v1.5.0pcn_global"],
        ["Assessment criteria", "v0.3.0pcn_global_reviewer_default"],
        ["Prioritisation criteria (MCA)", "v0.1.0pcn_global_mca_default"],
        ["Model", "fake/pcn-reviewer"],
        ["Submitted", submitted],
    ]
    assert tab.js("!!document.querySelector('.rv-prov-note')") is False

    tab.js(
        f"""(() => {{ const key = 'pcn:review:{review_id}';
          const record = JSON.parse(localStorage.getItem(key));
          record.sourceProjectTemplateVersion = '1.4.0';
          localStorage.setItem(key, JSON.stringify(record)); return true; }})()"""
    )
    tab.reload(ready=LANDED)
    tab.click("#rv-details")
    tab.wait_for("!!document.querySelector('.rv-prov-note')")
    assert tab.js("document.querySelector('.rv-prov-note').textContent") == (
        "This project was created against template v1.4.0; it was assessed "
        "against v1.5.0, the version live at submission."
    )


# --- A dropped connection -------------------------------------------------------------


def test_a_run_whose_server_goes_away_fails_retryably(
    chrome: Chrome, tmp_path_factory: pytest.TempPathFactory
) -> None:
    server = AppServer(
        tmp_path_factory.mktemp("dropped") / "uvicorn.log",
        {"PCN_AI_FAKE_DELAY_SECONDS": "30", "PCN_REVIEW_HEARTBEAT_SECONDS": "1"},
    )
    server.start()
    page = fresh_tab(chrome, server)
    try:
        review_id = submit_default(page)
        wait_status(page, "Drafting all 9 sections in parallel — 0 returned")
        page.wait_for("window.__inbox.some((m) => m.type === 'heartbeat')", timeout=5)

        assert server.process is not None
        os.killpg(server.process.pid, signal.SIGKILL)
        server.process.wait()
        server.start()
        wait_idle(page, review_id, timeout=15)

        record = stored(page, review_id)
        assert {
            item: (state["status"], state["error"])
            for item, state in record["dimensions"].items()
        } == {
            item: ("error", {"kind": "retryable", "code": "transport_error"})
            for item in record["dimensions"]
        }
        assert states(record) == {item: ("error", 1) for _, item in ITEMS}
        wait_status(page, "5 dimensions failed — retry them above.")
        assert (
            page.js(
                f"window.pcnReview.retry('{review_id}', 'dimension', 'cost_realism')"
            )
            is True
        )
        page.wait_for(
            "window.__inbox.filter((m) => m.type === 'started').length === 2",
            timeout=10,
        )
        assert page.errors() == []
    finally:
        page.close()
        server.stop()
