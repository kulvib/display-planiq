/* FreeRDP SDL3/Emscripten sandbox. No localStorage, cookies, DOM credential fields
 * or cross-origin messages. The parent is the already-authorized PlanIQ viewer.
 * This page is deliberately not a generic public RDP console.
 */
(() => {
  "use strict";
  const element = document.getElementById("canvas");
  const status = document.getElementById("status");
  let started = false;
  let failed = false;
  let transportOpened = false;
  let bidirectionalTraffic = false;
  let transportTimer = null;
  let probe = null;
  let viewportFit = null;
  let lastProgressReport = 0;
  let pointerEventCount = 0;
  let pointerEventLagMaxMs = 0;
  // Passive observation only: SDL3 remains the sole owner of pointer input.
  element?.addEventListener?.("pointermove", (event) => {
    const mark = window.performance?.now?.();
    if (typeof mark !== "number" || !Number.isFinite(event.timeStamp)) return;
    const delay = mark - event.timeStamp;
    if (delay >= 0 && delay <= 10000) {
      pointerEventCount++;
      pointerEventLagMaxMs = Math.max(pointerEventLagMaxMs, Math.round(delay));
    }
  }, { passive: true });
  let safeFailureClass = "UNKNOWN";
  const tell = (type, message) => {
    status.textContent = String(message).slice(0, 180);
    status.hidden = type !== "planiq-native-rdp-error" && bidirectionalTraffic;
    window.parent.postMessage({ type, message: status.textContent }, window.location.origin);
  };
  const error = (message) => {
    if (failed) return;
    failed = true;
    if (transportTimer !== null) clearTimeout(transportTimer);
    probe?.dispose();
    viewportFit?.dispose();
    tell("planiq-native-rdp-error", message);
  };
  const update = (message) => {
    if (!failed) tell("planiq-native-rdp-status", message);
  };
  // Raw FreeRDP stderr can include /u: and /p: parameters. NEVER forward it.
  const classifyStderr = (raw) => {
    const line = String(raw || "");
    if (/SDL_Init failed|video driver|video subsystem/i.test(line)) safeFailureClass = "SDL";
    else if (/command.line|unknown option|invalid option|usage:/i.test(line)) safeFailureClass = "ARGUMENTS";
    else if (/certificate|X509|TLS/i.test(line)) safeFailureClass = "TLS";
    else if (/websocket|network|socket|connect/i.test(line)) safeFailureClass = "NETWORK";
  };
  const isTunnelUrl = (raw) => {
    try {
      const url = new URL(raw);
      return (url.protocol === "wss:" || (url.hostname === "localhost" && url.protocol === "ws:")) &&
        /^\/api\/remote-desktop\/browser\/[0-9]+\/native-rdp\/[0-9a-f-]{36}\/ws$/.test(url.pathname) &&
        !url.username && !url.password && !url.hash && !url.search;
    } catch { return false; }
  };
  window.addEventListener("message", (event) => {
    if (event.source !== window.parent || event.origin !== window.location.origin) return;
    const data = event.data;
    if (data?.type === "planiq-native-rdp-display-mode" && started && !failed) {
      if (data.mode === "native" || data.mode === "fit") {
        viewportFit?.setMode(data.mode);
      } else if (data.mode === "zoom" && Number.isInteger(data.zoom) && data.zoom >= 25 && data.zoom <= 200) {
        viewportFit?.setMode("zoom", data.zoom);
      }
      return;
    }
    if (started || !data || data.type !== "planiq-native-rdp-start") return;
    started = true;
    if (!window.crossOriginIsolated || typeof SharedArrayBuffer === "undefined") {
      error("GNOME RDP kræver COOP/COEP browserisolering.");
      return;
    }
    if (!isTunnelUrl(data.tunnelUrl) ||
        !/^[A-Za-z0-9_-]{32,256}$/.test(String(data.ticket || "")) ||
        data.subprotocol !== "planiq-ws-ticket" ||
        typeof data.username !== "string" || !data.username || data.username.length > 128 ||
        typeof data.password !== "string" || !data.password || data.password.length > 512 ||
        typeof data.fingerprint !== "string" || !/^(?:[0-9a-f]{2}:){31}[0-9a-f]{2}$/.test(data.fingerprint)) {
      error("RDP-login eller sessionsbinding er ugyldig.");
      return;
    }
    if (!element || element.tagName !== "CANVAS" || document.querySelector("#canvas") !== element) {
      error("SDL3-billedfladen #canvas mangler. RDP kan ikke vise skærmen.");
      return;
    }
    // Physical pilot only: exact client 3 has a measured 2560x1080 primary.
    // Request an initial RDP framebuffer, never a physical GNOME mode change.
    // This is an A/B candidate, not proof of a negotiated resolution.
    const isViborg1 = /^\/api\/remote-desktop\/browser\/3\/native-rdp\/[0-9a-f-]{36}\/ws$/
      .test(new URL(data.tunnelUrl).pathname);
    // CSS presentation scale only. SDL3 retains its actual RDP window size
    // and accounts for CSS-to-window scaling when converting pointer events.
    try {
      viewportFit = window.PlanIQNativeRdpViewport.install({
        canvas: element, viewport: document.getElementById("viewport"),
        mode: data.displayMode === "native" ? "native" :
          data.displayMode === "zoom" && Number.isInteger(data.zoom) &&
          data.zoom >= 25 && data.zoom <= 200 ? "zoom" : "fit",
        zoom: Number.isInteger(data.zoom) && data.zoom >= 25 && data.zoom <= 200 ? data.zoom : 100,
        onResize: ({ sourceWidth, sourceHeight, displayWidth, displayHeight, mode }) => {
          // Only integer canvas and CSS dimensions. This is not a measurement
          // of physical GNOME monitor resolution or RDP input latency.
          window.parent.postMessage({
            type: "planiq-native-rdp-resolution",
            sourceWidth, sourceHeight, displayWidth, displayHeight, mode,
          }, window.location.origin);
        },
      });
    } catch {
      error("RDP-skærmen kunne ikke tilpasses visningsrammen.");
      return;
    }
    update("Starter FreeRDP …");
    // The separate transport adapter is installed only in this disposable
    // same-origin iframe, without retaining credentials or inspecting payloads.
    try {
      probe = window.PlanIQNativeRdpProbe.install({
        url: data.tunnelUrl,
        onFailure: error,
        onProgress: (stats) => {
          if (failed || stats.openedAt === null) return;
          const now = Date.now();
          if (now - lastProgressReport < 3000 &&
              stats.toAgentBytes > 0 && stats.fromAgentBytes > 0) return;
          lastProgressReport = now;
          // These indicators measure browser-local responsiveness, NOT RDP RTT.
          window.parent.postMessage({
            type: "planiq-native-rdp-performance",
            pointerEvents: pointerEventCount,
            maxBrowserEventLagMs: pointerEventLagMaxMs,
            peakOutboundQueueBytes: stats.peakOutboundQueueBytes || 0,
            maxBrowserTimerSlipMs: stats.maxTimerSlipMs || 0,
          }, window.location.origin);
          if (stats.toAgentBytes && stats.fromAgentBytes) {
            // Transport activity is not proof of rendered desktop pixels.
            bidirectionalTraffic = true;
            update("Forbundet");
          } else if (stats.toAgentBytes) {
            update("Forbinder …");
          } else {
            update("Forbinder …");
          }
        },
      });
    } catch {
      error("RDP-transportens sikkerhedskontrol kunne ikke initialiseres.");
      return;
    }
    let username = data.username;
    let password = data.password;
    let certFingerprint = data.fingerprint;
    window.Module = {
      canvas: element,
      websocket: {
        url: data.tunnelUrl,
        subprotocol: "binary,planiq-ws-ticket," + data.ticket,
      },
      print: () => {},
      printErr: classifyStderr,
      onExit: (statusCode) => {
        const code = Number.isInteger(statusCode) && Math.abs(statusCode) <= 65535
          ? String(statusCode) : "unknown";
        error("FreeRDP afsluttede (exit=" + code + ", fase=" + safeFailureClass +
          "). Ingen fungerende RDP-session er etableret.");
      },
      onAbort: () => error("FreeRDP blev afbrudt. Kontrollér GNOME RDP og forbindelsen."),
      onRuntimeInitialized: () => {
        update("Forbinder til GNOME RDP via PlanIQ …");
        transportTimer = setTimeout(() => {
          if (!transportOpened) {
            const fsActive = window.Module.FS?.initialized === true;
            error("FreeRDP åbnede ingen RDP-WebSocket inden 15 sekunder (FS=" +
              (fsActive ? "aktiv" : "afsluttet") + ", fase=" + safeFailureClass +
              "). Opret en ny forbindelse.");
          }
        }, 15000);
        if (typeof window.Module.websocket?.on === "function") {
          window.Module.websocket.on("open", () => {
            transportOpened = true;
            if (transportTimer !== null) clearTimeout(transportTimer);
            update("Forbinder …");
          });
          window.Module.websocket.on("close", () => error("RDP-tunnelen blev lukket. Vælg en ny forbindelse."));
          window.Module.websocket.on("error", () => error("RDP-transportfejl. Kontrollér GNOME og WSS-forbindelsen."));
        }
        try {
          // GNOME authentication remains inside the end-to-end TLS-protected
          // RDP connection. The Render relay only sees opaque binary data.
          const args = [
            "/v:127.0.0.1:3389", "/u:" + username, "/p:" + password,
            "/cert:fingerprint:sha256:" + certFingerprint,
            ...(isViborg1 ? ["/size:2560x1080"] : []),
            // Pilot: explicit measured size for Viborg1 only; strict TLS pinning.
            // Optional GFX/network/log flags made the first WASM startup abort
            // before a socket could be observed; enable only when proven.

          ];
          username = "";
          password = "";
          certFingerprint = "";
          window.Module.callMain(args);
        } catch {
          error("FreeRDP kunne ikke etablere GNOME RDP-sessionen.");
        }
      },
    };
    // Zero the transport object after copying into Emscripten configuration.
    data.password = "";
    data.ticket = "";
    data.fingerprint = "";
    const script = document.createElement("script");
    script.src = "/native-rdp/sdl-freerdp.js";
    script.async = true;
    script.onerror = () => error("FreeRDP WASM-klienten mangler eller kunne ikke indlæses.");
    document.body.appendChild(script);
  });
})();
