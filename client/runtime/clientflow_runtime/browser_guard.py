#!/usr/bin/env python3
"""
ClientFlow V2 Browser Guard (ported from verified legacy Browser Guard)

Defensiv ClientFlow Browser Guard via Chrome Remote Debugging Protocol.

Rettet efter v1.1-log:
- Main page WebSocket kunne lukke med "no close frame received or sent"
- Cookie Information iframe-target kunne afvise WebSocket med HTTP 500
- Derfor:
  * Vi skipper iframe-/worker-targets og policy.app.cookieinformation.com
  * Vi evaluerer kun i hovedsider af type "page"
  * Vi bruger små, hurtige Runtime.evaluate-kald
  * Vi skjuler kun kendt consent UI via CSS før navigation, aldrig automatisk klik
  * Kort timeout pr. WebSocket-kald
"""

import asyncio
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .kiosk_consent import CONSENT_CSS

try:
    import websockets
except Exception as e:
    print(f"FEJL: Python-modulet websockets mangler: {e}", file=sys.stderr)
    sys.exit(1)


LOADED_ENV_FILE_VALUES = {}

# v1.5.9:
# Browser Guard læser ikke længere /etc/clientflow/clientflow.env direkte.
# Den fil kan indeholde secrets og bør ikke læses af denne service.
# Brug i stedet systemd drop-in:
# /etc/systemd/system/clientflow_browser_guard.service.d/10-browser-guard-env.conf

HOST = os.environ.get("CLIENTFLOW_CHROME_DEBUG_HOST", "127.0.0.1")
PORT = int(os.environ.get("CLIENTFLOW_CHROME_DEBUG_PORT", "9222"))
INTERVAL = float(os.environ.get("CLIENTFLOW_BROWSER_GUARD_INTERVAL", "2"))
DEFAULT_REFRESH_SEC = int(os.environ.get("CLIENTFLOW_BROWSER_GUARD_REFRESH_SEC", "900"))
ENABLE_REFRESH = os.environ.get("CLIENTFLOW_BROWSER_GUARD_ENABLE_REFRESH", "1").strip().lower() in ("1", "true", "yes", "y")
REFRESH_MIN_SEC = int(os.environ.get("CLIENTFLOW_BROWSER_GUARD_REFRESH_MIN_SEC", "60"))
REFRESH_MAX_SEC = int(os.environ.get("CLIENTFLOW_BROWSER_GUARD_REFRESH_MAX_SEC", "86400"))
CONFIG_PATH = Path(os.environ.get("CLIENTFLOW_DISPLAY_CONFIG_PATH", "/var/lib/clientflow/display-runtime/configuration.json"))
WS_TIMEOUT = float(os.environ.get("CLIENTFLOW_BROWSER_GUARD_WS_TIMEOUT", "4"))

# v1.4.1: Guard må ikke forstyrre første sidelæsning.
# Vent til siden er complete + lidt ekstra stabil tid, før CSS/DOM-regler kører.
START_DELAY_SEC = int(os.environ.get("CLIENTFLOW_BROWSER_GUARD_START_DELAY_SEC", "1"))

# Kiosk consent UI is hidden, never auto-accepted. Explicit legacy "accept"
# configuration maps to "hide" to prevent inadvertent tracking consent.
COOKIE_MODE = os.environ.get("CLIENTFLOW_BROWSER_GUARD_COOKIE_MODE", "hide").strip().lower()
if COOKIE_MODE != "off":
    COOKIE_MODE = "hide"

VERSION = "1.7.0"


DEBUG_URL = f"http://{HOST}:{PORT}/json"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def log(msg: str) -> None:
    print(f"{now_iso()} - browser_guard: {msg}", flush=True)


UNREADY_LOG_INTERVAL_SEC = int(os.environ.get("CLIENTFLOW_BROWSER_GUARD_UNREADY_LOG_INTERVAL_SEC", "60"))
EMPTY_SUMMARY_INTERVAL_SEC = int(os.environ.get("CLIENTFLOW_BROWSER_GUARD_EMPTY_SUMMARY_INTERVAL_SEC", "60"))
# Golden default: Chrome may be intentionally closed while Browser Guard runs.
# In that state, DevTools/9222 refuses connections every poll. Do not log that
# normal state unless explicitly enabled for debugging.
LOG_CHROME_UNREADY = os.environ.get("CLIENTFLOW_BROWSER_GUARD_LOG_CHROME_UNREADY", "0").strip().lower() in ("1", "true", "yes", "y")
_LAST_CHROME_UNREADY_LOG = 0.0
_LAST_CHROME_UNREADY_MESSAGE = ""
_SUPPRESSED_CHROME_UNREADY_LOGS = 0


