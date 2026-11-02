"""The review store (``window.pcnReviews``, ``assets/review-store.js``) in a
real browser: what createReview stamps, the invariants every read and write
checks, the compare-and-swap on an item's generation with its visible
refusals (a result only into an item still pending at its generation), the
listing's unreadable entries, the rollback that keeps payload and index
together and never deletes a payload it could not read, and delete's
order."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from tests.browser.harness import Page
from tests.browser.review_steps import INPUT

HELPERS = """(() => {
  window.__input = INPUT;
  window.__finding = (record, id) => ({
    dimensionId: id, model: record.model, verdict: "pass", reasoning: "Reasoned.",
    evidence: [{sectionId: record.fields[0].sectionId,
                fieldId: record.fields[0].fieldId, quote: "Upper", verified: true}],
    questions: [],
  });
  window.__score = (record, id, score, basis) => ({
    criterionId: id, model: record.model, score, justification: "Justified.", basis,
  });
  window.__issues = (record) => {
    const result = window.pcnReviews.checkRecord(record);
    return result.ok ? [] : result.issues.map((issue) => issue.message);
  };
  return true;
})()""".replace("INPUT", json.dumps(INPUT))


@pytest.fixture
def store_page(page: Page) -> Iterator[Page]:
    page.js(HELPERS)
    yield page


def create(page: Page) -> dict[str, Any]:
    record: dict[str, Any] = page.js("window.pcnReviews.createReview(window.__input)")
    return record


def issues_after(page: Page, mutation: str) -> list[str]:
    """The invariant messages for a fresh record after ``mutation`` (a
    statement over ``r``)."""
    found: list[str] = page.js(
        f"""(() => {{ const r = window.pcnReviews.createReview(window.__input);
          {mutation}
          return window.__issues(r); }})()"""
    )
    return found


def test_create_stamps_identity_pending_items_and_the_index(store_page: Page) -> None:
    record = create(store_page)

    assert record["schemaVersion"] == 2
    assert record["createdISO"] == record["editedISO"]
    assert record["reviewerSummary"] == ""
    items = [*record["dimensions"].values(), *record["mca"]["criteria"].values()]
    assert items == [{"status": "pending", "generation": 0}] * 9
    assert len(record["dimensions"]) == 5
    assert len(record["mca"]["criteria"]) == 4
    assert store_page.js(f"localStorage.getItem('pcn:review:{record['id']}') !== null")
    assert store_page.js("JSON.parse(localStorage.getItem('pcn:reviews'))") == [
        {
            "schemaVersion": 2,
            "id": record["id"],
            "createdISO": record["createdISO"],
            "editedISO": record["editedISO"],
            "projectTitle": INPUT["projectTitle"],
            "templateId": "pcn_global",
            "templateLabel": "Global",
            "dimensionsTotal": 5,
            "dimensionsOk": 0,
            "dimensionsError": 0,
            "criteriaTotal": 4,
            "criteriaOk": 0,
            "criteriaError": 0,
        }
    ]
    listing = store_page.js("window.pcnReviews.listReviews()")
    assert listing["unreadable"] == []
    assert [entry["id"] for entry in listing["entries"]] == [record["id"]]


def test_a_record_breaking_an_invariant_is_never_created(store_page: Page) -> None:
    thrown = store_page.js(
        """(() => {
          const input = JSON.parse(JSON.stringify(window.__input));
          input.fields.reverse();
          try { window.pcnReviews.createReview(input); return null; }
          catch (error) { return [error.name, localStorage.getItem("pcn:reviews")]; }
        })()"""
    )

    assert thrown == ["ReviewInvariantError", None]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            "[r.fields[0], r.fields[1]] = [r.fields[1], r.fields[0]];",
            "does not agree with submission answer "
            '"investment_identification/project_title" at position 0.',
        ),
        (
            "r.dimensions.cost_realism = {status: 'ok', generation: 1,"
            " finding: Object.assign(window.__finding(r, 'cost_realism'),"
            " {model: 'other/model'})};",
            'Finding for "cost_realism" was produced by model "other/model", but the '
            'record pins "fake/pcn-reviewer".',
        ),
        (
            "r.dimensions.cost_realism = {status: 'ok', generation: 1,"
            " finding: window.__finding(r, 'internal_coherence')};",
            'Finding for "cost_realism" carries dimensionId "internal_coherence".',
        ),
        (
            "const f = window.__finding(r, 'cost_realism');"
            " f.evidence[0].fieldId = 'invented';"
            " r.dimensions.cost_realism = {status: 'ok', generation: 1, finding: f};",
            'Finding for "cost_realism" cites "investment_identification/invented", '
            "which is not in the record's field snapshot.",
        ),
        (
            "r.dimensions.cost_realism = {status: 'ok', generation: 2,"
            " finding: window.__finding(r, 'cost_realism'), disposition: {kind:"
            " 'edited', finalVerdict: 'fail', finalText: 'Weak.', evidence:"
            " [{sectionId: 'identification', fieldId: 'invented'}]}};",
            'Edited disposition for "cost_realism" cites "identification/invented", '
            "which is not in the record's field snapshot.",
        ),
        (
            "r.mca.criteria.environmental_impact = {status: 'ok', generation: 1,"
            " scoreFinding: window.__score(r, 'environmental_impact', 3,"
            " {kind: 'not_evidenced'})};",
            'Score finding for "environmental_impact" pairs a not_evidenced basis '
            "with score 3; absence can only score the scale minimum (1).",
        ),
        (
            "r.mca.criteria.environmental_impact = {status: 'ok', generation: 1,"
            " scoreFinding: window.__score(r, 'environmental_impact', 9,"
            " {kind: 'not_evidenced'})};",
            'Score 9 for "environmental_impact" is not a value on the frozen '
            "matrix's scale.",
        ),
        (
            "r.mca.criteria.environmental_impact = {status: 'ok', generation: 2,"
            " scoreFinding: window.__score(r, 'environmental_impact', 1,"
            " {kind: 'not_evidenced'}), disposition: {kind: 'adjusted', finalScore: 3,"
            " rationale: 'Better.', basis: {kind: 'not_evidenced'}}};",
            'Adjusted score for "environmental_impact" pairs a not_evidenced basis '
            "with score 3; a non-minimum score must cite the submission.",
        ),
        (
            "r.mca.criteria.environmental_impact = {status: 'ok', generation: 2,"
            " scoreFinding: window.__score(r, 'environmental_impact', 1,"
            " {kind: 'not_evidenced'}), disposition: {kind: 'adjusted', finalScore: 4,"
            " rationale: 'Better.', basis: {kind: 'documented', evidence:"
            " [{sectionId: 'nowhere', fieldId: 'x'}]}}};",
            'Adjusted disposition for "environmental_impact" cites "nowhere/x", '
            "which is not in the record's field snapshot.",
        ),
        (
            "r.dimensions.unknown = {status: 'pending', generation: 0};",
            'Dimension state "unknown" has no matching definition.',
        ),
        (
            "delete r.mca.criteria.environmental_impact;",
            'Criterion "environmental_impact" has no state entry.',
        ),
        (
            "r.submission.templateId = 'other';",
            'Submission targets template "other", but the record pins "pcn_global".',
        ),
        (
            "r.mca.matrix.criteria[0].weight += 1;",
            "Criterion weights must sum to exactly 100; they sum to 101.",
        ),
        ("r.extra = true;", 'Unrecognized key "extra".'),
        (
            "r.dimensions.cost_realism = {status: 'error', generation: 1,"
            " errorMessage: 'x', error: {kind: 'terminal', code: 'provider_error'}};",
            "Expected one of invalid_request",
        ),
        (
            "r.dimensions.cost_realism = {status: 'error', generation: 1,"
            " errorMessage: 'x', error: {kind: 'terminal',"
            " code: 'assessor_revision_mismatch'}};",
            "Expected one of invalid_request",
        ),
        (
            "const f = window.__finding(r, 'cost_realism');"
            " f.evidence[0].quote = 'x'.repeat(301);"
            " r.dimensions.cost_realism = {status: 'ok', generation: 1, finding: f};",
            "Expected at most 300 characters.",
        ),
    ],
)
def test_every_invariant_is_checked(
    store_page: Page, mutation: str, message: str
) -> None:
    found = issues_after(store_page, mutation)

    assert any(message in issue for issue in found), found


def test_writes_compare_and_swap_on_the_item_generation(store_page: Page) -> None:
    review_id = create(store_page)["id"]
    results = store_page.js(
        f"""(() => {{
          const R = window.pcnReviews, id = {json.dumps(review_id)};
          const launched = R.launchItem(id, "dimension", "cost_realism", 0);
          const stale = R.launchItem(id, "dimension", "cost_realism", 0);
          const record = R.getReview(id).review;
          const finding = window.__finding(record, "cost_realism");
          const ok = R.writeItem(id, "dimension", "cost_realism", 1,
            {{status: "ok", generation: 1, finding}});
          let invalid = null;
          const before = localStorage.getItem("pcn:review:" + id);
          try {{
            R.writeItem(id, "dimension", "cost_realism", 1, {{status: "ok",
              generation: 2, finding: window.__finding(record, "other")}});
          }} catch (error) {{ invalid = error.name; }}
          const unchanged = localStorage.getItem("pcn:review:" + id) === before;
          return [launched.applied, launched.review.dimensions.cost_realism,
                  stale, ok.applied, ok.review.dimensions.cost_realism.status,
                  invalid, unchanged, R.items(ok.review).length];
        }})()"""
    )

    assert results == [
        True,
        {"status": "pending", "generation": 1},
        {"applied": False, "reason": "stale"},
        True,
        "ok",
        "ReviewInvariantError",
        True,
        9,
    ]


def test_a_write_to_a_deleted_or_unreadable_review_is_refused(
    store_page: Page,
) -> None:
    gone = create(store_page)["id"]
    broken = create(store_page)["id"]
    refusals = store_page.js(
        f"""(() => {{
          const R = window.pcnReviews;
          R.deleteReview({json.dumps(gone)});
          localStorage.setItem("pcn:review:" + {json.dumps(broken)}, "{{not json");
          return [R.launchItem({json.dumps(gone)}, "dimension", "cost_realism", 0),
                  R.launchItem({json.dumps(broken)}, "dimension", "cost_realism", 0),
                  R.getReview({json.dumps(gone)}), R.getReview({json.dumps(broken)}),
                  localStorage.getItem("pcn:review:" + {json.dumps(gone)})];
        }})()"""
    )

    assert refusals == [
        {"applied": False, "reason": "missing"},
        {"applied": False, "reason": "unreadable"},
        {"status": "missing"},
        {
            "status": "unreadable",
            "message": "This review's stored data is corrupt and cannot be opened.",
        },
        None,
    ]


def test_the_listing_reports_what_it_cannot_read(store_page: Page) -> None:
    kept = create(store_page)["id"]
    listing = store_page.js(
        """(() => {
          const index = JSON.parse(localStorage.getItem("pcn:reviews"));
          index.push({schemaVersion: 3, id: "future"});
          index.push({...index[0], id: "lost"});
          index.push("junk");
          localStorage.setItem("pcn:reviews", JSON.stringify(index));
          const listing = window.pcnReviews.listReviews();
          return [listing.entries.map((e) => e.id), listing.unreadable];
        })()"""
    )

    assert listing == [
        [kept],
        [
            {
                "id": "future",
                "reason": "This review was saved by a different version of the app "
                "and cannot be opened.",
            },
            {"id": "lost", "reason": "This review's stored data is missing."},
            {"reason": "This review's stored data is corrupt and cannot be opened."},
        ],
    ]
    store_page.js("localStorage.setItem('pcn:reviews', '{}'); true")
    assert store_page.js("window.pcnReviews.listReviews()") == {
        "entries": [],
        "unreadable": [{"reason": "The review index could not be read."}],
    }


def test_a_failed_index_write_puts_the_payload_back(store_page: Page) -> None:
    review_id = create(store_page)["id"]
    outcome = store_page.js(
        f"""(() => {{
          const key = "pcn:review:" + {json.dumps(review_id)};
          const before = localStorage.getItem(key);
          const proto = Object.getPrototypeOf(localStorage);
          const set = proto.setItem;
          proto.setItem = function (name, value) {{
            if (name === "pcn:reviews") {{
              throw new DOMException("full", "QuotaExceededError");
            }}
            return set.call(this, name, value);
          }};
          let thrown = null;
          try {{
            window.pcnReviews.launchItem(
              {json.dumps(review_id)}, "dimension", "cost_realism", 0);
          }} catch (error) {{ thrown = [error.name, error.kind]; }}
          finally {{ proto.setItem = set; }}
          return [thrown, localStorage.getItem(key) === before];
        }})()"""
    )

    assert outcome == [["StoreError", "quota"], True]


def test_the_summary_saves_into_the_latest_record(store_page: Page) -> None:
    review_id = create(store_page)["id"]
    saved = store_page.js(
        f"""(() => {{
          const R = window.pcnReviews, id = {json.dumps(review_id)};
          R.launchItem(id, "criterion", "environmental_impact", 0);
          const record = R.saveSummary(id, "Fundable.");
          return [record.reviewerSummary, record.mca.criteria.environmental_impact];
        }})()"""
    )

    assert saved == ["Fundable.", {"status": "pending", "generation": 1}]


def test_delete_removes_the_payload_then_unreadable_entries_too(
    store_page: Page,
) -> None:
    store_page.js(
        """(() => {
          const old = {schemaVersion: 1, id: "old"};
          localStorage.setItem("pcn:reviews", JSON.stringify([old]));
          localStorage.setItem("pcn:review:old", "{}");
          window.pcnReviews.deleteReview("old");
          return true;
        })()"""
    )

    assert store_page.js("localStorage.getItem('pcn:review:old')") is None
    assert store_page.js("JSON.parse(localStorage.getItem('pcn:reviews'))") == []


def test_a_result_lands_only_on_an_item_still_pending_at_its_generation(
    store_page: Page,
) -> None:
    review_id = create(store_page)["id"]
    outcomes = store_page.js(
        f"""(() => {{
          const R = window.pcnReviews, id = {json.dumps(review_id)};
          const record = R.getReview(id).review;
          const ok = (generation) => ({{status: "ok", generation,
            finding: window.__finding(record, "cost_realism")}});
          const failed = {{status: "error", generation: 1, errorMessage: "x",
            error: {{kind: "retryable", code: "provider_error"}}}};
          R.launchItem(id, "dimension", "cost_realism", 0);
          const early = R.writeResult(id, "dimension", "cost_realism", 0, ok(0));
          const landed = R.writeResult(id, "dimension", "cost_realism", 1, ok(1));
          const again = R.writeResult(id, "dimension", "cost_realism", 1, failed);
          R.writeItem(id, "dimension", "cost_realism", 1,
            Object.assign(ok(2), {{disposition: {{kind: "accepted"}}}}));
          const decided = R.writeResult(id, "dimension", "cost_realism", 2, failed);
          return [early.reason, landed.applied, again.reason, decided.reason,
                  R.getReview(id).review.dimensions.cost_realism.disposition];
        }})()"""
    )

    assert outcomes == ["stale", True, "stale", "stale", {"kind": "accepted"}]


def test_a_payload_that_cannot_be_read_back_is_never_written_over(
    store_page: Page,
) -> None:
    review_id = create(store_page)["id"]
    outcome = store_page.js(
        f"""(() => {{
          const key = "pcn:review:" + {json.dumps(review_id)};
          const before = localStorage.getItem(key);
          const proto = Object.getPrototypeOf(localStorage);
          const get = proto.getItem;
          let reads = 0;
          proto.getItem = function (name) {{
            if (name === key && ++reads > 1) throw new Error("denied");
            return get.call(this, name);
          }};
          let thrown = null;
          try {{
            window.pcnReviews.launchItem(
              {json.dumps(review_id)}, "dimension", "cost_realism", 0);
          }} catch (error) {{ thrown = error.message; }}
          finally {{ proto.getItem = get; }}
          return [thrown, localStorage.getItem(key) === before];
        }})()"""
    )

    assert outcome == [
        "The stored review could not be read; refusing to write over it.",
        True,
    ]
