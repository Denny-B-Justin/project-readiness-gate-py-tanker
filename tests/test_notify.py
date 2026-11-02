"""Toasts: the entry ``toast`` builds, the per-kind table it draws from, and
that table's agreement with the stylesheets and with the browser-side copy
in ``projects.js``."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import get_args

import pytest
from dash import html

from pcn_clone.app.icons import IconName
from pcn_clone.app.notify import TOAST_KINDS, ToastKind, toast

ASSETS = Path(__file__).resolve().parents[1] / "pcn_clone" / "app" / "assets"
STORE_JS = (ASSETS / "projects.js").read_text(encoding="utf-8")
JS_TOAST_KINDS = re.compile(r"const TOAST_KINDS = (\{.*?\});", re.DOTALL)


def test_a_toast_is_a_headline_with_its_kind_and_icon() -> None:
    entry = toast("success", "Draft saved")
    icon = entry.pop("icon")
    assert entry == {
        "action": "show",
        "className": "toast-success",
        "message": "Draft saved",
    }
    assert isinstance(icon, html.Span)
    assert icon.to_plotly_json()["props"]["data-icon"] == "circle-check"


def test_a_description_moves_the_headline_into_the_title() -> None:
    entry = toast("error", "Couldn’t delete", "The store refused the write.")  # noqa: RUF001
    assert entry["title"] == "Couldn’t delete"  # noqa: RUF001
    assert entry["message"] == "The store refused the write."
    assert entry["className"] == "toast-error"


def test_every_kind_has_a_style_with_a_tint_and_a_glyph() -> None:
    assert set(TOAST_KINDS) == set(get_args(ToastKind))
    brand = (ASSETS / "brand.css").read_text(encoding="utf-8")
    icons = (ASSETS / "icons.css").read_text(encoding="utf-8")
    for style in TOAST_KINDS.values():
        assert f".mantine-Notification-root.{style['className']}" in brand
        assert style["icon"] in get_args(IconName)
        assert f'data-icon="{style["icon"]}"' in icons


@pytest.mark.skipif(
    "sendNotifications" not in STORE_JS and "toast-" not in STORE_JS,
    reason="projects.js shows no toasts",
)
def test_store_js_declares_the_same_toast_kinds() -> None:
    match = JS_TOAST_KINDS.search(STORE_JS)
    assert match, "store.js shows toasts but declares no `const TOAST_KINDS = {...};`"
    assert json.loads(match.group(1)) == TOAST_KINDS