def log_chrome_debug_unready(detail: str) -> None:
    """Handle normal Chrome-closed/DevTools-not-ready state quietly.

    Browser Guard may run while kiosk Chrome is intentionally closed. In that
    normal state, 127.0.0.1:9222 refuses connections every poll. For Golden
    clients this must not create journal spam. Set
    CLIENTFLOW_BROWSER_GUARD_LOG_CHROME_UNREADY=1 temporarily when debugging.
    """
    global _LAST_CHROME_UNREADY_LOG, _LAST_CHROME_UNREADY_MESSAGE, _SUPPRESSED_CHROME_UNREADY_LOGS
    detail = str(detail or "ukendt fejl")

    if not LOG_CHROME_UNREADY:
        _SUPPRESSED_CHROME_UNREADY_LOGS += 1
        return

    now = time.monotonic()
    interval = max(10, int(UNREADY_LOG_INTERVAL_SEC or 60))
    should_log = (detail != _LAST_CHROME_UNREADY_MESSAGE) or (now - _LAST_CHROME_UNREADY_LOG >= interval)
    if should_log:
        suffix = ""
        if _SUPPRESSED_CHROME_UNREADY_LOGS:
            suffix = f"; undertrykte gentagelser={_SUPPRESSED_CHROME_UNREADY_LOGS}"
        log(f"Chrome remote debugging ikke klar på {DEBUG_URL}: {detail}{suffix}")
        _LAST_CHROME_UNREADY_LOG = now
        _LAST_CHROME_UNREADY_MESSAGE = detail
        _SUPPRESSED_CHROME_UNREADY_LOGS = 0
    else:
        _SUPPRESSED_CHROME_UNREADY_LOGS += 1


def _coerce_refresh_sec(value, fallback=DEFAULT_REFRESH_SEC) -> int:
    if not ENABLE_REFRESH:
        return 0
    if value is None or str(value).strip() == "":
        value = fallback
    try:
        seconds = int(float(str(value).strip()))
    except Exception:
        seconds = int(fallback or 0)
    if seconds <= 0:
        return 0
    return max(REFRESH_MIN_SEC, min(REFRESH_MAX_SEC, seconds))


def get_refresh_sec() -> int:
    """Læs backend-styret refresh-interval fra clientflow_config.json.

    0 deaktiverer auto-refresh. Hvis feltet mangler, bruges environment/default 900s.
    """
    if not ENABLE_REFRESH:
        return 0
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "browser_refresh_interval_sec" in data:
                return _coerce_refresh_sec(data.get("browser_refresh_interval_sec"))
    except Exception as e:
        log(f"Kunne ikke læse browser refresh-interval fra {CONFIG_PATH}: {e}")
    return _coerce_refresh_sec(DEFAULT_REFRESH_SEC)


def get_tabs():
    """Return the current DevTools targets, or None when Chrome is unavailable.

    An unavailable DevTools endpoint is a normal state while kiosk Chrome is
    intentionally stopped (for example by Calendar OFF).  Keep that distinct
    from a successfully queried Chrome instance that simply has no main page
    target, so observability can stay useful without journal spam.
    """
    try:
        with urllib.request.urlopen(DEBUG_URL, timeout=3) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            return payload if isinstance(payload, list) else []
    except Exception as e:
        log_chrome_debug_unready(str(e))
        return None


def is_main_page_target(tab: dict) -> bool:
    url = tab.get("url", "") or ""
    target_type = tab.get("type", "") or ""

    # v1.6.2:
    # Evaluer kun rigtige hovedsider. CookieInformation eksponerer også et
    # cross-origin iframe-target via DevTools; det kan afvise WebSocket med
    # HTTP 500 og må ikke behandles som en refresh-/guard-side.
    if target_type and target_type != "page":
        return False

    if not url.startswith(("http://", "https://")):
        return False

    blocked = [
        "chrome-extension://",
        "devtools://",
        "policy.app.cookieinformation.com",
        "cookiesharingiframe",
    ]

    if any(b in url for b in blocked):
        return False

    return True


