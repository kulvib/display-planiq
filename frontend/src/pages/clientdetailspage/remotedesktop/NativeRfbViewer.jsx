import { useEffect, useRef, useState } from "react";
import { Box, Chip, Stack, Typography } from "@mui/material";
import {
  createBrowserWsTicket,
  getBrowserWsProtocols,
  getNativeRfbBrowserWsUrl,
  openNativeRfbBrowserHttpRelay,
  sendNativeRfbBrowserHttpRelay,
  pollNativeRfbBrowserHttpRelay,
  closeNativeRfbBrowserHttpRelay,
} from "../../../api";
import {
  createHttpRelaySocket,
  createWebSocketWithHttpsFallback,
} from "../../../api/httpRelaySocket";
import { createNativeRfbSocket } from "./nativeRfbSocket.mjs";

// 63D-36: real browser component, intentionally NOT an independently
// deployable feature. Parent source flag and backend source flag are both OFF.
// It never exposes an admin-side RDP link, VNC port, credential or CDN script.
export default function NativeRfbViewer({ clientId, sessionId, active = false }) {
  const targetRef = useRef(null);
  const [phase, setPhase] = useState("Ikke aktiveret");
  const [transportName, setTransportName] = useState(null);

  useEffect(() => {
    if (!active || !clientId || !sessionId) return undefined;

    let disposed = false;
    let rawSocket = null;
    let transport = null;
    let rfb = null;
    setPhase("Forbereder sikker skærmforbindelse…");

    const start = async () => {
      // This code-split package is version-locked and is *only* loaded after
      // both a logged-in browser session and explicit pilot activation.
      const [{ default: RFB }, ticket] = await Promise.all([
        import("@novnc/novnc"),
        createBrowserWsTicket(clientId, "remote_desktop"),
      ]);
      if (disposed || !targetRef.current) return;

      transport = createWebSocketWithHttpsFallback({
        openWebSocket: () => new WebSocket(
          getNativeRfbBrowserWsUrl(clientId, sessionId),
          getBrowserWsProtocols(ticket),
        ),
        openHttpsRelay: async () => {
          const opened = await openNativeRfbBrowserHttpRelay(clientId, sessionId);
          const relayId = String(opened?.relay_id || "");
          if (!relayId) throw new Error("RFB HTTPS-relay gav ikke en sessionsidentitet");
          return createHttpRelaySocket({
            relayId,
            sendPayload: payload => sendNativeRfbBrowserHttpRelay(clientId, sessionId, relayId, payload),
            pollMessages: () => pollNativeRfbBrowserHttpRelay(clientId, sessionId, relayId, 25),
            closeRelay: () => closeNativeRfbBrowserHttpRelay(clientId, sessionId, relayId),
          });
        },
      });
      rawSocket = createNativeRfbSocket({ transport, sessionId });
      if (disposed) {
        rawSocket.close(1000, "viewer_unmounted");
        return;
      }

      // RFB(target, rawChannel) explicitly displays/controls pixels INSIDE
      // this PlanIQ Display element; nothing launches an external RDP app.
      rfb = new RFB(targetRef.current, rawSocket, { shared: false });
      rfb.scaleViewport = true;
      rfb.clipViewport = true;
      rfb.focusOnClick = true;
      rfb.viewOnly = false;
      rfb.addEventListener("connect", () => {
        if (!disposed) {
          setPhase("GNOME-skrivebord forbundet");
          setTransportName(transport.transport);
        }
      });
      rfb.addEventListener("disconnect", () => {
        if (!disposed) setPhase("Skærmforbindelsen er afbrudt");
      });
      rfb.addEventListener("securityfailure", () => {
        if (!disposed) setPhase("RFB-sikkerhedskontrollen afviste forbindelsen");
      });
      setPhase("Venter på godkendt RFB-agent…");
    };

    void start().catch(() => {
      if (!disposed) {
        setPhase("Den sikre RFB-forbindelse kunne ikke oprettes");
        try { rawSocket?.close(1008, "viewer_setup_error"); } catch { /* already closed */ }
        try { transport?.close(1008, "viewer_setup_error"); } catch { /* already closed */ }
      }
    });

    return () => {
      disposed = true;
      // Disconnect first, so noVNC releases stuck modifier keys and canvas
      // handlers before the short-lived authenticated relay is destroyed.
      try { rfb?.disconnect(); } catch { /* possibly already disconnected */ }
      try { rawSocket?.close(1000, "viewer_unmounted"); } catch { /* already closed */ }
      try { transport?.close(1000, "viewer_unmounted"); } catch { /* already closed */ }
    };
  }, [active, clientId, sessionId]);

  return (
    <Stack spacing={1} sx={{ minWidth: 0 }}>
      <Box
        ref={targetRef}
        aria-label="GNOME Remote Desktop via PlanIQ Display"
        tabIndex={0}
        sx={{
          width: "100%",
          aspectRatio: "16 / 9",
          bgcolor: "#020617",
          borderRadius: 1.5,
          overflow: "hidden",
          outline: "none",
          "& canvas": { maxWidth: "100%" },
        }}
      />
      <Stack direction="row" spacing={1} alignItems="center">
        <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
          {phase}
        </Typography>
        {transportName && (
          <Chip size="small" variant="outlined" label={
            transportName === "https_long_poll" ? "HTTPS-fallback" : "WebSocket"
          } />
        )}
      </Stack>
    </Stack>
  );
}
