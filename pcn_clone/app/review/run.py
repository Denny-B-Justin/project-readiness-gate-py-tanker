"""The review run: a review's pending items drafted in parallel.

The browser keeps its run requests in the ``rv-launch`` list, each
``{reviewId, nonce, items: [{kind, id, generation}], request}`` with every
item already moved to ``pending`` at that generation in the stored record
and ``request`` carrying the record's pins (``templateId``,
``templateVersion``, ``assessmentSetId``, ``assessmentSetVersion``,
``mcaSetId``, ``mcaSetVersion``, ``model``, ``assessmentInputDigest``,
``submission``). :func:`run_review`, a WebSocket callback, runs every
request it has not run before (``REGISTRY`` remembers the nonces) and
answers on the ``rv-inbox`` list, appending messages that carry the
request's ``reviewId`` and ``nonce``:

- ``started`` as it begins, so the browser stops resending the request;
- ``result`` with ``kind``, ``itemId``, ``generation`` and ``response`` as
  each item's call returns, ``response`` being the engine's JSON or, when
  the call itself failed, a retryable ``transport_error``;
- ``heartbeat`` with ``at`` every ``heartbeat_seconds()`` while calls are
  still running;
- ``done`` when every item has been answered.

Every item of a review is called at once, at most ``RUN_CONCURRENCY`` per
review. When the connection closes, Dash cancels the run with its calls;
the browser notices the heartbeats stop and fails the items it was waiting
on as retryable. Both lists live in the app shell (:func:`run_stores`), so
results keep reaching the browser's store while the reviewer is on another
page, for any item the record names.

Nothing here limits how long a call takes: each model call is bounded by
the AI layer's own deadline. The WebSocket must stay open across the
longest of those calls, so the app sets its inactivity timeout to
``WEBSOCKET_INACTIVITY_TIMEOUT_MS``.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, TypeGuard

from dash import Input, Patch, callback, dcc, html, set_props

from pcn_clone.ai import assess_dimension, score_criterion
from pcn_clone.ai.provider import DEADLINE_CAP_SECONDS
from pcn_clone.app.review import ids, messages
from pcn_clone.app.review.config import client_config, heartbeat_seconds
from pcn_clone.app.review.ids import ITEM_KINDS, ItemKind

logger = logging.getLogger(__name__)

RUN_CONCURRENCY: Final = 9
"""Calls one review runs at once: every dimension and criterion together."""

WEBSOCKET_INACTIVITY_TIMEOUT_MS: Final = int((DEADLINE_CAP_SECONDS + 60) * 1000)
"""How long the browser keeps a silent WebSocket open: past the AI layer's
longest possible call (retries included), so a run waiting on it is not
cut off."""

REMEMBERED_NONCES: Final = 4096
"""How many run requests the registry remembers as already run."""

PINS: Final = {
    "dimension": ("assessmentSetId", "assessmentSetVersion"),
    "criterion": ("mcaSetId", "mcaSetVersion"),
}
"""The set pins each kind of request carries beside the shared ones."""

SHARED_PINS: Final = (
    "templateId",
    "templateVersion",
    "model",
    "assessmentInputDigest",
)

ITEM_ID_KEY: Final = {"dimension": "dimensionId", "criterion": "criterionId"}

Envelope = dict[str, Any]
"""An engine's response JSON: ``{ok, finding}`` or ``{ok, errorMessage,
error}``."""

Message = dict[str, Any]
"""One message on the inbox."""

Engine = Callable[[Mapping[str, Any]], Awaitable[Envelope]]
Post = Callable[[Message], None]


async def _assess(request: Mapping[str, Any]) -> Envelope:
    return (await assess_dimension(request)).to_json()


async def _score(request: Mapping[str, Any]) -> Envelope:
    return (await score_criterion(request)).to_json()


ENGINES: Final[Mapping[ItemKind, Engine]] = {
    "dimension": _assess,
    "criterion": _score,
}


@dataclass(frozen=True, slots=True)
class RunItem:
    """One item to draft, at the generation its launch stored."""

    kind: ItemKind
    id: str
    generation: int


@dataclass(frozen=True, slots=True)
class Launch:
    """A run request: the review, its items and the record's pins."""

    review_id: str
    nonce: str
    items: tuple[RunItem, ...]
    request: Mapping[str, Any]