HIDE_JS = r"""
(() => {
  const VERSION = '1.7.0';
  const COOKIE_MODE = '__COOKIE_MODE__';
  const CONSENT_CSS = __CONSENT_CSS__;
  const root = document.documentElement;
  if (!root) return { version: VERSION, skipped: 'no-document' };

  // A stylesheet is registered before first navigation by DisplayRuntime.
  // The fallback also works if a Chrome document was navigated independently.
  // CSS automatically covers later DOM additions; no broad scanning or
  // DOM scanning is needed and no website-owned styles are changed.
  if (COOKIE_MODE === 'hide' && !document.getElementById('clientflow-browser-guard-css')) {
    const css = document.createElement('style');
    css.id = 'clientflow-browser-guard-css';
    css.textContent = CONSENT_CSS;
    (document.head || root).appendChild(css);
  }

  // Only kiosk-owned pointer CSS is touched; native website dialogs,
  // window.open, alert, confirm and prompt remain unmodified.
  if (!window.__clientflowCursorIdleInstalled) {
    window.__clientflowCursorIdleInstalled = true;
    const css = document.createElement('style');
    css.id = 'clientflow-idle-cursor';
    css.textContent = 'html[data-clientflow-cursor-idle="1"], html[data-clientflow-cursor-idle="1"] * { cursor: none !important; }';
    (document.head || root).appendChild(css);
    let timer = null;
    const showPointer = (event) => {
      if (event && event.isTrusted === false) return;
      root.removeAttribute('data-clientflow-cursor-idle');
      if (timer !== null) clearTimeout(timer);
      timer = setTimeout(() => root.setAttribute('data-clientflow-cursor-idle', '1'), 2000);
    };
    for (const name of ['pointermove', 'pointerdown', 'keydown']) {
      window.addEventListener(name, showPointer, {passive: true, capture: true});
    }
    showPointer();
  }

  root.setAttribute('data-clientflow-browser-guard', VERSION);
  return {
    version: VERSION,
    href: location.href,
    readyState: document.readyState,
    marker: VERSION,
    cookieMode: COOKIE_MODE,
    css: !!document.getElementById('clientflow-browser-guard-css'),
  };
})()
""".replace("__COOKIE_MODE__", COOKIE_MODE).replace("__CONSENT_CSS__", json.dumps(CONSENT_CSS))

