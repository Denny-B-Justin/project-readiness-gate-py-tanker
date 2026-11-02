"""The proposer workspace: the Concept Note form with per-field AI feedback.

The project page renders :func:`form_view` once its gate finds the project.
The answers belong to the browser: ``assets/form.js`` restores the saved
draft over every field's blank default, mirrors each edit into the
``form-values`` memory store and autosaves the draft through
``window.pcnStore`` (500 ms after the last edit; a pending save is written
at once when the page is hidden or left, or the app navigates elsewhere).
Live figures (worksheet totals, scenario differences, inert table rows) are
computed there too, with ``assets/numbers.js`` reproducing
``pcn_clone.core.numbers``. Evaluation and readiness go through the server
callbacks in :mod:`pcn_clone.app.form.callbacks`; feedback is held in memory
only and is gone after a reload.

Importing this package registers those callbacks.

Reading the answers: a server callback takes ``State("form-values",
"data")``, the flat ``{field id: answer}`` map in stored shapes; in the
browser, once ``window.pcnForm.hydrated()`` is true,
``window.pcnForm.snapshot()`` returns a deep copy of the same map.
"""

from __future__ import annotations

from pcn_clone.app.form import callbacks as callbacks
from pcn_clone.app.form.layout import form_view

__all__ = ["form_view"]
