"""The review session's callbacks, registered once when this module is
imported.

Clientside (``dash_clientside.pcnReview`` in ``assets/review.js``):

- ``mount``: when a review page renders ``rv-session``, read the record,
  launch every pending item not already running in this browser session,
  fill ``rv-record`` and publish ``rv-run``, ``rv-summary``,
  ``rv-completion`` and the status line (``review.js`` sets all of them
  again on every later change);
- ``receive``: read the run's new messages on the inbox: merge each
  result into the stored record by compare-and-swap on its pending
  generation, and settle what a finished run never answered;
- ``crumbs``: the breadcrumb follows the open workspace component
  (``rv-part``), and ``backToHub`` closes it from the project crumb.

The run (:mod:`pcn_clone.app.review.run`) and Submit
(:mod:`pcn_clone.app.review.submit`) register their own.
"""

from __future__ import annotations

from dash import ClientsideFunction, Input, Output, State, clientside_callback

from pcn_clone.app.review import ids
from pcn_clone.app.review import run as run
from pcn_clone.app.review import submit as submit

clientside_callback(
    ClientsideFunction(namespace="pcnReview", function_name="mount"),
    Output(ids.RECORD, "data"),
    Input(ids.SESSION, "data"),
    State(ids.CONFIG, "data"),
)

clientside_callback(
    ClientsideFunction(namespace="pcnReview", function_name="receive"),
    Input(ids.INBOX, "data"),
    State(ids.CONFIG, "data"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="pcnReview", function_name="backToHub"),
    Output(ids.PART, "data", allow_duplicate=True),
    Input(ids.CRUMB_BACK, "n_clicks"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="pcnReview", function_name="crumbs"),
    Output(ids.CRUMB_TITLE, "hidden"),
    Output(ids.CRUMB_BACK, "hidden"),
    Output(ids.CRUMB_TAIL, "hidden"),
    Output(ids.CRUMB_PART, "children"),
    Input(ids.PART, "data"),
)