def _is_generation(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _run_item(raw: Any) -> RunItem | None:
    if not isinstance(raw, Mapping):
        return None
    kind, item_id, generation = raw.get("kind"), raw.get("id"), raw.get("generation")
    if kind not in ITEM_KINDS or not isinstance(item_id, str) or not item_id:
        return None
    return RunItem(kind, item_id, generation) if _is_generation(generation) else None


def parse_launch(data: Any) -> Launch | None:
    """The run request in ``data``, or ``None`` when it is malformed or has
    no items."""
    if not isinstance(data, Mapping):
        return None
    review_id, nonce = data.get("reviewId"), data.get("nonce")
    raw_items, request = data.get("items"), data.get("request")
    if not (isinstance(review_id, str) and review_id):
        return None
    if not (isinstance(nonce, str) and nonce):
        return None
    if not (isinstance(raw_items, list) and raw_items and isinstance(request, Mapping)):
        return None
    items = [_run_item(raw) for raw in raw_items]
    if any(item is None for item in items):
        return None
    return Launch(review_id, nonce, tuple(i for i in items if i is not None), request)


def item_request(launch: Launch, item: RunItem) -> dict[str, Any]:
    """The engine request for one item: the shared pins, its kind's set pins,
    its id and the submission."""
    request = launch.request
    keys = (*SHARED_PINS, *PINS[item.kind])
    built = {key: request[key] for key in keys if key in request}
    built[ITEM_ID_KEY[item.kind]] = item.id
    if "submission" in request:
        built["submission"] = request["submission"]
    return built


def transport_failure(kind: ItemKind) -> Envelope:
    """The response for a call that never completed."""
    return {
        "ok": False,
        "errorMessage": messages.TRANSPORT_FAILURE[kind],
        "error": {"kind": "retryable", "code": "transport_error"},
    }


@dataclass(slots=True)
class RunRegistry:
    """The run requests this process has run, and each review's limit on
    concurrent calls (kept while any of its runs is active)."""

    width: int = RUN_CONCURRENCY
    _seen: OrderedDict[str, None] = field(default_factory=OrderedDict, init=False)
    _limits: dict[str, asyncio.Semaphore] = field(default_factory=dict, init=False)
    _active: dict[str, int] = field(default_factory=dict, init=False)

    def admit(self, nonce: str) -> bool:
        """True the first time a request's ``nonce`` is seen: a request
        delivered again is not run again."""
        if nonce in self._seen:
            return False
        self._seen[nonce] = None
        if len(self._seen) > REMEMBERED_NONCES:
            self._seen.popitem(last=False)
        return True

    @asynccontextmanager
    async def review(self, review_id: str) -> AsyncIterator[asyncio.Semaphore]:
        """The review's call limit, held for the length of one run."""
        limit = self._limits.setdefault(review_id, asyncio.Semaphore(self.width))
        self._active[review_id] = self._active.get(review_id, 0) + 1
        try:
            yield limit
        finally:
            self._active[review_id] -= 1
            if not self._active[review_id]:
                del self._active[review_id]
                del self._limits[review_id]

    def active(self, review_id: str) -> int:
        """How many runs of the review are under way."""
        return self._active.get(review_id, 0)


REGISTRY: Final = RunRegistry()
"""The process's run registry."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def run_launch(
    launch: Launch,
    post: Post,
    *,
    registry: RunRegistry = REGISTRY,
    engines: Mapping[ItemKind, Engine] = ENGINES,
    heartbeat: float | None = None,
) -> None:
    """Run every item of ``launch`` at once, within the review's limit,
    posting ``started``, each ``result`` as it returns, a ``heartbeat``
    every ``heartbeat`` seconds (default :func:`heartbeat_seconds`) while
    calls run, and ``done``.

    An engine that raises yields the item's ``transport_error`` response.
    Cancelled (the connection closed), the run cancels its calls and posts
    nothing more.
    """
    interval = heartbeat_seconds() if heartbeat is None else heartbeat
    frame = {"reviewId": launch.review_id, "nonce": launch.nonce}
    post({**frame, "type": "started"})

    async def beat() -> None:
        while True:
            await asyncio.sleep(interval)
            post({**frame, "type": "heartbeat", "at": _now()})

    async with registry.review(launch.review_id) as limit:

        async def run_one(item: RunItem) -> tuple[RunItem, Envelope]:
            async with limit:
                try:
                    envelope = await engines[item.kind](item_request(launch, item))
                except Exception:
                    logger.exception('Review item "%s/%s" failed', item.kind, item.id)
                    envelope = transport_failure(item.kind)
            return item, envelope

        tasks = [asyncio.create_task(run_one(item)) for item in launch.items]
        beating = asyncio.create_task(beat())
        try:
            for finished in asyncio.as_completed(tasks):
                item, envelope = await finished
                post(
                    {
                        **frame,
                        "type": "result",
                        "kind": item.kind,
                        "itemId": item.id,
                        "generation": item.generation,
                        "response": envelope,
                    }
                )
        finally:
            beating.cancel()
            for task in tasks:
                task.cancel()
            await asyncio.gather(beating, *tasks, return_exceptions=True)
    post({**frame, "type": "done"})


def post_to_inbox(message: Message) -> None:
    """Append ``message`` to the browser's inbox."""
    appended = Patch()
    appended.append(message)
    set_props(ids.INBOX, {"data": appended})


@callback(Input(ids.LAUNCH, "data"), prevent_initial_call=True, websocket=True)
async def run_review(requests: Any) -> None:
    """Run each request in the browser's outbox not run before, answering on
    the inbox."""
    launches = [
        launch
        for raw in (requests if isinstance(requests, list) else [])
        if (launch := parse_launch(raw)) is not None and REGISTRY.admit(launch.nonce)
    ]
    await asyncio.gather(*(run_launch(launch, post_to_inbox) for launch in launches))


def run_stores() -> html.Div:
    """The stores a run needs wherever the reviewer is: the configuration,
    the browser's outbox and its inbox."""
    return html.Div(
        hidden=True,
        children=[
            dcc.Store(id=ids.CONFIG, data=client_config()),
            dcc.Store(id=ids.LAUNCH, data=[]),
            dcc.Store(id=ids.INBOX, data=[]),
        ],
    )
