"""The review session: the record, its run and the reviewer's decisions.

Submit (on the proposer's Concept Note) freezes the answers into a review
record held in the browser (``assets/review-store.js``, ``window.pcnReviews``)
and opens its page (``?page=review&review_id=…``). There
``assets/review.js`` (``window.pcnReview``) mounts the session, starts the
run, merges each result into the record, and publishes the record and its
derived state into the page's stores. Python never reads the browser's
storage; it renders from those stores.

Stores (``pcn_clone.app.review.ids``):

- ``rv-record``: the open review's validated record (the stored record, with
  an item shown as failed when its failure could not be stored, and
  ``reviewerSummary`` holding the live text). Shape:
  ``{schemaVersion: 2, id, createdISO, editedISO, projectId, projectTitle,
  templateId, templateLabel, templateVersion, sourceProjectTemplateVersion,
  assessmentSetId, assessmentSetVersion, model, assessmentInputDigest,
  dimensionDefs, fields, submission, dimensions: {id: state}, mca: {setId,
  setVersion, matrix, criteria: {id: state}}, reviewerSummary}``. An item
  state is ``{status: "pending", generation}``, ``{status: "error",
  generation, errorMessage, error: {kind: "retryable" | "terminal",
  code}}``, or ``{status: "ok", generation, finding | scoreFinding,
  disposition?}`` (``finding`` for dimensions, ``scoreFinding`` for
  criteria).
- ``rv-summary``: ``{reviewId, persisted, saveFailed, lastSavedISO}``.
- ``rv-completion``: ``{ready, reasons, status, drafting}``, the reasons in
  fixed order (:mod:`pcn_clone.app.review.completion`) and ``status`` the
  context bar's line.
- ``rv-part``: written by the workspace, ``{"key", "title"}`` of the opened
  component or ``None`` on the hub; the breadcrumb follows it and its
  project crumb sets it back to ``None``.
- ``rv-launch`` and ``rv-inbox`` (in the app shell): the run's two
  channels, private to ``review.js`` and :mod:`pcn_clone.app.review.run`.

Item kinds are ``"dimension"`` and ``"criterion"``. Every change to a
review sets the open page's ``rv-record``, ``rv-summary`` and
``rv-completion`` together (when that review is the one in view) and then
dispatches ``pcn:review-changed`` on ``window`` with ``{reviewId}``, for any
review, including one whose run is still landing while the reviewer is
elsewhere; render from the stores' ``data`` (or listen for the event in the
browser, checking ``reviewId``).

Browser API, ``window.pcnReview`` (each call acts on the stored record, not
on a rendered copy):

- ``decide(reviewId, kind, itemId, generation, disposition)``: record the
  reviewer's decision on an ``ok`` item whose state is at ``generation``
  (``null`` clears it). Writes at ``generation + 1`` by compare-and-swap and
  refreshes the stores; returns ``true`` when the decision is stored. A
  superseded or failed write returns ``false`` and says why in a toast, so
  an editor keeps the reviewer's work open. A dimension disposition is
  ``{kind: "accepted", note?}``, ``{kind: "edited", finalVerdict, finalText,
  evidence: [{sectionId, fieldId, quote?, note?}], note?}`` or ``{kind:
  "dismissed", note?}``; a criterion's is ``{kind: "accepted", note?}`` or
  ``{kind: "adjusted", finalScore, rationale, basis: {kind: "documented",
  evidence: [...]} | {kind: "not_evidenced"}}``.
- ``retry(reviewId, kind, itemId)``: re-launch one item whose error is
  retryable; returns ``true`` when launched.
- ``changeSummary(reviewId, text)``: the summary as typed; it is saved 800
  ms after the last change (at once when the page is hidden or left), and
  ``rv-summary`` follows. ``summaryState(reviewId)`` reads the same state
  with the live ``text``.
- ``completion(record, summary)`` and ``status(record, summary)``: the pure
  functions behind ``rv-completion``, ``summary`` being ``{text, persisted,
  saveFailed}``.
- ``idle(reviewId)``: ``true`` when the review has no run unsettled and no
  summary waiting to be saved.
- ``record()``: the published record of the review page in view, or
  ``null``.

``window.pcnReview`` is defined when ``review.js`` loads, after
``review-ui.js``; reach it at call time, not at load.

The store itself, ``window.pcnReviews``, is documented at the top of
``assets/review-store.js``.

Importing this package registers the session's callbacks.
"""

from __future__ import annotations

from pcn_clone.app.review import callbacks as callbacks
from pcn_clone.app.review.run import run_stores
from pcn_clone.app.review.view import review_view

__all__ = ["review_view", "run_stores"]
