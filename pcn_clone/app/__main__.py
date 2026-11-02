"""Development server: ``uv run python -m pcn_clone.app``.

Serves with Dash dev tools and auto-reload on ``PORT`` (8050 by default).
Run it from the repository root: the FastAPI backend serves by re-launching
Uvicorn on this module's ``app`` by its import path, which it derives from
the working directory, so the app is bound at module level rather than built
inline.
"""

import os

from pcn_clone.app.server import app

if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", "8050")))
