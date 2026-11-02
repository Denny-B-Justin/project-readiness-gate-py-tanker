"""The review run on the server: the request it accepts (never an empty
one), the request it builds per item, the registry that runs a request
once however often it is delivered and bounds each review's concurrent
calls, and the run itself: ``started``, each result as it returns, a
heartbeat while calls are slow, ``done``; a failed call is a retryable
transport error; a cancelled run posts nothing more. The callback is driven
against the offline engines, and the fake provider's timings show all nine
calls in flight together."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

import pytest

from pcn_clone.ai import FakeClient, assess_dimension, build_snapshot, score_criterion
from pcn_clone.app.projects_data import default_project_values
from pcn_clone.app.review import ids, run
from pcn_clone.app.review.config import HEARTBEAT_ENV, heartbeat_seconds
from pcn_clone.app.review.ids import ItemKind
from pcn_clone.app.review.run import (
    Envelope,
    Launch,
    Message,
    RunItem,
    RunRegistry,
    item_request,
    parse_launch,
    run_launch,
)
from pcn_clone.app.review.submit import submission_from_values
from pcn_clone.content import load_assessment, load_mca

PINS = {
    "templateId": "pcn_global",
    "templateVersion": "1.5.0",
    "assessmentSetId": "set",
    "assessmentSetVersion": "0.3.0",
    "mcaSetId": "mca",
    "mcaSetVersion": "0.1.0",
    "model": "fake/pcn-reviewer",
    "assessmentInputDigest": "aiv1-x",
    "submission": {"templateId": "pcn_global", "answers": []},
}

SNAPSHOT = build_snapshot(submission_from_values(default_project_values())).to_json()
REQUEST = {
    key: SNAPSHOT[key]
    for key in (*run.SHARED_PINS, *run.PINS["dimension"], *run.PINS["criterion"])
} | {"submission": SNAPSHOT["submission"]}
ALL_ITEMS = [RunItem("dimension", d.id, 1) for d in load_assessment().dimensions] + [
    RunItem("criterion", c.id, 1) for c in load_mca().matrix.criteria
]
ITEM = {"kind": "dimension", "id": "d1", "generation": 1}


def launch(*items: RunItem, review_id: str = "r1", nonce: str = "n1") -> Launch:
    return Launch(review_id, nonce, items, PINS)


def dim(item_id: str, generation: int = 1) -> RunItem:
    return RunItem("dimension", item_id, generation)


def crit(item_id: str, generation: int = 1) -> RunItem:
    return RunItem("criterion", item_id, generation)


class Engines:
    """Engines that answer only when released, recording every request and
    how many calls ran at once."""

    def __init__(self) -> None:
        self.requests: list[Mapping[str, Any]] = []
        self.gates: dict[str, asyncio.Event] = {}
        self.running = 0
        self.peak = 0
        self.cancelled: list[str] = []

    def gate(self, item_id: str) -> asyncio.Event:
        return self.gates.setdefault(item_id, asyncio.Event())

    async def call(self, request: Mapping[str, Any], key: str) -> Envelope:
        item_id = str(request[key])
        self.requests.append(request)
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            await self.gate(item_id).wait()
        except asyncio.CancelledError:
            self.cancelled.append(item_id)
            raise
        finally:
            self.running -= 1
        if item_id.startswith("boom"):
            raise RuntimeError("connection reset")
        return {"ok": True, key: item_id, "finding": {"id": item_id}}

    def table(self) -> dict[ItemKind, run.Engine]:
        async def assess(request: Mapping[str, Any]) -> Envelope:
            return await self.call(request, "dimensionId")

        async def score(request: Mapping[str, Any]) -> Envelope:
            return await self.call(request, "criterionId")

        return {"dimension": assess, "criterion": score}


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def kinds(posted: list[Message]) -> list[str]:
    return [
        str(m["type"]) + (f":{m['itemId']}" if m["type"] == "result" else "")
        for m in posted
    ]


def appended(props: dict[str, Any]) -> Message:
    """The message one inbox write appends."""
    (operation,) = props["data"].to_plotly_json()["operations"]
    assert (operation["operation"], operation["location"]) == ("Append", [])
    message: Message = operation["params"]["value"]
    return message


# --- The request ---------------------------------------------------------------


def test_a_well_formed_launch_parses() -> None:
    parsed = parse_launch(
        {
            "reviewId": "r1",
            "nonce": "n1",
            "items": [ITEM, {"kind": "criterion", "id": "c1", "generation": 0}],
            "request": PINS,
        }
    )

    assert parsed == Launch("r1", "n1", (dim("d1"), crit("c1", 0)), PINS)


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {"nonce": "n", "items": [ITEM], "request": {}},
        {"reviewId": "", "nonce": "n", "items": [ITEM], "request": {}},
        {"reviewId": "r", "nonce": "", "items": [ITEM], "request": {}},
        {"reviewId": "r", "nonce": 1, "items": [ITEM], "request": {}},
        {"reviewId": "r", "nonce": "n", "items": [], "request": {}},
        {"reviewId": "r", "nonce": "n", "items": {}, "request": {}},
        {"reviewId": "r", "nonce": "n", "items": [ITEM], "request": []},
        {"reviewId": "r", "nonce": "n", "items": ["d1"], "request": {}},
        {
            "reviewId": "r",
            "nonce": "n",
            "items": [ITEM | {"kind": "memo"}],
            "request": {},
        },
        {"reviewId": "r", "nonce": "n", "items": [ITEM | {"id": ""}], "request": {}},
        {
            "reviewId": "r",
            "nonce": "n",
            "items": [ITEM | {"generation": -1}],
            "request": {},
        },
        {
            "reviewId": "r",
            "nonce": "n",
            "items": [ITEM | {"generation": True}],
            "request": {},
        },
    ],
)
def test_a_malformed_or_empty_launch_is_refused(data: Any) -> None:
    assert parse_launch(data) is None


def test_each_kind_gets_its_own_request() -> None:
    assert item_request(launch(), dim("d1")) == {
        "templateId": "pcn_global",
        "templateVersion": "1.5.0",
        "model": "fake/pcn-reviewer",
        "assessmentInputDigest": "aiv1-x",
        "assessmentSetId": "set",
        "assessmentSetVersion": "0.3.0",
        "dimensionId": "d1",
        "submission": PINS["submission"],
    }
    assert item_request(launch(), crit("c1")) == {
        "templateId": "pcn_global",
        "templateVersion": "1.5.0",
        "model": "fake/pcn-reviewer",
        "assessmentInputDigest": "aiv1-x",
        "mcaSetId": "mca",
        "mcaSetVersion": "0.1.0",
        "criterionId": "c1",
        "submission": PINS["submission"],
    }


# --- The registry --------------------------------------------------------------


def test_a_request_delivered_again_is_not_run_again() -> None:
    registry = RunRegistry()

    assert registry.admit("n1") is True
    assert registry.admit("n2") is True
    assert registry.admit("n1") is False


def test_the_registry_remembers_a_bounded_number_of_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run, "REMEMBERED_NONCES", 2)
    registry = RunRegistry()
    for nonce in ("a", "b", "c"):
        registry.admit(nonce)

    assert registry.admit("a") is True
    assert registry.admit("c") is False


def test_a_review_limit_lasts_while_any_of_its_runs_is_active() -> None:
    async def scenario() -> None:
        registry = RunRegistry(width=3)
        async with registry.review("r1") as first:
            async with registry.review("r1") as second:
                assert second is first
                assert registry.active("r1") == 2
            assert registry.active("r1") == 1
        assert registry.active("r1") == 0
        async with registry.review("r1") as fresh:
            assert fresh is not first

    asyncio.run(scenario())


# --- The run -------------------------------------------------------------------


def test_a_run_posts_start_each_result_as_it_returns_and_done() -> None:
    async def scenario() -> list[Message]:
        engines = Engines()
        posted: list[Message] = []
        task = asyncio.create_task(
            run_launch(
                launch(dim("d1"), dim("d2"), crit("c1")),
                posted.append,
                registry=RunRegistry(),
                engines=engines.table(),
                heartbeat=60,
            )
        )
        await settle()
        assert engines.running == 3
        assert kinds(posted) == ["started"]
        for item_id in ("c1", "d2", "d1"):
            engines.gate(item_id).set()
            await settle()
            assert kinds(posted)[-1] == f"result:{item_id}"
        await task
        return posted

    posted = asyncio.run(scenario())

    assert kinds(posted) == ["started", "result:c1", "result:d2", "result:d1", "done"]
    assert all(m["reviewId"] == "r1" and m["nonce"] == "n1" for m in posted)
    assert posted[1] == {
        "reviewId": "r1",
        "nonce": "n1",
        "type": "result",
        "kind": "criterion",
        "itemId": "c1",
        "generation": 1,
        "response": {"ok": True, "criterionId": "c1", "finding": {"id": "c1"}},
    }


def test_a_slow_run_sends_heartbeats_until_its_calls_return() -> None:
    async def scenario() -> list[Message]:
        engines = Engines()
        posted: list[Message] = []
        task = asyncio.create_task(
            run_launch(
                launch(dim("d1")),
                posted.append,
                registry=RunRegistry(),
                engines=engines.table(),
                heartbeat=0.01,
            )
        )
        await asyncio.sleep(0.055)
        engines.gate("d1").set()
        await task
        await asyncio.sleep(0.03)
        return posted

    posted = asyncio.run(scenario())
    beats = [m for m in posted if m["type"] == "heartbeat"]

    assert len(beats) >= 3
    assert kinds(posted)[0] == "started"
    assert kinds(posted)[-2:] == ["result:d1", "done"]
    assert all(m["at"].endswith("+00:00") for m in beats)


def test_a_failed_call_is_a_retryable_transport_error() -> None:
    async def scenario() -> list[Message]:
        engines = Engines()
        for gate in ("boom", "boom-too"):
            engines.gate(gate).set()
        posted: list[Message] = []
        await run_launch(
            launch(dim("boom"), crit("boom-too")),
            posted.append,
            registry=RunRegistry(),
            engines=engines.table(),
            heartbeat=60,
        )
        return posted

    results = [m["response"] for m in asyncio.run(scenario()) if m["type"] == "result"]

    assert sorted(results, key=lambda envelope: envelope["errorMessage"]) == [
        {
            "ok": False,
            "errorMessage": "The assessment request could not be completed. "
            "Please try again.",
            "error": {"kind": "retryable", "code": "transport_error"},
        },
        {
            "ok": False,
            "errorMessage": "The scoring request could not be completed. "
            "Please try again.",
            "error": {"kind": "retryable", "code": "transport_error"},
        },
    ]


def test_a_review_runs_at_most_its_width_at_once() -> None:
    async def scenario() -> int:
        engines = Engines()
        registry = RunRegistry(width=2)
        first = asyncio.create_task(
            run_launch(
                launch(*(dim(f"d{n}") for n in range(5))),
                lambda _message: None,
                registry=registry,
                engines=engines.table(),
                heartbeat=60,
            )
        )
        await settle()
        assert engines.running == 2
        second = asyncio.create_task(
            run_launch(
                launch(crit("c9"), nonce="n2"),
                lambda _message: None,
                registry=registry,
                engines=engines.table(),
                heartbeat=60,
            )
        )
        await settle()
        assert engines.running == 2
        for gate in [*(f"d{n}" for n in range(5)), "c9"]:
            engines.gate(gate).set()
        await asyncio.gather(first, second)
        return engines.peak

    assert asyncio.run(scenario()) == 2


def test_a_closed_connection_cancels_the_calls_and_posts_nothing_more() -> None:
    async def scenario() -> tuple[list[str], list[str], int]:
        engines = Engines()
        registry = RunRegistry()
        posted: list[Message] = []
        task = asyncio.create_task(
            run_launch(
                launch(dim("d1"), crit("c1")),
                posted.append,
                registry=registry,
                engines=engines.table(),
                heartbeat=0.01,
            )
        )
        await settle()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        count = len(posted)
        await asyncio.sleep(0.03)
        assert len(posted) == count
        return sorted(engines.cancelled), kinds(posted), registry.active("r1")

    cancelled, posted, active = asyncio.run(scenario())

    assert cancelled == ["c1", "d1"]
    assert posted == ["started"]
    assert active == 0


def test_the_fake_provider_has_all_nine_calls_in_flight_together() -> None:
    client = FakeClient(delay_seconds=0.3)
    running = 0
    overlap = 0

    def counted(call: Any) -> run.Engine:
        async def engine(request: Mapping[str, Any]) -> Envelope:
            nonlocal running, overlap
            running += 1
            overlap = max(overlap, running)
            try:
                response = await call(request, client=client)
            finally:
                running -= 1
            result: Envelope = response.to_json()
            return result

        return engine

    async def scenario() -> list[Message]:
        posted: list[Message] = []
        await run_launch(
            Launch("r1", "n1", tuple(ALL_ITEMS), REQUEST),
            posted.append,
            registry=RunRegistry(),
            engines={
                "dimension": counted(assess_dimension),
                "criterion": counted(score_criterion),
            },
            heartbeat=60,
        )
        return posted

    started = time.monotonic()
    posted = asyncio.run(scenario())
    elapsed = time.monotonic() - started

    results = [m for m in posted if m["type"] == "result"]
    assert len(ALL_ITEMS) == run.RUN_CONCURRENCY == 9
    assert overlap == 9
    assert [m["response"]["ok"] for m in results] == [True] * 9
    assert elapsed < 2 * 0.3


# --- The callback --------------------------------------------------------------


def test_the_callback_runs_new_requests_once_and_answers_on_the_inbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pushed: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(
        run, "set_props", lambda target, props: pushed.append((target, props))
    )
    monkeypatch.setattr(run, "REGISTRY", RunRegistry())
    coherence = {"kind": "dimension", "id": "internal_coherence", "generation": 1}
    impact = {"kind": "criterion", "id": "environmental_impact", "generation": 3}
    requests = [
        {"reviewId": "r1", "nonce": "first", "items": [coherence], "request": REQUEST},
        {"reviewId": "r1", "nonce": "broken", "items": [], "request": REQUEST},
        {"reviewId": "r2", "nonce": "second", "items": [impact], "request": REQUEST},
    ]

    asyncio.run(run.run_review(requests))
    asyncio.run(run.run_review(requests))

    assert {target for target, _ in pushed} == {ids.INBOX}
    messages = [appended(props) for _, props in pushed]
    assert {
        nonce: [m["type"] for m in messages if m["nonce"] == nonce]
        for nonce in ("first", "second")
    } == {
        "first": ["started", "result", "done"],
        "second": ["started", "result", "done"],
    }
    first = next(m for m in messages if m.get("itemId") == "internal_coherence")
    assert first["generation"] == 1
    assert first["response"]["ok"] is True
    assert first["response"]["finding"]["model"] == SNAPSHOT["model"]
    second = next(m for m in messages if m.get("itemId") == "environmental_impact")
    assert (second["reviewId"], second["generation"]) == ("r2", 3)


def test_an_item_the_content_no_longer_has_fails_terminally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pushed: list[dict[str, Any]] = []
    monkeypatch.setattr(run, "set_props", lambda _target, props: pushed.append(props))
    monkeypatch.setattr(run, "REGISTRY", RunRegistry())
    retired = {"kind": "dimension", "id": "retired", "generation": 1}

    asyncio.run(
        run.run_review(
            [{"reviewId": "r1", "nonce": "n1", "items": [retired], "request": REQUEST}]
        )
    )

    (result,) = [m for m in map(appended, pushed) if m["type"] == "result"]
    assert result["itemId"] == "retired"
    assert result["response"]["error"] == {
        "kind": "terminal",
        "code": "unknown_dimension",
    }


# --- The heartbeat setting -------------------------------------------------------


def test_the_heartbeat_defaults_to_ten_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HEARTBEAT_ENV, raising=False)
    assert heartbeat_seconds() == 10.0
    monkeypatch.setenv(HEARTBEAT_ENV, "0.5")
    assert heartbeat_seconds() == 0.5


@pytest.mark.parametrize("raw", ["soon", "0", "-1", "inf", "nan"])
def test_a_bad_heartbeat_setting_is_refused(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv(HEARTBEAT_ENV, raw)

    with pytest.raises(ValueError, match=HEARTBEAT_ENV):
        heartbeat_seconds()