COUNTDOWN_JS = r"""
(() => {
  const VERSION = '1.7.0';
  window.__clientflowBrowserGuardRefreshSec = __REFRESH_SEC__;
  window.__clientflowBrowserGuardStartDelaySec = __START_DELAY_SEC__;

  function safe(fn, fallback) {
    try { return fn(); } catch (e) { return fallback; }
  }

  function getRefreshSec() {
    const value = Number(window.__clientflowBrowserGuardRefreshSec || 0);
    return Number.isFinite(value) ? value : 0;
  }

  function getStartDelaySec() {
    const value = Number(window.__clientflowBrowserGuardStartDelaySec || 0);
    return Number.isFinite(value) ? value : 0;
  }

  function removeCountdown() {
    safe(() => document.getElementById('tm-kiosk-bar')?.remove());
    safe(() => document.getElementById('tm-kiosk-text')?.remove());
  }

  function isFullscreen() {
    return safe(() => {
      if (document.fullscreenElement || document.webkitFullscreenElement || document.querySelector(':fullscreen')) return true;
      const h = Math.abs(outerHeight - screen.height) <= 2 || Math.abs(innerHeight - screen.height) <= 2;
      const w = Math.abs(outerWidth - screen.width) <= 2 || Math.abs(innerWidth - screen.width) <= 2;
      if (h && w) return true;
      if (innerHeight >= screen.availHeight - 2 && innerWidth >= screen.availWidth - 2) return true;
      return false;
    }, false);
  }

  function createCountdown() {
    if (document.getElementById('tm-kiosk-bar')) return;

    const bar = document.createElement('div');
    bar.id = 'tm-kiosk-bar';
    const txt = document.createElement('div');
    txt.id = 'tm-kiosk-text';

    Object.entries({
      position:'fixed', top:'0', left:'0', height:'6px', width:'100%',
      transform:'scaleX(0)', 'transform-origin':'left center',
      background:'linear-gradient(90deg, rgba(0,150,136,.95), rgba(76,175,80,.95))',
      'z-index':'2147483647', 'pointer-events':'none', transition:'transform 0.9s linear, opacity 0.2s',
      display:'block', visibility:'visible', opacity:'1'
    }).forEach(([k,v]) => safe(() => bar.style.setProperty(k, v, 'important')));

    Object.entries({
      position:'fixed', top:'8px', right:'10px', padding:'3px 6px',
      background:'rgba(0,0,0,.6)', color:'#fff', 'font-size':'12px',
      'border-radius':'4px', 'z-index':'2147483647', 'pointer-events':'none',
      'font-family':'sans-serif', 'line-height':'1', display:'block', visibility:'visible', opacity:'1'
    }).forEach(([k,v]) => safe(() => txt.style.setProperty(k, v, 'important')));

    safe(() => (document.body || document.documentElement).appendChild(bar));
    safe(() => (document.body || document.documentElement).appendChild(txt));
  }

  function updateCountdown() {
    const REFRESH_SEC = getRefreshSec();
    const START_DELAY_SEC = getStartDelaySec();
    if (!REFRESH_SEC || REFRESH_SEC < 60) {
      removeCountdown();
      window.__clientflowBrowserGuardStart = null;
      return { disabled: true, refreshSec: REFRESH_SEC, readyState: document.readyState };
    }

    // Start først refresh-countdown når siden faktisk er færdigindlæst
    // og URL'en har været stabil i START_DELAY_SEC sekunder.
    if (document.readyState !== 'complete') {
      return { skipped: 'not-complete', refreshSec: REFRESH_SEC, readyState: document.readyState };
    }

    if (window.__clientflowBrowserGuardCountdownHref !== location.href) {
      window.__clientflowBrowserGuardCountdownHref = location.href;
      window.__clientflowBrowserGuardCountdownCompleteAt = Date.now();
      window.__clientflowBrowserGuardStart = null;
    }

    window.__clientflowBrowserGuardCountdownCompleteAt = window.__clientflowBrowserGuardCountdownCompleteAt || Date.now();
    const stableFor = Math.floor((Date.now() - window.__clientflowBrowserGuardCountdownCompleteAt) / 1000);
    if (stableFor < START_DELAY_SEC) {
      return { skipped: 'start-delay', refreshSec: REFRESH_SEC, readyState: document.readyState, stableFor, startDelaySec: START_DELAY_SEC };
    }

    createCountdown();

    if (!window.__clientflowBrowserGuardStart) window.__clientflowBrowserGuardStart = Date.now();

    const elapsed = Math.floor((Date.now() - window.__clientflowBrowserGuardStart) / 1000);
    const pct = Math.max(0, Math.min(1, elapsed / REFRESH_SEC));
    const hidden = isFullscreen();

    const bar = document.getElementById('tm-kiosk-bar');
    const txt = document.getElementById('tm-kiosk-text');

    if (bar) {
      bar.removeAttribute('data-clientflow-browser-guard-hidden');
      bar.style.setProperty('display', hidden ? 'none' : 'block', 'important');
      bar.style.setProperty('visibility', hidden ? 'hidden' : 'visible', 'important');
      bar.style.setProperty('opacity', hidden ? '0' : '1', 'important');
      bar.style.setProperty('transform', 'scaleX(' + pct + ')', 'important');
      bar.style.setProperty('z-index', '2147483647', 'important');
    }

    if (txt) {
      txt.removeAttribute('data-clientflow-browser-guard-hidden');
      const left = Math.max(0, REFRESH_SEC - elapsed);
      const m = Math.floor(left / 60);
      const s = left % 60;
      txt.textContent = 'Opdaterer om ' + m + ':' + String(s).padStart(2, '0');
      txt.style.setProperty('display', hidden ? 'none' : 'block', 'important');
      txt.style.setProperty('visibility', hidden ? 'hidden' : 'visible', 'important');
      txt.style.setProperty('opacity', hidden ? '0' : '1', 'important');
      txt.style.setProperty('z-index', '2147483647', 'important');
    }

    if (elapsed >= REFRESH_SEC) {
      window.__clientflowBrowserGuardStart = Date.now();
      // Reload the exact URL, including signed query params and fragment.
      location.reload();
    }

    return { elapsed, hidden, bar: !!bar, text: !!txt };
  }

  if (!window.__clientflowBrowserGuardCountdownLoop) {
    window.__clientflowBrowserGuardCountdownLoop = true;
    window.__clientflowBrowserGuardStart = window.__clientflowBrowserGuardStart || Date.now();
    safe(() => setInterval(updateCountdown, 1000));
  }

  return updateCountdown();
})()
"""


