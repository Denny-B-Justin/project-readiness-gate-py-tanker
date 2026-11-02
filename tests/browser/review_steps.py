"""Steps shared by the review browser tests: a review's creation input
frozen from the default project, hooks that record what the session does,
submitting the default project, reading the stored record back, waiting for
a session to go idle, and writing to the run's inbox as the server does."""

from __future__ import annotations

import json
from typing import Any

from pcn_clone.ai import build_snapshot
from pcn_clone.app.projects_data import default_project_values
from pcn_clone.app.review.submit import submission_from_values
from pcn_clone.content import load_assessment, load_mca
from tests.browser.form_steps import open_default
from tests.browser.harness import Page, url_param

SNAPSHOT = build_snapshot(submission_from_values(default_project_values())).to_json()

INPUT = {
    "projectId": "p-1",
    "projectTitle": "Upper Valley District Road Rehabilitation",
    "templateId": SNAPSHOT["templateId"],
    "templateLabel": SNAPSHOT["templateLabel"],
    "templateVersion": SNAPSHOT["templateVersion"],
    "sourceProjectTemplateVersion": "1.4.0",
    "assessmentSetId": SNAPSHOT["assessmentSetId"],
    "assessmentSetVersion": SNAPSHOT["assessmentSetVersion"],
    "model": SNAPSHOT["model"],
    "assessmentInputDigest": SNAPSHOT["assessmentInputDigest"],
    "dimensionDefs": SNAPSHOT["dimensionDefs"],
    "fields": SNAPSHOT["fields"],
    "submission": SNAPSHOT["submission"],
    "mca": {
        "setId": SNAPSHOT["mcaSetId"],
        "setVersion": SNAPSHOT["mcaSetVersion"],
        "matrix": SNAPSHOT["matrix"],
    },
}
"""A ``pcnReviews.createReview`` input for the default project, as Submit
builds it."""

DIMENSIONS = [d.id for d in load_assessment().dimensions]
CRITERIA = [c.id for c in load_mca().matrix.criteria]
ITEMS = [("dimension", d) for d in DIMENSIONS] + [("criterion", c) for c in CRITERIA]

ON_REVIEW_URL = "location.search.startsWith('?page=review&review_id=')"
"""True once the address is a review's page."""

STATUS = "(document.getElementById('rv-status') || {}).textContent || ''"
LANDED = f"(({STATUS}) && !({STATUS}).startsWith('Drafting'))"

HOOKS = """(() => {
  window.__created = null;
  window.__launches = [];
  window.__inbox = [];
  const reviews = window.pcnReviews;
  const create = reviews.createReview;
  reviews.createReview = (input) => (window.__created = create(input));
  const ns = window.dash_clientside.pcnReview;
  const receive = ns.receive;
  ns.receive = function (list, ...rest) {
    if (Array.isArray(list)) window.__inbox = list;
    return receive.call(this, list, ...rest);
  };
  const set = window.dash_clientside.set_props;
  const seen = new Set();
  window.dash_clientside.set_props = (id, props) => {
    if (id === "rv-launch") {
      for (const request of props.data) {
        if (!seen.has(request.nonce)) {
          seen.add(request.nonce);
          window.__launches.push(request);
        }
      }
    }
    return set(id, props);
  };
  return true;
})()"""
"""Records the created review, every run request sent and the inbox."""


def stored(page: Page, review_id: str) -> dict[str, Any]:
    record: dict[str, Any] = page.js(
        f"JSON.parse(localStorage.getItem('pcn:review:{review_id}'))"
    )
    return record


def states(record: dict[str, Any]) -> dict[str, tuple[str, int]]:
    """``{item id: (status, generation)}`` across dimensions and criteria."""
    items = {**record["dimensions"], **record["mca"]["criteria"]}
    return {key: (state["status"], state["generation"]) for key, state in items.items()}


def status(page: Page) -> str:
    return str(page.js(STATUS))


def submit_default(page: Page) -> str:
    """Open the default project, submit it and return the new review's id."""
    open_default(page)
    page.js(HOOKS)
    page.click("#pf-submit")
    page.wait_for(ON_REVIEW_URL, timeout=15)
    return str(page.js(url_param("review_id")))


def wait_idle(
    page: Page, review_id: str, timeout: float = 15, *, on_page: bool = True
) -> None:
    """Wait until the review has no run unsettled and no summary unsaved
    and, ``on_page``, its page has mounted the session."""
    quoted = json.dumps(review_id)
    mounted = (
        f"(window.pcnReview.record() || {{}}).id === {quoted} && " if on_page else ""
    )
    page.wait_for(f"{mounted}window.pcnReview.idle({quoted})", timeout=timeout)


def post(page: Page, *messages: dict[str, Any]) -> None:
    """Append ``messages`` to the run's inbox in one tick, as the server's
    writes can arrive."""
    writes = "".join(
        "window.dash_clientside.set_props('rv-inbox', {data: "
        f"new window.dash_clientside.Patch().append([], {json.dumps(m)}).build()}});"
        for m in messages
    )
    page.js(f"(() => {{ {writes} return true; }})()")


def result(
    review_id: str, kind: str, item_id: str, generation: int, response: dict[str, Any]
) -> dict[str, Any]:
    """A run's result message for one item."""
    return {
        "type": "result",
        "reviewId": review_id,
        "nonce": "test",
        "kind": kind,
        "itemId": item_id,
        "generation": generation,
        "response": response,
    }


FAILED = {
    "ok": False,
    "errorMessage": "Late.",
    "error": {"kind": "retryable", "code": "provider_error"},
}


def decide(
    page: Page,
    review_id: str,
    kind: str,
    item: str,
    generation: int,
    disposition: dict[str, Any],
) -> Any:
    """Record a decision through the session API; true when stored."""
    return page.js(
        f"window.pcnReview.decide({json.dumps(review_id)}, {json.dumps(kind)}, "
        f"{json.dumps(item)}, {generation}, {json.dumps(disposition)})"
    )


def toasts(page: Page) -> list[str]:
    found: list[str] = page.js(
        "[...document.querySelectorAll('.mantine-Notification-root')]"
        ".map((n) => n.textContent)"
    )
    return found
