"""Steps shared by the proposer-workspace browser tests: opening a project's
form, reading controls, footers and tallies, editing native controls,
watching draft saves and Dash requests, and comparing markup drawn in the
browser with the Python components it mirrors."""

from __future__ import annotations

import json
from typing import Any

from dash.development.base_component import Component

from pcn_clone.app.projects_data import default_project_meta, default_project_values
from pcn_clone.app.routing import page_url
from tests.browser.harness import Page, dash_id

READY = (
    "(() => { const root = document.getElementById('pf-root');"
    " return !!root && root.dataset.pfReady === 'true'; })()"
)
"""True once the workspace has restored its draft into the controls."""

ALL_READY = (
    "document.querySelectorAll('[data-pf-evaluate]').length === 19"
    " && !document.querySelector('[data-pf-evaluate]:disabled')"
)
"""True once every field's readiness came back ready (the default project)."""


def evaluate_button(field_id: str) -> str:
    return dash_id({"type": "pf-evaluate", "field": field_id})


def status(field_id: str) -> str:
    return dash_id({"type": "pf-status", "field": field_id})


def tally(section_id: str) -> str:
    return dash_id({"type": "pf-tally", "section": section_id})


def bound(field_id: str, path: list[str]) -> str:
    """The control bound to ``path`` in a field's answer."""
    return (
        f"[data-pf-field={json.dumps(field_id)}]"
        f"[data-pf-path='{json.dumps(path, separators=(',', ':'))}']"
    )


def open_form(page: Page, project_id: str, *, wait_ready: bool = True) -> None:
    page.goto("/" + page_url("project", project_id=project_id), ready=READY)
    if wait_ready:
        page.wait_for(ALL_READY)


def seed_default(page: Page) -> str:
    """Clone the default project straight into the store; return its id."""
    meta = json.dumps(default_project_meta())
    values = json.dumps(default_project_values())
    return str(page.js(f"window.pcnStore.cloneDefaultProject({meta}, {values}).id"))


def open_default(page: Page) -> str:
    project_id = seed_default(page)
    open_form(page, project_id)
    return project_id


def snapshot(page: Page) -> dict[str, Any]:
    values: dict[str, Any] = page.js("window.pcnForm.snapshot()")
    return values


def set_value(page: Page, selector: str, value: str) -> None:
    """Set a control's value as an edit would (select, month and number
    controls take no typed text) and announce it."""
    page.js(
        f"""(() => {{
          const el = document.querySelector({json.dumps(selector)});
          el.value = {json.dumps(value)};
          el.dispatchEvent(new Event("input", {{bubbles: true}}));
          el.dispatchEvent(new Event("change", {{bubbles: true}}));
          return true;
        }})()"""
    )


def text(page: Page, selector: str) -> str:
    result: str = page.js(
        f"(document.querySelector({json.dumps(selector)}) || {{}}).textContent || ''"
    )
    return result


def texts(page: Page, selector: str) -> list[str]:
    result: list[str] = page.js(
        f"[...document.querySelectorAll({json.dumps(selector)})]"
        ".map((el) => el.textContent)"
    )
    return result


def footer(page: Page, field_id: str) -> dict[str, Any]:
    """The field's footer: its status text, Evaluate label, whether the
    button is primary and disabled."""
    button = evaluate_button(field_id)
    result: dict[str, Any] = page.js(
        f"""(() => {{
          const b = document.querySelector({json.dumps(button)});
          return {{
            status: document.querySelector({json.dumps(status(field_id))})
              .textContent,
            label: b.textContent,
            primary: b.classList.contains("btn-primary"),
            disabled: b.disabled,
          }};
        }})()"""
    )
    return result


def control(page: Page, field_id: str, path: list[str], prop: str = "value") -> Any:
    """A property (``value`` by default) of the control bound to ``path``."""
    selector = json.dumps(bound(field_id, path))
    return page.js(f"document.querySelector({selector}).{prop}")


def exists(selector: str) -> str:
    """An expression true while ``selector`` matches."""
    return f"!!document.querySelector({json.dumps(selector)})"


def count(page: Page, selector: str) -> int:
    result: int = page.js(f"document.querySelectorAll({json.dumps(selector)}).length")
    return result


def has_text(selector: str, value: str) -> str:
    """An expression true while ``selector``'s text is ``value``."""
    return (
        f"(document.querySelector({json.dumps(selector)}) || {{}})"
        f".textContent === {json.dumps(value)}"
    )


def rows(field_id: str, kind: str = "list") -> str:
    """The drawn rows of a list (or ``worksheet``) field."""
    return f"[data-pf-{kind}={field_id}] tbody[data-pf-rows] > tr"


