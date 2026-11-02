"""ARIA and data attributes for Dash html components.

Dash takes ``aria-*`` and ``data-*`` attributes as hyphenated keyword
arguments, which Python can only pass by unpacking a dict; ``aria`` and
``data`` build that dict from ordinary keywords:
``html.Nav(links, **aria(label="Primary"))``.
"""

from typing import Any


def aria(**attributes: str) -> dict[str, Any]:
    """Prefix each keyword with ``aria-``: ``aria(hidden="true")`` gives
    ``{"aria-hidden": "true"}``. ARIA names are single words
    (``describedby``, ``haspopup``), so they pass through unchanged."""
    return {f"aria-{name}": value for name, value in attributes.items()}


def data(**attributes: str) -> dict[str, Any]:
    """Prefix each keyword with ``data-``, underscores becoming hyphens:
    ``data(pf_rows="x")`` gives ``{"data-pf-rows": "x"}``."""
    return {
        f"data-{name.replace('_', '-')}": value for name, value in attributes.items()
    }
