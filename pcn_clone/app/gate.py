"""A client-side gate for pages that show one record held in the browser.

The server cannot read the browser's storage, so a gated page opens in a
checking state. A clientside check (``pcnGate.check`` in ``assets/gate.js``)
looks the record up, requires the expected fields to match, and answers into
a state store; a Python callback renders that answer as the record's view or
a not-found panel (or, for a record that exists but cannot be read, an
unreadable panel). Nothing that writes to the store mounts before the gate
reports the record exists.

A page builds its body with ``gate_container`` and registers the pair of
callbacks once with ``register_gate``; ids are derived from a prefix, so each
gated page gets its own ``<prefix>-gate-request``, ``<prefix>-gate`` and
``<prefix>-gate-body``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from dash import (
    ClientsideFunction,
    Input,
    Output,
    callback,
    clientside_callback,
    dcc,
    html,
)
from dash.development.base_component import Component

GateView = Component | list[Component]
"""What a gate renders into its body."""


def gate_container(
    prefix: str,
    *,
    record_type: str,
    record_id: str | None,
    expect: dict[str, str],
    fields: list[str],
    checking: Component,
) -> html.Div:
    """The gate's request and state stores and its body, which opens showing
    ``checking``. The check passes when a ``record_type`` record with id
    ``record_id`` exists and every ``expect`` field matches; only ``fields``
    of the record reach Python."""
    request = {
        "type": record_type,
        "id": record_id,
        "expect": expect,
        "fields": fields,
    }
    return html.Div(
        className="gate",
        children=[
            dcc.Store(id=f"{prefix}-gate-request", storage_type="memory", data=request),
            dcc.Store(id=f"{prefix}-gate", storage_type="memory"),
            html.Div(id=f"{prefix}-gate-body", children=checking),
        ],
    )


def register_gate(
    prefix: str,
    *,
    found: Callable[[dict[str, Any]], GateView],
    missing: Callable[[], GateView],
    checking: Callable[[], GateView],
    unreadable: Callable[[str], GateView] | None = None,
) -> Callable[[dict[str, Any] | None], GateView]:
    """Register the clientside check and the Python render for the gate with
    ids under ``prefix``. ``found`` receives the record's requested fields;
    ``unreadable``, when given, the lookup's message for a record that
    cannot be read (without it, such a record renders as ``missing``).
    Returns the render function."""
    clientside_callback(
        ClientsideFunction(namespace="pcnGate", function_name="check"),
        Output(f"{prefix}-gate", "data"),
        Input(f"{prefix}-gate-request", "data"),
    )

    def render(state: dict[str, Any] | None) -> GateView:
        if not state:
            return checking()
        record = state.get("record")
        if state.get("status") == "ok" and isinstance(record, dict):
            return found(record)
        message = state.get("message")
        if unreadable is not None and state.get("status") == "unreadable":
            return unreadable(message if isinstance(message, str) else "")
        return missing()

    render.__doc__ = f"The body of the {prefix} gate for its check's answer."
    callback(
        Output(f"{prefix}-gate-body", "children"),
        Input(f"{prefix}-gate", "data"),
        prevent_initial_call=True,
    )(render)
    return render
