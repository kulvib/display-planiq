"""Prevent browser guard itself from re-exposing cookie banners on reload."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "client/runtime/clientflow_runtime/browser_guard.py"
RUNTIME = ROOT / "client/runtime/clientflow_runtime/display_runtime.py"


def test_consent_attempt_does_not_remove_kiosk_css_or_force_overlay_visible():
    src = GUARD.read_text(encoding="utf-8")
    block = src[src.index("  function tryAcceptCookies() {"):src.index("  function addCss() {")]
    assert "forceShowForClick" not in block
    assert "oldCss.remove()" not in block
    assert "scrollIntoView" not in block
    assert "style.setProperty('display', 'block'" not in block
    assert "style.setProperty('visibility', 'visible'" not in block
    assert "function robustClick(el)" in block
    assert "const oldCss" not in block


def test_kiosk_css_is_injected_before_navigation_and_survives_refresh():
    src = RUNTIME.read_text(encoding="utf-8")
    assert '"Page.addScriptToEvaluateOnNewDocument"' in src
    assert '"Page.navigate"' in src
    early = src[src.index("def _early_protection_script"):src.index("async def _cdp_register_and_navigate")]
    assert "clientflow-early-kiosk-protection" in early
    assert "MutationObserver" in early
    assert "#coiOverlay" in src
    assert "#CybotCookiebotDialog" in src


def test_periodic_refresh_does_not_delete_browser_profile():
    guard = GUARD.read_text(encoding="utf-8")
    block = guard[guard.index("COUNTDOWN_JS ="):guard.index("async def evaluate_js")]
    assert "location.replace(url.toString())" in block
    assert "rmtree" not in block
