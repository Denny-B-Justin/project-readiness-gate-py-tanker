"""ASGI entry point.

Serve in production with ``uv run uvicorn pcn_clone.app.server:server --port 8050``.
"""

from __future__ import annotations

from pcn_clone.app import create_app

app = create_app()
server = app.server