async def evaluate_js(tab, js: str, label: str):
    wsurl = tab.get("webSocketDebuggerUrl")
    url = tab.get("url", "")

    if not wsurl:
        return {"href": url, "error": "missing webSocketDebuggerUrl", "label": label}

    try:
        async with websockets.connect(
            wsurl,
            max_size=10_000_000,
            open_timeout=WS_TIMEOUT,
            close_timeout=1,
        ) as ws:
            await ws.send(json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": js,
                    "returnByValue": True,
                    "awaitPromise": False,
                    "userGesture": False,
                    "timeout": int(WS_TIMEOUT * 1000),
                },
            }))

            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=WS_TIMEOUT)
                payload = json.loads(msg)
                if payload.get("id") != 1:
                    continue

                result = payload.get("result", {})
                if "exceptionDetails" in result:
                    return {
                        "href": url,
                        "label": label,
                        "error": "Runtime.evaluate exception",
                        "exceptionDetails": result.get("exceptionDetails"),
                    }

                return result.get("result", {}).get("value")
    except Exception as e:
        return {"href": url, "label": label, "error": str(e)}



async def watch_javascript_dialogs(tab: dict) -> None:
    """Keep a CDP Page subscription alive and dismiss native browser dialogs.

    Do not replace website-owned alert/confirm/prompt functions: that can alter
    page scripts and silently approve dangerous actions. A beforeunload dialog
    is accepted only to permit the configured kiosk navigation or refresh.
    Never log a dialog's text, URL or its potentially sensitive prompt contents.
    """
    wsurl = str(tab.get("webSocketDebuggerUrl") or "")
    if not wsurl:
        return
    try:
        async with websockets.connect(
            wsurl, max_size=1_000_000, open_timeout=WS_TIMEOUT, close_timeout=1
        ) as ws:
            await ws.send(json.dumps({"id": 1001, "method": "Page.enable"}))
            async for raw in ws:
                payload = json.loads(raw)
                if payload.get("id") == 1001 and "error" in payload:
                    raise RuntimeError("Chrome CDP Page.enable blev afvist")
                if payload.get("method") != "Page.javascriptDialogOpening":
                    continue
                dialog_type = (payload.get("params") or {}).get("type")
                if dialog_type not in {"alert", "confirm", "prompt", "beforeunload"}:
                    continue
                # Always dismiss alert/confirm/prompt; never accept a website
                # operation. Only beforeunload is accepted, to enable reload.
                await ws.send(json.dumps({
                    "id": 1002,
                    "method": "Page.handleJavaScriptDialog",
                    "params": {"accept": dialog_type == "beforeunload"},
                }))
                log(f"Kiosk blokerede indbygget JavaScript-dialog: type={dialog_type}")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # The main loop will reconnect only while this target still exists.
        log(f"JavaScript-dialogvagt blev afbrudt: {type(exc).__name__}")


def update_dialog_monitors(tabs: list[dict], tasks: dict[str, asyncio.Task]) -> None:
    """Maintain one event subscriber per main page, not a connection per poll."""
    current: set[str] = set()
    for tab in tabs:
        target_id = str(tab.get("id") or "")
        if not target_id or not tab.get("webSocketDebuggerUrl"):
            continue
        current.add(target_id)
        existing = tasks.get(target_id)
        if existing is None or existing.done():
            tasks[target_id] = asyncio.create_task(watch_javascript_dialogs(tab))
    for target_id in list(tasks):
        if target_id not in current:
            tasks.pop(target_id).cancel()


