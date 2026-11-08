"""A local stand-in for the Posit mAI Gateway, for tests and hand runs.

A threaded HTTP server answers under ``/posit-mai/conversationalai/`` the
way the gateway does for one model family: GPT (Responses bodies), Gemini
(Interactions bodies) or Claude (Converse bodies with an ``answer`` tool
call). It records every request (path, query, lower-cased headers and JSON
body) and serves queued :class:`Reply` values first; without one it
answers with ``answer`` or, when that is unset, with what the offline
:class:`~pcn_clone.ai.provider.FakeClient` would answer to the request, so
the whole app can run through the real gateway client against it::

    python -m tests.ai.fake_gateway --family gpt --port 9000

and then, in another shell::

    PCN_AI_PROVIDER=WB-mAI \\
    MAI_BASE_URL=http://127.0.0.1:9000/posit-mai/conversationalai/ \\
    MAI_ENDPOINT=https://mai.invalid/maifactory/openai/responses \\
    CONNECT_CONTENT_GUID=00000000-0000-0000-0000-000000000000 \\
    uv run python -m pcn_clone.app
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit

from pcn_clone.ai.provider import FakeClient
from pcn_clone.ai.schemas import (
    ASSESSMENT_FINDING_FORMAT,
    FIELD_EVALUATION_FORMAT,
    MCA_SCORE_FINDING_FORMAT,
)

PREFIX = "/posit-mai/conversationalai/"
Family = Literal["gpt", "gemini", "claude"]
FAMILIES: tuple[Family, ...] = ("gpt", "gemini", "claude")
USAGE = {"input": 1200, "output": 340, "reasoning": 256}


@dataclass(frozen=True)
class Reply:
    """One canned gateway reply: a ``status`` with a JSON (mapping or list)
    or text ``body`` (``None``: the family's success body), extra
    ``headers``, a ``delay`` before answering, or ``drop`` to close the
    connection without answering."""

    status: int = 200
    body: Any = None
    headers: Mapping[str, str] = field(default_factory=dict)
    delay: float = 0.0
    drop: bool = False


@dataclass(frozen=True)
class Recorded:
    """One request as the gateway saw it."""

    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    body: Any


# --- Success bodies -----------------------------------------------------------


def gpt_body(
    text: str,
    *,
    status: str = "completed",
    incomplete_reason: str | None = None,
    refusal: str | None = None,
    usage: bool = True,
) -> dict[str, Any]:
    """A Responses API body whose message carries ``text`` (or a refusal)."""
    part = (
        {"type": "refusal", "refusal": refusal}
        if refusal is not None
        else {"type": "output_text", "text": text, "annotations": []}
    )
    body: dict[str, Any] = {
        "id": "resp_1",
        "object": "response",
        "created_at": 1_760_000_000,
        "status": status,
        "model": "gpt-5.6-luna-2026-09-01",
        "output": [
            {
                "type": "message",
                "id": "msg_1",
                "status": "completed",
                "role": "assistant",
                "content": [part],
            }
        ],
        "incomplete_details": (
            {"reason": incomplete_reason} if incomplete_reason is not None else None
        ),
        "error": None,
        "instructions": None,
        "metadata": {},
        "parallel_tool_calls": True,
        "temperature": None,
        "tool_choice": "auto",
        "tools": [],
        "top_p": None,
    }
    if usage:
        body["usage"] = {
            "input_tokens": USAGE["input"],
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": USAGE["output"],
            "output_tokens_details": {"reasoning_tokens": USAGE["reasoning"]},
            "total_tokens": USAGE["input"] + USAGE["output"],
        }
    return body


def gemini_body(
    text: str, *, status: str = "completed", usage: bool = True
) -> dict[str, Any]:
    """An Interactions API body whose model output is ``text``."""
    body: dict[str, Any] = {
        "id": "interaction_1",
        "object": "interaction",
        "status": status,
        "model": "gemini-3.8-flash",
        "created": "2026-11-08T00:00:00Z",
        "updated": "2026-11-08T00:00:01Z",
        "steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}]
        if text
        else [],
    }
    if usage:
        body["usage"] = {
            "total_input_tokens": USAGE["input"],
            "total_output_tokens": USAGE["output"] - USAGE["reasoning"],
            "total_thought_tokens": USAGE["reasoning"],
            "total_tokens": USAGE["input"] + USAGE["output"],
        }
    return body


def claude_body(
    answer: Any = None,
    *,
    text: str | None = None,
    stop: str = "tool_use",
    usage: bool = True,
) -> dict[str, Any]:
    """A Converse body carrying ``answer`` as the ``answer`` tool's input,
    or ``text`` as a plain text block."""
    content: list[dict[str, Any]] = []
    if text is not None:
        content.append({"text": text})
    if answer is not None:
        content.append(
            {"toolUse": {"toolUseId": "tooluse_1", "name": "answer", "input": answer}}
        )
    body: dict[str, Any] = {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": stop,
        "metrics": {"latencyMs": 1200},
    }
    if usage:
        body["usage"] = {
            "inputTokens": USAGE["input"],
            "outputTokens": USAGE["output"],
            "totalTokens": USAGE["input"] + USAGE["output"],
        }
    return body


def success_body(family: Family, answer: Mapping[str, Any]) -> dict[str, Any]:
    """The family's success body for a JSON ``answer``."""
    if family == "gpt":
        return gpt_body(json.dumps(answer))
    if family == "gemini":
        return gemini_body(json.dumps(answer))
    return claude_body(dict(answer))


# --- Requests -----------------------------------------------------------------


def request_parts(family: Family, body: Any) -> tuple[str, str, dict[str, Any]]:
    """The system prompt, user prompt and response schema of a request."""
    if family == "gpt":
        return (
            body["instructions"],
            body["input"][0]["content"][0]["text"],
            body["text"]["format"]["schema"],
        )
    if family == "gemini":
        user = body["input"]
        if isinstance(user, list):
            user = "".join(part.get("text", "") for part in user)
        return body["system_instruction"], user, body["response_format"]
    tool = body["toolConfig"]["tools"][0]["toolSpec"]
    return (
        body["system"][0]["text"],
        body["messages"][0]["content"][0]["text"],
        tool["inputSchema"]["json"],
    )


def _format_name(schema: Mapping[str, Any]) -> str:
    properties = schema.get("properties", {})
    if "suggestions" in properties:
        return FIELD_EVALUATION_FORMAT
    if "basis" in properties:
        return MCA_SCORE_FINDING_FORMAT
    return ASSESSMENT_FINDING_FORMAT


def fake_answer(family: Family, body: Any) -> dict[str, Any]:
    """What the offline fake provider answers to a gateway request."""
    system, user, schema = request_parts(family, body)
    reply = asyncio.run(
        FakeClient().complete(
            system=system, user=user, schema=schema, format_name=_format_name(schema)
        )
    )
    return reply.data


# --- Server -------------------------------------------------------------------


class _Server(ThreadingHTTPServer):
    """A threaded server that ignores clients hanging up mid-request."""

    daemon_threads = True
    block_on_close = False

    def handle_error(self, request: Any, client_address: Any) -> None:
        if not isinstance(sys.exc_info()[1], ConnectionError):
            super().handle_error(request, client_address)


class FakeGateway:
    """The fake gateway for one ``family``; use as a context manager, or
    :meth:`start` and :meth:`close`."""

    def __init__(
        self,
        family: Family,
        *,
        answer: Mapping[str, Any] | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self.family = family
        self.answer = answer
        self.requests: list[Recorded] = []
        self.replies: deque[Reply] = deque()
        self._lock = threading.Lock()
        self._server = _Server((host, port), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        """The gateway URL, ending in ``/``."""
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}{PREFIX}"

    def queue(self, *replies: Reply) -> None:
        """Serve ``replies``, in order, before the default answer."""
        with self._lock:
            self.replies.extend(replies)

    def body(self, index: int = 0) -> Any:
        """The JSON body of the ``index``-th request."""
        return self.requests[index].body

    def start(self) -> FakeGateway:
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> FakeGateway:
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.close()

    def _next_reply(self, body: Any) -> Reply:
        with self._lock:
            reply = self.replies.popleft() if self.replies else Reply()
        if reply.body is None and reply.status < 300 and not reply.drop:
            answer = self.answer
            if answer is None:
                answer = fake_answer(self.family, body)
            reply = replace(reply, body=success_body(self.family, answer))
        return reply

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                """Keep the test output quiet."""

            def do_POST(self) -> None:
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length)
                try:
                    body: Any = json.loads(raw) if raw else None
                except ValueError:
                    body = raw.decode("utf-8", "replace")
                url = urlsplit(self.path)
                with gateway._lock:
                    gateway.requests.append(
                        Recorded(
                            method="POST",
                            path=url.path,
                            query=dict(parse_qsl(url.query)),
                            headers={k.lower(): v for k, v in self.headers.items()},
                            body=body,
                        )
                    )
                if not url.path.startswith(PREFIX):
                    reply = Reply(
                        404, {"statusCode": 404, "message": "Resource not found"}
                    )
                else:
                    reply = gateway._next_reply(body)
                if reply.delay:
                    time.sleep(reply.delay)
                if reply.drop:
                    self.close_connection = True
                    return
                self._send(reply)

            def _send(self, reply: Reply) -> None:
                if isinstance(reply.body, str):
                    payload = reply.body.encode("utf-8")
                    content_type = "text/plain; charset=utf-8"
                else:
                    payload = json.dumps(reply.body).encode("utf-8")
                    content_type = "application/json"
                try:
                    self.send_response(reply.status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(payload)))
                    for name, value in reply.headers.items():
                        self.send_header(name, value)
                    self.end_headers()
                    self.wfile.write(payload)
                except OSError:
                    self.close_connection = True

        return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--family", choices=FAMILIES, default="gpt")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    options = parser.parse_args()
    gateway = FakeGateway(options.family, host=options.host, port=options.port)
    gateway.start()
    print(f"Fake mAI Gateway ({options.family}) at {gateway.url}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        gateway.close()


if __name__ == "__main__":
    main()
