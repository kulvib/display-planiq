#!/usr/bin/env python3
"""Reliable Chromium proof of one pinned FreeRDP WASM artifact; localhost and dummy credentials only."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from threading import Thread
import json
import os
import re
import shutil
import time

from playwright.sync_api import sync_playwright, TimeoutError as ChromeTimeout
import diagnose_freerdp_wasm_browser as baseline

ASSETS = Path(os.environ["CF_FREERDP_ASSET_ROOT"]).resolve()
EXPECTED = {
    "sdl-freerdp.js": "c7d0a7e20a7b6473c5743892086b00dfb096807b8386adf992ab294867ad8112",
    "sdl-freerdp.wasm": "f5cfa907421b47c3ed6acdee329f5ebda7e9279c4a5972e02139dc8e2fe6f315",
}


class Handler(baseline.Handler):
    def do_GET(self):
        if self.headers.get("Upgrade", "").lower() == "websocket":
            self.server.ws_attempts += 1
            self.send_error(403, "Offline test deliberately rejects RDP")
            return
        return super().do_GET()


def main():
    info = json.loads((ASSETS / "provenance.json").read_text(encoding="utf-8"))
    if (info["freerdp_source_commit"] != "65bcca1913a28cbdd7eb913599f692bd2b707991"
            or info["emsdk"] != "6.0.12"):
        raise RuntimeError("Untrusted artifact source")
    for name, expected in EXPECTED.items():
        content = (ASSETS / name).read_bytes()
        if (sha256(content).hexdigest() != expected or
                info["files"][name]["sha256"] != expected or
                len(content) != info["files"][name]["bytes"]):
            raise RuntimeError("Untrusted binary: " + name)
    binary = next((shutil.which(x) for x in
                   ("google-chrome", "chromium", "chromium-browser") if shutil.which(x)), None)
    if not binary:
        raise RuntimeError("Chromium missing")
    baseline.ROOT = ASSETS
    server = baseline.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.ws_attempts = 0
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=binary, headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-background-networking", "--no-proxy-server"]
            )
            try:
                for variant in ("version", "minimal"):
                    before = server.ws_attempts
                    context = browser.new_context(viewport={"width": 1280, "height": 800})
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda exc: errors.append(str(exc)[:180]))
                    try:
                        page.goto(
                            f"http://127.0.0.1:{server.server_port}/probe?case={variant}",
                            wait_until="domcontentloaded", timeout=30000,
                        )
                        page.wait_for_function(
                            "() => {const e=document.getElementById('result');"
                            "if(!e)return false;try{return JSON.parse(e.textContent).initialized}"
                            "catch{return false}}",
                            timeout=30000,
                        )
                        if variant == "version":
                            page.wait_for_function(
                                "() => JSON.parse(document.getElementById('result').textContent).exit===0",
                                timeout=15000,
                            )
                        else:
                            deadline = time.monotonic() + 25
                            while time.monotonic() < deadline:
                                if server.ws_attempts > before:
                                    break
                                result = json.loads(page.locator("#result").inner_text())
                                if result.get("exit") is not None:
                                    break
                                time.sleep(0.25)
                        result = json.loads(page.locator("#result").inner_text())
                        diagnostic = [
                            x for x in result.get("output", [])
                            if re.search(r"display|monitor|SDL|socket|error", x, re.I)
                        ][-12:]
                        attempts = server.ws_attempts - before
                        print(json.dumps({
                            "case": variant, "initialized": result.get("initialized"),
                            "exit": result.get("exit"), "ws_attempts": attempts,
                            "screen": result.get("viewport"),
                            "diagnostic": diagnostic, "browser_errors": errors[-3:],
                        }, ensure_ascii=False), flush=True)
                        if variant == "version" and result.get("exit") != 0:
                            raise RuntimeError("FreeRDP version query failed")
                        if variant == "minimal":
                            all_output = " ".join(result.get("output", [])).lower()
                            if ("invalid size 0x0" in all_output or
                                "no usable size" in all_output):
                                raise RuntimeError("Original zero-size SDL monitor problem persists")
                            if attempts < 1:
                                raise RuntimeError("No actual localhost WebSocket upgrade attempted")
                    except ChromeTimeout as exc:
                        print("CHROME_TIMEOUT", variant,
                              "socket_attempts", server.ws_attempts - before,
                              "errors", errors[-3:], flush=True)
                        raise RuntimeError("Chrome initialization deadline exceeded") from exc
                    finally:
                        context.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
    print("PINNED_WASM_BROWSER_WEBSOCKET_PROOF=PASS", flush=True)


if __name__ == "__main__":
    main()
