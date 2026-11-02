"""Submit: a Concept Note frozen into a new review.

The Submit button in the proposer's context bar is ``aria-disabled`` until
the workspace has restored its draft (``pcnForm.hydrated()``); then it is
enabled. If the draft is never restored, the button stays disabled and its
description and the autosave line say why. A click snapshots the answers at
once, in the browser, into the ``pf-submit-request`` store with the
project's id, title and template version, and marks the button busy.
:func:`intake` canonicalizes and serializes the answers into the intake
snapshot (:func:`pcn_clone.ai.build_snapshot`: the canonical submission,
the serialized fields and their digest, the dimension definitions, the MCA
matrix, the model and the set identities). The browser then creates the
review from it, every item pending at generation 0, and opens its page
(``?page=review&review_id=…``). A failure at any step, or no snapshot
within the configured time, is a toast and the button is enabled again (a
snapshot arriving after that is ignored); on success the button stays busy
while the review page takes over.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from dash import ClientsideFunction, Input, Output, State, callback, clientside_callback

from pcn_clone.ai import AiConfigurationError, build_snapshot
from pcn_clone.app.form.ids import (
    AUTOSAVE,
    NAV,
    PROJECT,
    SUBMIT,
    SUBMIT_HINT,
    SUBMIT_REQUEST,
    SUBMIT_SNAPSHOT,
)
from pcn_clone.app.review import ids
from pcn_clone.app.review.messages import SUBMIT_UNEXPECTED
from pcn_clone.content import load_template
from pcn_clone.core.serialize import blank_answer_value

logger = logging.getLogger(__name__)

UNREADABLE_ANSWERS = "The Concept Note's answers could not be read."


def submission_from_values(values: Mapping[str, Any]) -> dict[str, Any]:
    """The submission for a form's ``{field id: answer}`` map: every template
    field once, in template order, an unanswered field as its explicit blank.
    Keys the template does not know are left out."""
    template = load_template()
    return {
        "templateId": template.id,
        "answers": [
            {
                "sectionId": section.id,
                "fieldId": field.id,
                "answer": values[field.id]
                if field.id in values
                else blank_answer_value(field),
            }
            for section, field in template.iter_fields()
        ],
    }


@callback(
    Output(SUBMIT_SNAPSHOT, "data"),
    Input(SUBMIT_REQUEST, "data"),
    prevent_initial_call=True,
)
async def intake(request: Any) -> dict[str, Any]:
    """The intake snapshot for a Submit request, with the request's nonce;
    ``ok: false`` with the reason when the answers cannot be frozen."""
    request = request if isinstance(request, Mapping) else {}
    nonce = request.get("nonce")
    values = request.get("values")
    if not isinstance(values, Mapping):
        return {"nonce": nonce, "ok": False, "errorMessage": UNREADABLE_ANSWERS}
    try:
        snapshot = build_snapshot(submission_from_values(values))
    except (ValueError, AiConfigurationError) as error:
        return {"nonce": nonce, "ok": False, "errorMessage": str(error)}
    except Exception:
        logger.exception("Building the intake snapshot failed")
        return {"nonce": nonce, "ok": False, "errorMessage": SUBMIT_UNEXPECTED}
    return {"nonce": nonce, "ok": True, "intake": snapshot.to_json()}


clientside_callback(
    ClientsideFunction(namespace="pcnReview", function_name="enableSubmit"),
    Output(SUBMIT, "aria-disabled"),
    Output(SUBMIT_HINT, "children"),
    Output(AUTOSAVE, "children"),
    Input(PROJECT, "data"),
    State(ids.CONFIG, "data"),
)

clientside_callback(
    ClientsideFunction(namespace="pcnReview", function_name="startSubmit"),
    Output(SUBMIT_REQUEST, "data"),
    Output(SUBMIT, "aria-disabled", allow_duplicate=True),
    Output(SUBMIT, "aria-busy"),
    Input(SUBMIT, "n_clicks"),
    State(PROJECT, "data"),
    State(ids.CONFIG, "data"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="pcnReview", function_name="finishSubmit"),
    Output(NAV, "href"),
    Output(SUBMIT, "aria-disabled", allow_duplicate=True),
    Output(SUBMIT, "aria-busy", allow_duplicate=True),
    Input(SUBMIT_SNAPSHOT, "data"),
    State(SUBMIT_REQUEST, "data"),
    State(ids.CONFIG, "data"),
    prevent_initial_call=True,
)
