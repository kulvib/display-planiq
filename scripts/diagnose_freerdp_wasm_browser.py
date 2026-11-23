#!/usr/bin/env python3
"""Offline Chromium/Emscripten FreeRDP startup matrix. NEVER uses real RDP credentials.

Same checked-in, SHA-256-pinned JS/WASM as the production pilot. No API/backend,
GNOME RDP connection, remote login or untrusted external services.
"""
from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from html import unescape
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import tempfile
from threading import Thread

ROOT = Path(__file__).resolve().parents[1] / "frontend" / "public" / "native-rdp"
CASES = ("version", "minimal", "no_cert", "invalid_arg", "canvas_styled", "screen_fallback")

HTML = r'''<!doctype html>
<html><head><meta charset="utf-8"></head>
<body><canvas id="desktop" width="960" height="600"></canvas><pre id="result">PENDING</pre>
<script>
"use strict";
const variant = new URL(location.href).searchParams.get("case");
const common = ["/v:127.0.0.1:3389","/u:ci-dummy","/p:ci-fake-password"];
const cert = "/cert:fingerprint:sha256:" + Array(32).fill("00").join(":");
const variants = {
  version: ["/version"],
  minimal: [...common, cert],
  no_cert: [...common],
  invalid_arg: ["/this-option-does-not-exist"],
  canvas_styled: [...common, cert],
  screen_fallback: [...common, cert]
};
if(variant==="canvas_styled") {
  document.documentElement.style.height="100%";
  document.body.style.cssText="margin:0;width:100vw;height:100vh";
  const canvas=document.getElementById("desktop");
  canvas.style.cssText="width:100vw;height:100vh;display:block";
  canvas.width=1200;
  canvas.height=720;
}
const nativeScreen={width:window.screen.width,height:window.screen.height};
let screenShim="not-requested";
if(variant==="screen_fallback") {
  try {
    Object.defineProperty(window.screen,"width",{value:1280,configurable:true});
    Object.defineProperty(window.screen,"height",{value:720,configurable:true});
    screenShim="attempted";
  } catch(e) {screenShim="rejected"; }
}
let events=[];
const state={variant, isolated:crossOriginIsolated,
             viewport:{innerWidth:innerWidth,innerHeight:innerHeight,
              screenWidth:screen.width,screenHeight:screen.height,
              nativeScreenWidth:nativeScreen.width,nativeScreenHeight:nativeScreen.height,
              canvasWidth:document.getElementById("desktop").width,
              canvasHeight:document.getElementById("desktop").height,screenShim},
             initialized:false,
             exit:null, exception:null, output:[]};
function report(){
  state.output=events.slice(-28);
  document.getElementById("result").textContent=JSON.stringify(state);
}
const masked=(raw)=>String(raw).slice(0,230)
 .replace(/\/p:[^\s]+/g,"/p:[redacted]")
 .replace(/ci-fake-password/g,"[redacted]");
const collect=(category,line)=>{
  const message=masked(line);
  events.push(category+":"+message);
  if(events.length>80)events.shift();
  report();
};
window.Module={
 canvas:document.getElementById("desktop"),
 websocket:{url:"ws://127.0.0.1:9/never-open",subprotocol:"binary"},
 print:(line)=>collect("out",line),
 printErr:(line)=>collect("err",line),
 onAbort:(error)=>collect("abort",error),
 onExit:(code)=>{state.exit=code;report();},
 onRuntimeInitialized:()=>{
   state.initialized=true;report();
   try{const rv=window.Module.callMain([...(variants[variant]||[])]);state.returnValue=rv;}
   catch(error){state.exception=String(error).slice(0,220);}
   report();
 }
};
report();
</script>
<script src="/sdl-freerdp.js"></script>
</body></html>'''

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        if self.path.startswith("/probe?"):
            data = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            super().do_GET()

    def end_headers(self):
        for key, value in (
            ("Cross-Origin-Opener-Policy", "same-origin"),
            ("Cross-Origin-Embedder-Policy", "require-corp"),
            ("Cross-Origin-Resource-Policy", "same-origin"),
            ("Cache-Control", "no-store"),
        ):
            self.send_header(key, value)
        super().end_headers()

    def log_message(self, *_args):
        pass

def main():
    import hashlib
    js=ROOT/"sdl-freerdp.js"
    wasm=ROOT/"sdl-freerdp.wasm"
    expected={
      "sdl-freerdp.js":"609715445d2dc9f637f386572566b10fa8b3b9f0736f483a1d6a5ed423ee8cb5",
      "sdl-freerdp.wasm":"808752fe85bb1d65964d19f4b5d40cf990d1708c437ff0e40ec92f5994d7cf90",
    }
    for f in (js,wasm):
        actual=hashlib.sha256(f.read_bytes()).hexdigest()
        if actual!=expected[f.name]:
            raise RuntimeError("Untrusted or different compiled FreeRDP artifact: "+f.name)
    browser=next((shutil.which(x) for x in ("google-chrome","chromium","chromium-browser")
                  if shutil.which(x)),None)
    if not browser:
        raise RuntimeError("Chromium/Chrome not installed: cannot claim an actual browser test")
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        for name in CASES:
            with tempfile.TemporaryDirectory(prefix="cf-wasm-chrome-") as profile:
                url=f"http://127.0.0.1:{server.server_port}/probe?case={name}"
                cmd=[browser,"--headless=new","--no-sandbox","--disable-dev-shm-usage",
                     "--no-first-run","--disable-background-networking","--disable-extensions","--window-size=1280,800",
                     f"--user-data-dir={profile}","--virtual-time-budget=16000",
                     "--dump-dom",url]
                try:
                    run=subprocess.run(cmd,capture_output=True,text=True,timeout=85,check=False)
                except subprocess.TimeoutExpired:
                    print(f"{name}: BROWSER_PROCESS_TIMEOUT",flush=True)
                    continue
                match=re.search(r'<pre id="result">(.*?)</pre>',run.stdout,re.DOTALL)
                if not match:
                    print(f"{name}: NO_DOM_RESULT browser_rc={run.returncode} "+
                          repr(run.stderr[-180:]),flush=True)
                    continue
                try:
                    state=json.loads(unescape(match.group(1)))
                except json.JSONDecodeError:
                    print(f"{name}: INVALID_DOM_RESULT",flush=True)
                    continue
                print(json.dumps(state,ensure_ascii=False),flush=True)
                if not state.get("initialized"):
                    print(f"{name}: INITIALIZATION_UNVERIFIED",flush=True)
    finally:
        server.shutdown()
    print("OFFLINE_BROWSER_DIAGNOSTIC_COMPLETE=True",flush=True)

if __name__=="__main__":
    main()
