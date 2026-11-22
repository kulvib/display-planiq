/* FreeRDP SDL3/Emscripten sandbox. No localStorage, cookies, DOM credential fields
 * or cross-origin messages. The parent is the already-authorized PlanIQ viewer.
 * This page is deliberately not a generic public RDP console.
 */
(() => {
  "use strict";
  const element = document.getElementById("desktop");
  const status = document.getElementById("status");
  let started = false;
  const tell = (type, message) => {
    status.textContent = String(message).slice(0, 180);
    window.parent.postMessage({ type, message: status.textContent }, window.location.origin);
  };
  const error = (message) => tell("planiq-native-rdp-error", message);
  const update = (message) => tell("planiq-native-rdp-status", message);
  const isTunnelUrl = (raw) => {
    try {
      const url = new URL(raw);
      return (url.protocol === "wss:" || (url.hostname === "localhost" && url.protocol === "ws:")) &&
        /^\/api\/remote-desktop\/browser\/[0-9]+\/native-rdp\/[0-9a-f-]{36}\/ws$/.test(url.pathname) &&
        !url.username && !url.password && !url.hash && !url.search;
    } catch { return false; }
  };
  window.addEventListener("message", (event) => {
    if (started || event.source !== window.parent || event.origin !== window.location.origin) return;
    const data = event.data;
    if (!data || data.type !== "planiq-native-rdp-start") return;
    started = true;
    if (!window.crossOriginIsolated || typeof SharedArrayBuffer === "undefined") {
      error("GNOME RDP kræver COOP/COEP browserisolering.");
      return;
    }
    if (!isTunnelUrl(data.tunnelUrl) ||
        !/^[A-Za-z0-9_-]{32,256}$/.test(String(data.ticket || "")) ||
        data.subprotocol !== "planiq-ws-ticket" ||
        typeof data.username !== "string" || !data.username || data.username.length > 128 ||
        typeof data.password !== "string" || !data.password || data.password.length > 512) {
      error("RDP-login eller sessionsbinding er ugyldig.");
      return;
    }
    update("Starter FreeRDP …");
    let username = data.username;
    let password = data.password;
    window.Module = {
      canvas: element,
      websocket: {
        url: data.tunnelUrl,
        subprotocol: "binary,planiq-ws-ticket," + data.ticket,
      },
      print: () => {},
      printErr: () => {},
      onAbort: () => error("FreeRDP blev afbrudt. Kontrollér GNOME RDP og forbindelsen."),
      onRuntimeInitialized: () => {
        update("Forbinder til GNOME RDP via PlanIQ …");
        try {
          // GNOME authentication remains inside the end-to-end TLS-protected
          // RDP connection. The Render relay only sees opaque binary data.
          const args = [
            "/v:127.0.0.1:3389", "/u:" + username, "/p:" + password,
            "/cert:ignore", "/gfx", "/network:lan", "/log-level:ERROR",
          ];
          username = "";
          password = "";
          window.Module.callMain(args);
        } catch {
          error("FreeRDP kunne ikke etablere GNOME RDP-sessionen.");
        }
      },
    };
    // Zero the transport object after copying into Emscripten configuration.
    data.password = "";
    data.ticket = "";
    const script = document.createElement("script");
    script.src = "/native-rdp/sdl-freerdp.js";
    script.async = true;
    script.onerror = () => error("FreeRDP WASM-klienten mangler eller kunne ikke indlæses.");
    document.body.appendChild(script);
  });
})();
