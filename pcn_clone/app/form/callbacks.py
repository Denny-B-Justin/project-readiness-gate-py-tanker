"""The workspace's callbacks, registered once when this module is imported.

Server callbacks:

- ``evaluate`` (one per field card, by pattern matching): form.js starts an
  evaluation by writing ``{"answer", "context", "n"}`` to the field's
  ``pf-evaluate-request`` store, the snapshot it also takes the answer's
  signature from. The callback refuses an answer that is not ready
  (``pcn_clone.ai.is_field_ready``) without a model call; otherwise it awaits
  ``pcn_clone.ai.evaluate_field`` and writes the response, with ``n``, to the
  field's ``pf-evaluation`` store. While it runs, ``running`` disables the
  button and raises the field's ``pf-evaluating`` flag. Several fields can
  run at once: at most ``MAX_CONCURRENT_EVALUATIONS`` per project, and
  ``MAX_PROCESS_EVALUATIONS`` across the process, call the model together;
  the rest wait their turn (still showing "Evaluating…").
- ``check_readiness`` (one for the whole workspace): form.js writes to the
  ``pf-readiness-request`` store the answer of every field whose readiness
  the server decides and is still owed: all of them when the workspace
  mounts, then each edited field once its edits settle. Each request carries
  every field still waiting, so when a newer request supersedes one in
  flight (Dash keeps only the latest response) nothing is lost. The answer,
  in ``pf-readiness``, comes from ``pcn_clone.ai.readiness`` (the issues,
  empty exactly when the field is ready), and each requested field's
  "Complete the following before evaluating" panel is redrawn.

Clientside callbacks (``dash_clientside.pcnForm`` in ``assets/form.js``)
mount the workspace (restoring the draft into ``form-values``), open the
guidance and criteria dialogs, and hand evaluation and readiness changes to
form.js, which draws the footers and tallies.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final
from weakref import WeakValueDictionary

from dash import (
    ALL,
    MATCH,
    ClientsideFunction,
    Input,
    Output,
    State,
    callback,
    clientside_callback,
    no_update,
)

from pcn_clone.ai import evaluate_field, is_field_ready, readiness
from pcn_clone.app.form.config import LOCAL_READINESS_KINDS, field_default
from pcn_clone.app.form.field_card import issues_panel
from pcn_clone.app.form.ids import (
    CONFIG,
    CRITERIA_DIALOG,
    CRITERIA_OPEN,
    EVALUATE,
    EVALUATE_REQUEST,
    EVALUATING,
    EVALUATION,
    FORM_VALUES,
    GUIDANCE_DIALOG,
    GUIDANCE_OPEN,
    ISSUES,
    PROJECT,
    READINESS,
    READINESS_REQUEST,
)
from pcn_clone.app.form.messages import NOT_READY, TRANSPORT_FAILURE
from pcn_clone.app.form.template import find_field

MAX_CONCURRENT_EVALUATIONS: Final = 4
"""Model calls one project runs at a time."""

MAX_PROCESS_EVALUATIONS: Final = 16
"""Model calls the whole process runs at a time, whatever the projects."""

_process_limit = asyncio.Semaphore(MAX_PROCESS_EVALUATIONS)
_project_limits: WeakValueDictionary[str, asyncio.Semaphore] = WeakValueDictionary()


def _project_limit(project_id: str) -> asyncio.Semaphore:
    """The semaphore shared by one project's running evaluations; it lasts
    while any evaluation holds it."""
    limit = _project_limits.get(project_id)
    if limit is None:
        limit = asyncio.Semaphore(MAX_CONCURRENT_EVALUATIONS)
        _project_limits[project_id] = limit
    return limit


def _refusal(
    field_id: str,
    message: str,
    n: Any,
    *,
    section_id: str = "",
    retryable: bool = False,
    issues: list[str] | None = None,
) -> dict[str, Any]:
    """A failed response in the evaluation's wire shape, with ``n``."""
    return {
        "ok": False,
        "sectionId": section_id,
        "fieldId": field_id,
        "errorMessage": message,
        "issues": issues or [],
        "retryable": retryable,
        "n": n,
    }


