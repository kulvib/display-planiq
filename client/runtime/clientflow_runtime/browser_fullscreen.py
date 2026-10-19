"""Bounded, read-only Chrome window-state probe using local Chrome DevTools.

Only the actual page target of this kiosk browser is measured. An invalid,
ambiguous or unreachable CDP response is *unknown*, never "not fullscreen".
No remote host may be contacted even if the local DevTools endpoint is tainted.
"""
from __future__ import annotations

import asyncio
import json
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

import websockets
from websockets.exceptions import WebSocketException

LOCAL_CDP = "http://127.0.0.1:9222"
_ALLOWED_STATES = frozenset({"fullscreen", "maximized", "normal", "minimized"})


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("CDP redirect denied")


def _read_json(path: str) -> object:
    # Neither system HTTP proxies nor redirects may move a local CDP probe
    # outside the loopback endpoint. Bound payload size as well as time.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    with opener.open(Request(f"{LOCAL_CDP}{path}"), timeout=1.0) as response:
        payload = response.read(128 * 1024 + 1)
        if len(payload) > 128 * 1024:
            raise ValueError("CDP response too large")
    return json.loads(payload)


def _validated_browser_socket(raw: object) -> str:
    if not isinstance(raw, str):
        raise ValueError("missing CDP socket")
    parsed = urlsplit(raw)
    if (
        parsed.scheme != "ws"
        or parsed.hostname != "127.0.0.1"
        or parsed.port != 9222
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith("/devtools/browser/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("untrusted CDP socket")
    return raw


async def _window_state(socket_url: str, page_id: str) -> str:
    async with websockets.connect(socket_url, open_timeout=1, close_timeout=1, max_size=65536) as socket:
        await socket.send(json.dumps({
            "id": 1, "method": "Browser.getWindowForTarget", "params": {"targetId": page_id}
        }))
        # Some CDP versions send events before the command result.
        while True:
            reply = json.loads(await socket.recv())
            if reply.get("id") != 1:
                continue
            if "error" in reply:
                raise ValueError("CDP rejected window lookup")
            result = reply.get("result") or {}
            state = (result.get("bounds") or {}).get("windowState")
            if state is None and isinstance(result.get("windowId"), int):
                await socket.send(json.dumps({
                    "id": 2, "method": "Browser.getWindowBounds",
                    "params": {"windowId": result["windowId"]},
                }))
                while True:
                    bounds_reply = json.loads(await socket.recv())
                    if bounds_reply.get("id") == 2:
                        if "error" in bounds_reply:
                            raise ValueError("CDP rejected window bounds")
                        state = ((bounds_reply.get("result") or {}).get("bounds") or {}).get("windowState")
                        break
            if state not in _ALLOWED_STATES:
                raise ValueError("unsupported Chrome window state")
            return "fullscreen" if state == "fullscreen" else "windowed"


def probe_browser_fullscreen() -> str:
    """Return 'fullscreen'/'windowed'/'unknown'; never modify Chrome."""
    try:
        version = _read_json("/json/version")
        targets = _read_json("/json")
        if not isinstance(version, dict) or not isinstance(targets, list):
            return "unknown"
        pages = [t for t in targets if isinstance(t, dict) and t.get("type") == "page"]
        if len(pages) != 1 or not isinstance(pages[0].get("id"), str) or not pages[0]["id"]:
            return "unknown"
        socket_url = _validated_browser_socket(version.get("webSocketDebuggerUrl"))
        return asyncio.run(asyncio.wait_for(_window_state(socket_url, pages[0]["id"]), timeout=2.5))
    except (OSError, ValueError, TypeError, KeyError, TimeoutError, RuntimeError,
            WebSocketException):
        return "unknown"
