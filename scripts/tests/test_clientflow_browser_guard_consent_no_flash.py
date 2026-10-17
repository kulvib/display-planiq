"""Browser Guard must hide known CMP overlays without breaking real sites."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client/runtime"))
from clientflow_runtime import browser_guard, display_runtime, kiosk_consent, post_final_reboot_acceptance  # noqa: E402


def test_consent_ui_is_hidden_before_navigation_with_shared_css():
    css = kiosk_consent.CONSENT_CSS
    for selector in ("#coiOverlay", "#CybotCookiebotDialog", "#usercentrics-root", "#onetrust-banner-sdk"):
        assert selector in css
    assert css in display_runtime.EARLY_KIOSK_CSS
    assert json.dumps(css) in browser_guard.HIDE_JS
    assert json.dumps(kiosk_consent.CONSENT_SELECTORS) in post_final_reboot_acceptance._BROWSER_GUARD_PROBE_JS
    source = (ROOT / "client/runtime/clientflow_runtime/display_runtime.py").read_text(encoding="utf-8")
    assert source.index('"Page.addScriptToEvaluateOnNewDocument"') < source.index('"Page.navigate"')


def test_ordinary_content_and_native_js_are_not_modified():
    css = kiosk_consent.CONSENT_CSS
    assert 'iframe[title*="cookie"' not in css
    assert '[id^="coi"' not in css
    assert '[class*="coi' not in css
    assert '.cookie-banner' not in css
    js = browser_guard.HIDE_JS
    assert "tryAcceptCookies" not in js
    assert "window.confirm =" not in js
    assert "window.open =" not in js
    assert "window.alert =" not in js
    assert "new MutationObserver(" not in js
    assert "querySelectorAll('*')" not in js
    assert "restorePage" not in js
    assert "cookie|cookies|samtykke" not in js


def test_cookie_mode_never_implicitly_grants_consent():
    assert browser_guard.COOKIE_MODE == "hide"
    assert "acceptAll" not in browser_guard.HIDE_JS
    assert "el.click()" not in browser_guard.HIDE_JS
    unit = (ROOT / "client/systemd/clientflow-browser-guard.service").read_text()
    assert "CLIENTFLOW_BROWSER_GUARD_COOKIE_MODE=hide" in unit
    assert "CLIENTFLOW_BROWSER_GUARD_COOKIE_MODE=accept" not in unit


def test_refresh_preserves_exact_url_and_never_erases_browser_profile():
    countdown = browser_guard.COUNTDOWN_JS
    assert "location.reload();" in countdown
    assert "_kiosk_refresh" not in countdown
    assert "location.replace(" not in countdown
    runtime = (ROOT / "client/runtime/clientflow_runtime/display_runtime.py").read_text()
    assert runtime.count("_clear_browser_profile(") == 2  # definition + explicit reset
    assert "shutil.rmtree(profile" in runtime


def test_native_browser_dialogs_are_dismissed_without_javascript_overrides(monkeypatch):
    """Confirm and prompt must never implicitly approve website actions."""
    import asyncio

    sent = []

    class FakeConnection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def send(self, raw):
            sent.append(json.loads(raw))

        async def __aiter__(self):
            for dialog_type in ("alert", "confirm", "prompt", "beforeunload"):
                yield json.dumps({
                    "method": "Page.javascriptDialogOpening",
                    "params": {"type": dialog_type, "message": "never log me"},
                })

    monkeypatch.setattr(browser_guard.websockets, "connect", lambda *_a, **_k: FakeConnection())
    monkeypatch.setattr(browser_guard, "log", lambda _message: None)
    asyncio.run(browser_guard.watch_javascript_dialogs({"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/1"}))
    assert sent[0]["method"] == "Page.enable"
    decisions = [command["params"]["accept"] for command in sent[1:]]
    assert decisions == [False, False, False, True]
    assert all(command["method"] == "Page.handleJavaScriptDialog" for command in sent[1:])


def test_dialog_monitors_do_not_survive_tab_disappearance(monkeypatch):
    import asyncio

    async def check():
        started = []
        cancelled = []

        async def watch(tab):
            started.append(tab["id"])
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.append(tab["id"])
                raise

        monkeypatch.setattr(browser_guard, "watch_javascript_dialogs", watch)
        tasks = {}
        browser_guard.update_dialog_monitors([
            {"id": "page-1", "webSocketDebuggerUrl": "ws://127.0.0.1/test"}
        ], tasks)
        await asyncio.sleep(0)
        assert started == ["page-1"] and list(tasks) == ["page-1"]
        browser_guard.update_dialog_monitors([], tasks)
        await asyncio.sleep(0)
        assert tasks == {} and cancelled == ["page-1"]

    asyncio.run(check())
