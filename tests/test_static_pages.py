"""Static content pages: the home video guides, and the methodology and release
notes copy and diagrams."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import dash
import pytest
from dash import Dash
from dash.development.base_component import Component

ASSETS = Path(__file__).resolve().parents[1] / "pcn_clone" / "app" / "assets"


@pytest.fixture(scope="module")
def pages(app: Dash) -> dict[str, ModuleType]:
    """The static page modules, as the application imported them."""
    return {
        name: importlib.import_module(f"pcn_clone.app.pages.{name}")
        for name in ("home", "methodology", "release_notes")
    }


def _walk(node: Any) -> Iterator[Any]:
    """Every node of a component tree, depth first, strings included."""
    if isinstance(node, list | tuple):
        for child in node:
            yield from _walk(child)
        return
    yield node
    if isinstance(node, Component):
        yield from _walk(getattr(node, "children", None))


def _text(layout: Component) -> str:
    """All text in a rendered layout, one string child per line."""
    return "\n".join(node for node in _walk(layout) if isinstance(node, str))


def _image_sources(layout: Component) -> list[str]:
    """The ``src`` of every image in a rendered layout, in document order."""
    images = [node for node in _walk(layout) if isinstance(node, dash.html.Img)]
    return [str(getattr(image, "src", "")) for image in images]


METHODOLOGY_SENTENCES = (
    "Stronger project submissions before formal review",
    "When a submission is handed over, those same standards drive a first-pass "
    "assessment for the reviewer.",
    "Guidance before review, not only after submission",
    "A Pass is a preparation signal, not project approval.",
    "The first pass is a draft, not a decision.",
    "The completed review is exported as a structured assessment memo",
    "Calibration does not transfer decision-making authority to the AI.",
    "This cycle is repeated until the feedback is sufficiently aligned with "
    "reviewer expectations and approved for use with project proponents.",
    "Reviews that start from a drafted assessment, not a blank page",
    "Feedback is grounded in the country's own forms, criteria, guidance, "
    "terminology, and policy context.",
)

RELEASE_NOTES_SENTENCES = (
    "What\N{RIGHT SINGLE QUOTATION MARK}s new",
    "Release notes",
    "We version each release and use GitHub as the version-control system, so "
    "changes are tracked over time and easy to roll back if needed.",
    "Operational pre-release",
    "Pre-release / testing version",
    "Template-neutral building blocks",
    "Projects are scored 1–5 against four weighted criteria",
    "Each export is generated in a dedicated web worker, keeping document "
    "rendering responsive and separate from the form.",
    "Export stays blocked until every finding is decided.",
    "The PIM PCN evaluation module is now available as an operational pre-release.",
)

RELEASE_VERSIONS = (
    "v2.2.1.beta",
    "v2.2.0.beta",
    "v2.1.0.beta",
    "v2.0.0.beta",
    "v1.4.0.beta",
    "v1.3.0.beta",
    "v1.2.0.beta",
    "v1.1.0.beta",
    "v1.0.0.beta",
)


def test_home_links_the_three_video_guides_in_new_tabs(
    pages: dict[str, ModuleType],
) -> None:
    layout = pages["home"].layout()
    links = [node for node in _walk(layout) if isinstance(node, dash.html.A)]
    assert [(link.href, link.target, link.rel) for link in links] == [
        (url, "_blank", "noopener noreferrer")
        for url in (
            "https://vimeo.com/1228876110",
            "https://vimeo.com/1228873814",
            "https://vimeo.com/1229071373",
        )
    ]
    text = _text(layout)
    for title, duration in (
        ("Product walkthrough", "2:08"),
        ("Drafting a Concept Note", "1:56"),
        ("Reviewing a Concept Note", "2:03"),
    ):
        assert f"{title}\n (opens in a new tab)\n{duration}" in text


@pytest.mark.parametrize("sentence", METHODOLOGY_SENTENCES)
def test_methodology_copy(pages: dict[str, ModuleType], sentence: str) -> None:
    assert sentence in _text(pages["methodology"].layout())


def test_methodology_diagrams_are_referenced_and_shipped(
    pages: dict[str, ModuleType],
) -> None:
    diagrams = [
        "methodology/readiness_gate_diagram.png",
        "methodology/calibration_cycle_diagram.png",
    ]
    assert _image_sources(pages["methodology"].layout()) == [
        dash.get_asset_url(diagram) for diagram in diagrams
    ]
    for diagram in diagrams:
        assert (ASSETS / diagram).is_file()


@pytest.mark.parametrize("sentence", RELEASE_NOTES_SENTENCES)
def test_release_notes_copy(pages: dict[str, ModuleType], sentence: str) -> None:
    assert sentence in _text(pages["release_notes"].layout())


def test_release_notes_list_every_release_most_recent_first(
    pages: dict[str, ModuleType],
) -> None:
    lines = _text(pages["release_notes"].layout()).split("\n")
    versions = [
        line for line in lines if line.startswith("v") and line.endswith(".beta")
    ]
    assert tuple(versions) == RELEASE_VERSIONS


def test_release_notes_anatomy_reads_v_1_0_0_beta(pages: dict[str, ModuleType]) -> None:
    lines = _text(pages["release_notes"].layout()).split("\n")
    start = lines.index("v")
    assert "".join(lines[start : start + 8]) == "v1.0.0.beta"
