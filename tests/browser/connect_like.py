"""Test scaffolding: the app served the way Posit Connect serves it.

Connect reaches one app at two roots, its content URL ``/content/<GUID>/``
and a vanity URL, and strips the root before the request reaches the app.
This ASGI app stands in front of ``pcn_clone.app.server`` no more leniently
than Connect may be:

- under ``CONTENT_ROOT`` (with or without its trailing slash) every path is
  forwarded, HTTP and WebSocket alike;
- at ``VANITY_ROOT`` only the root itself is served (with or without its
  trailing slash, with any query string), as the index page; deeper vanity
  paths, and WebSockets there, are refused;
- anything else answers 404.

So a page, asset, callback or socket URL that leaves the content root fails,
and a review run that completes proves its socket used Dash's prefix. Serve
it with ``DASH_REQUESTS_PATHNAME_PREFIX`` set to ``CONTENT_ROOT``, as on
Connect.
"""

from __future__ import annotations

from typing import Any

from pcn_clone.app.server import server as app

CONTENT_ROOT = "/content/7c1e5b2a-0d4f-4e8b-9a61-3f2d8c9b0e17/"
VANITY_ROOT = "/pcn-assessment/"


def _strip(path: str, *, websocket: bool) -> str | None:
    """``path`` as the app sees it, or ``None`` when the stand-in refuses
    it."""
    if path == CONTENT_ROOT.rstrip("/"):
        return "/"
    if path.startswith(CONTENT_ROOT):
        return "/" + path.removeprefix(CONTENT_ROOT)
    if not websocket and path in (VANITY_ROOT, VANITY_ROOT.rstrip("/")):
        return "/"
    return None


async def server(scope: dict[str, Any], receive: Any, send: Any) -> None:
    if scope["type"] in ("http", "websocket"):
        websocket = scope["type"] == "websocket"
        path = _strip(scope["path"], websocket=websocket)
        if path is None:
            if websocket:
                await send({"type": "websocket.close", "code": 1008})
            else:
                await send({"type": "http.response.start", "status": 404})
                await send({"type": "http.response.body", "body": b"Not found"})
            return
        scope = {**scope, "path": path, "raw_path": path.encode()}
    await app(scope, receive, send)
