"""Headless Chrome over the DevTools Protocol, driving the real app.

``AppServer`` serves ``create_app()`` (through ``pcn_clone.app.server``) with
uvicorn in a subprocess on a free port, against the offline fake AI
provider unless told otherwise. ``Chrome`` launches headless Chrome
with its own throwaway profile and opens tabs; each tab is a ``Page`` with
synchronous helpers: ``goto``, ``js``, ``wait_for``, ``click``, ``type``,
``press``, ``screenshot``, plus raw ``send`` and DevTools event access for
network interception. No Node.js is involved.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from websockets.sync.client import ClientConnection, connect

ROOT = Path(__file__).resolve().parents[2]

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
)

KEYS: dict[str, tuple[str, int, str]] = {
    "Enter": ("Enter", 13, "\r"),
    "Backspace": ("Backspace", 8, ""),
    "Tab": ("Tab", 9, ""),
    "Escape": ("Escape", 27, ""),
    " ": ("Space", 32, " "),
}
"""Key name -> (DOM code, Windows virtual key code, text it types)."""


class CDPError(RuntimeError):
    """A DevTools command failed or a page script threw."""


def find_chrome() -> str | None:
    """Chrome or Chromium: ``$PCN_CHROME`` if set, else the macOS app bundle,
    else the first candidate on ``PATH``."""
    override = os.environ.get("PCN_CHROME")
    for candidate in ((override,) if override else ()) + CHROME_CANDIDATES:
        if os.path.isabs(candidate):
            if os.access(candidate, os.X_OK):
                return candidate
        elif found := shutil.which(candidate):
            return found
    return None


def free_port() -> int:
    """A TCP port nothing is listening on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def wait_for_http(url: str, timeout: float = 30) -> None:
    """Block until ``url`` answers 200, or raise after ``timeout`` seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.1)
    raise TimeoutError(f"{url} did not answer within {timeout} s")


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    """Stop a process started in its own session, with its children."""
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)


SERVER_ENVIRONMENT: dict[str, str] = {"PCN_AI_PROVIDER": "fake"}
"""What an app server's environment sets over the test process's."""


class AppServer:
    """The app under uvicorn on a free port, logging to ``log_path``. Its
    environment is the test process's with ``SERVER_ENVIRONMENT`` and then
    ``env`` over it, so ``env`` can choose another provider or add the fake
    provider's latency and failures. ``asgi`` names another ASGI app to
    serve and ``ready_path`` the path that answers once it is up."""

    def __init__(
        self,
        log_path: Path,
        env: Mapping[str, str] | None = None,
        *,
        asgi: str = "pcn_clone.app.server:server",
        ready_path: str = "/",
    ) -> None:
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.log_path = log_path
        self.env = {**SERVER_ENVIRONMENT, **(env or {})}
        self.asgi = asgi
        self.ready_path = ready_path
        self.process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        log = self.log_path.open("wb")
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                self.asgi,
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "warning",
            ],
            cwd=ROOT,
            env={**os.environ, **self.env},
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        wait_for_http(self.url + self.ready_path)

    def stop(self) -> None:
        stop_process(self.process)


class Chrome:
    """Headless Chrome with a throwaway profile, reachable over DevTools."""

    def __init__(self, binary: str, profile: Path) -> None:
        self.binary = binary
        self.profile = profile
        self.port = free_port()
        self.endpoint = f"http://127.0.0.1:{self.port}"
        self.process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        self.process = subprocess.Popen(
            [
                self.binary,
                "--headless=new",
                f"--remote-debugging-port={self.port}",
                f"--user-data-dir={self.profile}",
                "--window-size=1280,900",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-sync",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        wait_for_http(self.endpoint + "/json/version")

    def stop(self) -> None:
        stop_process(self.process)

    def new_page(self, base_url: str) -> Page:
        """A fresh tab whose relative URLs resolve against ``base_url``."""
        request = urllib.request.Request(
            self.endpoint + "/json/new?about:blank", method="PUT"
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            target = json.load(response)
        socket_url: str = target["webSocketDebuggerUrl"]
        stack = contextlib.ExitStack()
        connection = stack.enter_context(connect(socket_url, max_size=None))
        page = Page(connection, base_url)
        page.exit_stack = stack
        page.target_id = target["id"]
        page.chrome = self
        return page

    def close_target(self, target_id: str) -> None:
        url = f"{self.endpoint}/json/close/{target_id}"
        try:
            with urllib.request.urlopen(url, timeout=5):
                pass
        except OSError:
            pass


class Page:
    """One browser tab. Commands are synchronous; DevTools events received
    while waiting are kept in ``events``."""

    def __init__(self, connection: ClientConnection, base_url: str) -> None:
        self._ws = connection
        self._next_id = 0
        self.base_url = base_url
        self.events: list[dict[str, Any]] = []
        self.target_id = ""
        self.chrome: Chrome | None = None
        self.exit_stack = contextlib.ExitStack()
        for domain in ("Page", "Runtime", "Log"):
            self.send(f"{domain}.enable")
        self.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
        self.set_viewport(1280, 900)
        self.send("Page.bringToFront")

    # --- Protocol ---------------------------------------------------------

    def send(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = 15
    ) -> dict[str, Any]:
        """Run one DevTools command and return its result."""
        self._next_id += 1
        command_id = self._next_id
        self._ws.send(
            json.dumps({"id": command_id, "method": method, "params": params or {}})
        )
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CDPError(f"{method} timed out")
            message = json.loads(self._ws.recv(timeout=remaining))
            if message.get("id") == command_id:
                if "error" in message:
                    raise CDPError(f"{method}: {message['error']}")
                result: dict[str, Any] = message.get("result", {})
                return result
            if "method" in message:
                self.events.append(message)

    def pump(self, seconds: float) -> None:
        """Receive events for ``seconds`` without sending anything."""
        deadline = time.monotonic() + seconds
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                message = json.loads(self._ws.recv(timeout=remaining))
            except TimeoutError:
                return
            if "method" in message:
                self.events.append(message)

    def wait_event(
        self,
        method: str,
        predicate: Callable[[dict[str, Any]], bool] = lambda _params: True,
        since: int = 0,
        timeout: float = 10,
    ) -> dict[str, Any]:
        """The params of the first ``method`` event at or after index
        ``since`` that satisfies ``predicate``, waiting up to ``timeout``."""
        deadline = time.monotonic() + timeout
        while True:
            for event in self.events[since:]:
                if event["method"] == method and predicate(event["params"]):
                    params: dict[str, Any] = event["params"]
                    return params
            since = len(self.events)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(f"no {method} event within {timeout} s")
            self.pump(min(remaining, 0.2))

    def callback_outputs(self, since: int = 0) -> list[str]:
        """The ``output`` of each Dash server-callback request sent since
        event index ``since`` (requires ``Network.enable``)."""
        outputs = []
        for event in self.events[since:]:
            if event["method"] != "Network.requestWillBeSent":
                continue
            request = event["params"]["request"]
            if "_dash-update-component" in request["url"]:
                body = request.get("postData")
                outputs.append(json.loads(body)["output"] if body else "?")
        return outputs

    # --- Script -----------------------------------------------------------

    def js(self, expression: str) -> Any:
        """Evaluate ``expression`` in the page (awaiting a promise) and return
        its JSON value; a thrown error raises ``CDPError``."""
        result = self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            description = details.get("exception", {}).get("description") or details
            raise CDPError(f"{expression[:80]!r} threw: {description}")
        return result["result"].get("value")

    def wait_for(self, expression: str, timeout: float = 10) -> Any:
        """Poll ``expression`` until it is truthy and return its value; fail
        the test after ``timeout`` seconds."""
        deadline = time.monotonic() + timeout
        last: Any = None
        while time.monotonic() < deadline:
            try:
                last = self.js(expression)
            except CDPError as error:
                last = error
            else:
                if last:
                    return last
            time.sleep(0.05)
        raise AssertionError(f"timed out waiting for {expression!r} (last: {last!r})")

    def errors(self) -> list[str]:
        """Uncaught page exceptions and console errors seen so far."""
        found = []
        for event in self.events:
            params = event["params"]
            if event["method"] == "Runtime.exceptionThrown":
                details = params["exceptionDetails"]
                found.append(
                    str(details.get("exception", {}).get("description") or details)
                )
            elif (
                event["method"] == "Runtime.consoleAPICalled"
                and params["type"] == "error"
            ):
                found.append(" ".join(str(a.get("value", "")) for a in params["args"]))
        return found

    # --- Navigation and input ---------------------------------------------

    def goto(self, path: str, ready: str | None = None) -> None:
        """Load ``path`` (relative to the app) and wait for the load event
        and, when given, the ``ready`` expression."""
        since = len(self.events)
        self.send("Page.navigate", {"url": self.base_url + path})
        self.wait_event("Page.loadEventFired", since=since, timeout=20)
        if ready:
            self.wait_for(ready, timeout=20)

    def reload(self, ready: str | None = None) -> None:
        since = len(self.events)
        self.send("Page.reload")
        self.wait_event("Page.loadEventFired", since=since, timeout=20)
        if ready:
            self.wait_for(ready, timeout=20)

    def set_viewport(self, width: int, height: int) -> None:
        self.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
        )

    def click(self, selector: str) -> None:
        """A real left click at the centre of the first match."""
        point = self.js(
            f"""(() => {{
              const el = document.querySelector({json.dumps(selector)});
              if (!el) return null;
              el.scrollIntoView({{block: "center", inline: "center"}});
              const r = el.getBoundingClientRect();
              return [r.x + r.width / 2, r.y + r.height / 2];
            }})()"""
        )
        if point is None:
            raise AssertionError(f"nothing matches {selector!r}")
        x, y = point
        self.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        for kind in ("mousePressed", "mouseReleased"):
            self.send(
                "Input.dispatchMouseEvent",
                {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1},
            )

    def type(self, selector: str, text: str) -> None:
        """Focus the first match and type ``text`` into it."""
        found = self.js(
            f"""(() => {{
              const el = document.querySelector({json.dumps(selector)});
              if (!el) return false;
              el.focus();
              return document.activeElement === el;
            }})()"""
        )
        if not found:
            raise AssertionError(f"cannot focus {selector!r}")
        self.send("Input.insertText", {"text": text})

    def press(self, key: str) -> None:
        """Press and release one key (see ``KEYS``) on the focused element."""
        code, virtual_key, text = KEYS[key]
        down: dict[str, Any] = {
            "type": "keyDown",
            "key": key,
            "code": code,
            "windowsVirtualKeyCode": virtual_key,
        }
        if text:
            down["text"] = text
        self.send("Input.dispatchKeyEvent", down)
        self.send(
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "key": key,
                "code": code,
                "windowsVirtualKeyCode": virtual_key,
            },
        )

    def screenshot(self, path: Path) -> Path:
        result = self.send("Page.captureScreenshot", {"format": "png"})
        path.write_bytes(base64.b64decode(result["data"]))
        return path

    def close(self) -> None:
        try:
            self.exit_stack.close()
        finally:
            if self.chrome is not None and self.target_id:
                self.chrome.close_target(self.target_id)


def url_param(name: str) -> str:
    """A JavaScript expression for the current URL's query parameter
    ``name``, or ``null`` when it has none."""
    return f"new URLSearchParams(location.search).get({json.dumps(name)})"


def dash_id(component_id: dict[str, str]) -> str:
    """A CSS selector for a Dash pattern-matching id (keys sorted, no spaces,
    as Dash writes it into the DOM)."""
    return (
        "[id='" + json.dumps(component_id, sort_keys=True, separators=(",", ":")) + "']"
    )