@callback(
    Output({"type": EVALUATION, "field": MATCH}, "data"),
    Input({"type": EVALUATE_REQUEST, "field": MATCH}, "data"),
    State({"type": EVALUATE_REQUEST, "field": MATCH}, "id"),
    State(PROJECT, "data"),
    running=[
        (Output({"type": EVALUATE, "field": MATCH}, "disabled"), True, False),
        (Output({"type": EVALUATING, "field": MATCH}, "data"), True, False),
    ],
    prevent_initial_call=True,
)
async def evaluate(
    request: Any, store_id: dict[str, str], project: Any
) -> dict[str, Any]:
    """Evaluate the requested answer of one field. The response is the
    evaluation's wire shape plus ``n``, the request it answers; an answer
    that is not ready comes back with ``notReady`` and its issues, unsent."""
    field_id = store_id["field"]
    request = request if isinstance(request, dict) else {}
    n = request.get("n")
    found = find_field(field_id)
    if found is None:
        return _refusal(field_id, f'Unknown field "{field_id}".', n)
    section, field = found
    answer = request.get("answer", field_default(field))
    context = request.get("context") or None
    if not is_field_ready(section.id, field_id, answer, context):
        issues = readiness(section.id, field_id, answer, context)
        refusal = _refusal(field_id, NOT_READY, n, section_id=section.id, issues=issues)
        return {**refusal, "notReady": True}
    project_id = str(project.get("id", "")) if isinstance(project, dict) else ""
    try:
        async with _project_limit(project_id), _process_limit:
            response = await evaluate_field(section.id, field_id, answer, context)
    except Exception:
        return _refusal(
            field_id, TRANSPORT_FAILURE, n, section_id=section.id, retryable=True
        )
    return {**response.to_json(), "n": n}


def _field_readiness(field_id: str, request: Any) -> dict[str, Any]:
    """``{"ready", "issues", "n"}`` for one field's readiness request
    ``{"answer", "context", "n"}``. For the validator-backed kinds the field
    is ready exactly when its validator reports no issues, so the validator
    runs once; text, textarea and group fields have no issues to list."""
    request = request if isinstance(request, dict) else {}
    n = request.get("n")
    found = find_field(field_id)
    if found is None:
        return {"ready": False, "issues": [f'Unknown field "{field_id}".'], "n": n}
    section, field = found
    answer = request.get("answer", field_default(field))
    context = request.get("context") or None
    if field.kind in LOCAL_READINESS_KINDS:
        ready = is_field_ready(section.id, field_id, answer, context)
        return {"ready": ready, "issues": [], "n": n}
    issues = readiness(section.id, field_id, answer, context)
    return {"ready": not issues, "issues": issues, "n": n}


@callback(
    Output({"type": ISSUES, "field": ALL}, "children"),
    Output(READINESS, "data"),
    Input(READINESS_REQUEST, "data"),
    State({"type": ISSUES, "field": ALL}, "id"),
    prevent_initial_call=True,
)
def check_readiness(
    request: Any, panel_ids: list[dict[str, str]]
) -> tuple[list[Any], dict[str, dict[str, Any]]]:
    """Answer a readiness request ``{field id: {"answer", "context", "n"}}``
    with ``{field id: {"ready", "issues", "n"}}``, and redraw the panel of
    each requested field (shown while it has issues; the panels of fields
    not in the request are left as they are)."""
    requested = request if isinstance(request, dict) else {}
    answers = {
        field_id: _field_readiness(field_id, entry)
        for field_id, entry in requested.items()
    }
    panels: list[Any] = []
    for panel_id in panel_ids:
        answer = answers.get(panel_id["field"])
        if answer is None:
            panels.append(no_update)
        else:
            panels.append(issues_panel(answer["issues"]) if answer["issues"] else None)
    return panels, answers


clientside_callback(
    ClientsideFunction(namespace="pcnForm", function_name="mount"),
    Output(FORM_VALUES, "data"),
    Input(CONFIG, "data"),
    Input(PROJECT, "data"),
)

for _opener, _dialog in (
    (GUIDANCE_OPEN, GUIDANCE_DIALOG),
    (CRITERIA_OPEN, CRITERIA_DIALOG),
):
    clientside_callback(
        ClientsideFunction(namespace="pcnForm", function_name="openDialog"),
        Output({"type": _dialog, "field": MATCH}, "opened"),
        Input({"type": _opener, "field": MATCH}, "n_clicks"),
        prevent_initial_call=True,
    )

clientside_callback(
    ClientsideFunction(namespace="pcnForm", function_name="evaluationChanged"),
    Input({"type": EVALUATION, "field": ALL}, "data"),
    Input({"type": EVALUATING, "field": ALL}, "data"),
    prevent_initial_call=True,
)

clientside_callback(
    ClientsideFunction(namespace="pcnForm", function_name="readinessChanged"),
    Input(READINESS, "data"),
    prevent_initial_call=True,
)