SAVE_SPY = """(() => {
  window.pcnSaves = [];
  let current;
  Object.defineProperty(window, "pcnStore", {
    configurable: true,
    get() { return current; },
    set(value) {
      current = value;
      const original = value && value.saveDraft;
      if (typeof original !== "function" || original.spied) return;
      const spy = function (projectId, values) {
        const root = document.getElementById("pf-root");
        window.pcnSaves.push({
          at: performance.now(),
          ready: !!root && root.dataset.pfReady === "true",
          values: JSON.parse(JSON.stringify(values)),
        });
        return original.apply(this, arguments);
      };
      spy.spied = true;
      value.saveDraft = spy;
    },
  });
})()"""
"""Records every ``pcnStore.saveDraft`` call in ``window.pcnSaves`` (when, the
answers, and whether the workspace was ready), from the first script on."""


def spy_on_saves(page: Page) -> None:
    """Install ``SAVE_SPY`` in every page this tab loads from now on."""
    page.send("Page.addScriptToEvaluateOnNewDocument", {"source": SAVE_SPY})


def saves(page: Page) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = page.js("window.pcnSaves")
    return result


def dash_requests(page: Page, output: str, since: int = 0) -> list[dict[str, Any]]:
    """The Dash callback requests sent since event index ``since`` whose
    output names ``output``, each with its ``body`` and DevTools
    ``requestId`` (requires ``Network.enable``)."""
    found = []
    for event in page.events[since:]:
        if event["method"] != "Network.requestWillBeSent":
            continue
        request = event["params"]["request"]
        if "_dash-update-component" not in request["url"]:
            continue
        body = json.loads(request.get("postData") or "{}")
        if output in body.get("output", ""):
            found.append({"body": body, "requestId": event["params"]["requestId"]})
    return found


def request_window(page: Page, request_id: str) -> tuple[float, float]:
    """When a request was sent and when its response finished loading, in
    the browser's monotonic seconds."""
    sent = page.wait_event(
        "Network.requestWillBeSent", lambda p: p["requestId"] == request_id
    )
    done = page.wait_event(
        "Network.loadingFinished", lambda p: p["requestId"] == request_id
    )
    return float(sent["timestamp"]), float(done["timestamp"])


SHAPE = """(el) => {
  const shape = (node) => {
    if (node.nodeType === Node.TEXT_NODE) return node.textContent;
    const attributes = {};
    for (const { name, value } of node.attributes) {
      if (name === "class" || name === "role" || /^(aria|data)-/.test(name)) {
        attributes[name] = value;
      }
    }
    if (node.style.length) {
      const style = {};
      for (const property of node.style) {
        style[property] = node.style.getPropertyValue(property).trim();
      }
      attributes.style = style;
    }
    const children = [...node.childNodes].filter(
      (child) => child.nodeType === Node.ELEMENT_NODE
        || (child.nodeType === Node.TEXT_NODE && child.textContent !== ""));
    return [node.tagName.toLowerCase(), attributes, ...children.map(shape)];
  };
  return shape(el);
}"""
"""A DOM element as ``[tag, attributes, ...children]``: its class, role,
``aria-*`` and ``data-*`` attributes and inline style, text kept."""


def shape(node: Any) -> Any:
    """A Dash component tree in ``SHAPE``'s form, as it renders."""
    if isinstance(node, str | int | float):
        return str(node)
    assert isinstance(node, Component), node
    props = node.to_plotly_json()["props"]
    attributes: dict[str, Any] = {}
    for name, value in props.items():
        if name == "className" and value:
            attributes["class"] = value
        elif name == "role" or name.startswith(("aria-", "data-")):
            attributes[name] = str(value)
        elif name == "style" and value:
            attributes["style"] = {key: str(item) for key, item in value.items()}
    children = props.get("children")
    if children is None:
        children = []
    elif not isinstance(children, list | tuple):
        children = [children]
    return [type(node).__name__.lower(), attributes, *(shape(c) for c in children)]


def dom_shape(page: Page, selector: str) -> Any:
    """``SHAPE`` of the first element matching ``selector``."""
    return page.js(f"({SHAPE})(document.querySelector({json.dumps(selector)}))")


def type_at_end(page: Page, selector: str, typed: str) -> None:
    """Focus a text control with the caret at its end and type ``typed``."""
    page.js(
        f"""(() => {{
          const el = document.querySelector({json.dumps(selector)});
          el.focus();
          el.setSelectionRange(el.value.length, el.value.length);
          return true;
        }})()"""
    )
    page.send("Input.insertText", {"text": typed})