async def run_once(refresh_sec: int, dialog_tasks: dict[str, asyncio.Task] | None = None):
    tab_payload = get_tabs()
    if tab_payload is None:
        return None
    tabs = [t for t in tab_payload if is_main_page_target(t)]
    if dialog_tasks is not None:
        update_dialog_monitors(tabs, dialog_tasks)
    results = []

    for tab in tabs:
        # Først: kort CSS/DOM hide. Dette må ikke klikke/reloade siden.
        hide_result = await evaluate_js(tab, HIDE_JS, "hide")
        results.append(hide_result)

        # Countdown/refresh evalueres også når refresh_sec=0, så en tidligere
        # countdown-bar fjernes straks, hvis intervallet slås fra fra backend.
        countdown_js = COUNTDOWN_JS.replace("__REFRESH_SEC__", str(refresh_sec)).replace("__START_DELAY_SEC__", str(START_DELAY_SEC))
        countdown_result = await evaluate_js(tab, countdown_js, "countdown")
        if isinstance(countdown_result, dict):
            hide_result = dict(hide_result or {})
            hide_result["countdown"] = countdown_result
            results[-1] = hide_result

    return results


async def _async_main():
    initial_refresh_sec = get_refresh_sec()
    log(f"Starter v{VERSION}. DevTools={DEBUG_URL}, interval={INTERVAL}s, refresh={initial_refresh_sec}s, ws_timeout={WS_TIMEOUT}s, start_delay={START_DELAY_SEC}s, cookie_mode={COOKIE_MODE}, policy=known_consent_css_only, authority=display_desired_configuration, config={CONFIG_PATH}")

    last_summary = 0.0
    last_error = ""
    last_refresh_sec = initial_refresh_sec
    dialog_tasks: dict[str, asyncio.Task] = {}

    while True:
        try:
            refresh_sec = get_refresh_sec()
            if refresh_sec != last_refresh_sec:
                log(f"Browser refresh-interval ændret: {last_refresh_sec}s -> {refresh_sec}s")
                last_refresh_sec = refresh_sec
            run_result = await run_once(refresh_sec, dialog_tasks)
            chrome_ready = run_result is not None
            results = run_result or []

            for r in results:
                if isinstance(r, dict) and r.get("error"):
                    # Avoid logging full kiosk URL/query/fragment (may carry tokens).
                    msg = json.dumps({k: v for k, v in r.items() if k != "href"}, ensure_ascii=False)[:1400]
                    if msg != last_error:
                        log(f"FEJL evaluate: {msg}")
                        last_error = msg

            # A failed DevTools query is deliberately silent by default.  It is
            # the expected state while Calendar/GUI has intentionally stopped
            # Chrome.  A successful Chrome query with zero main-page targets is
            # still useful operational information and keeps the old summary.
            now = time.monotonic()
            if chrome_ready:
                summary_interval = 10 if results else max(10, int(EMPTY_SUMMARY_INTERVAL_SEC or 60))
                if now - last_summary > summary_interval:
                    if results:
                        for r in results:
                            if isinstance(r, dict):
                                log(
                                    "status "
                                    f"url_origin={urlsplit(str(r.get('href') or '')).scheme}://{urlsplit(str(r.get('href') or '')).netloc} "
                                    f"readyState={r.get('readyState')} "
                                    f"skipped={r.get('skipped')} "
                                    f"cookieMode={r.get('cookieMode')} "
                                    f"accepted={r.get('accepted')} "
                                    f"acceptResult={r.get('acceptResult')} "
                                    f"marker={r.get('marker')} "
                                    f"hidden={r.get('hidden')} "
                                    f"overlay={r.get('overlay')} "
                                    f"css={r.get('css')} "
                                    f"countdown={r.get('countdown')}"
                                )
                            else:
                                log(f"status non-dict={r!r}")
                    else:
                        log("Ingen main page http(s)-tabs fundet i kørende Chrome.")
                    last_summary = now
        except Exception as e:
            log(f"FEJL i loop: {e}")

        await asyncio.sleep(INTERVAL)


def main() -> int:
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        log("Stopper.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
