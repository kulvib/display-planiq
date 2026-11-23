import React, { useCallback, useEffect, useRef, useState } from "react";
import { Box, Button, Paper, Stack, TextField, Typography } from "@mui/material";
import { createBrowserWsTicket, getRemoteDesktopBrowserWsUrl } from "../../../api";
import { normalizeNativeRdpFingerprint } from "./nativeRdpFingerprint";

/**
 * Disposable, same-origin sandbox for the official FreeRDP SDL3/Emscripten client.
 * Removing the iframe destroys its WASM heap, sockets and threads.
 * RDP credentials never go through a PlanIQ HTTP endpoint or storage.
 */
export default function NativeRdpViewer({ clientId, sessionId, onFallback }) {
  const iframeRef = useRef(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [fingerprint, setFingerprint] = useState("");
  const normalizedFingerprint = normalizeNativeRdpFingerprint(fingerprint);
  const [boot, setBoot] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState("GNOME RDP-pilot er klar til forbindelse.");
  const [working, setWorking] = useState(false);
  const [performance, setPerformance] = useState(null);
  const [resolution, setResolution] = useState(null);
  const [displayMode, setDisplayMode] = useState("fit");

  useEffect(() => {
    const onMessage = (event) => {
      if (event.origin !== window.location.origin ||
          event.source !== iframeRef.current?.contentWindow) return;
      if (event.data?.type === "planiq-native-rdp-status") {
        setStatus(String(event.data.message || "Forbundet").slice(0, 180));
      }
      if (event.data?.type === "planiq-native-rdp-performance") {
        const data = event.data;
        const keys = [
          "pointerEvents", "maxBrowserEventLagMs",
          "peakOutboundQueueBytes", "maxBrowserTimerSlipMs"
        ];
        if (keys.every((key) =>
          Number.isSafeInteger(data[key]) && data[key] >= 0 &&
          data[key] <= 10_000_000
        )) {
          setPerformance({
            pointerEvents: data.pointerEvents,
            eventLag: data.maxBrowserEventLagMs,
            queueKiB: Math.ceil(data.peakOutboundQueueBytes / 1024),
            timerSlip: data.maxBrowserTimerSlipMs,
          });
        }
      }
      if (event.data?.type === "planiq-native-rdp-resolution") {
        const { sourceWidth, sourceHeight, displayWidth, displayHeight, mode } = event.data;
        const pixels = [sourceWidth, sourceHeight, displayWidth, displayHeight];
        if (pixels.every((n) => Number.isSafeInteger(n) && n >= 1 && n <= 32768) &&
            (mode === "fit" || mode === "native")) {
          setResolution({ sourceWidth, sourceHeight, displayWidth, displayHeight, mode });
        }
      }
      if (event.data?.type === "planiq-native-rdp-error") {
        setStatus(String(event.data.message || "RDP-fejl").slice(0, 180));
        setWorking(false);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  const start = useCallback(async () => {
    if (!sessionId || !username.trim() || !password || !normalizedFingerprint || working) return;
    setWorking(true);
    setPerformance(null);
    setResolution(null);
    setStatus("Kontrollerer WASM-browsermiljø …");
    try {
      if (!window.crossOriginIsolated || typeof SharedArrayBuffer === "undefined") {
        throw new Error("FreeRDP kræver COOP/COEP browserisolering på Remote Desktop-siden.");
      }
      const asset = await fetch("/native-rdp/sdl-freerdp.js", { method: "HEAD", cache: "no-store" });
      if (!asset.ok || !String(asset.headers.get("content-type") || "").includes("javascript")) {
        throw new Error("Det verificerede FreeRDP WebAssembly-build er endnu ikke installeret.");
      }
      const issued = await createBrowserWsTicket(clientId, "remote_desktop");
      const browserUrl = getRemoteDesktopBrowserWsUrl(clientId);
      if (!browserUrl.endsWith("/ws") || !issued?.ticket) {
        throw new Error("RDP-browsergodkendelsen blev ikke oprettet.");
      }
      const tunnelUrl = browserUrl.replace(/\/ws$/, "/native-rdp/" + encodeURIComponent(sessionId) + "/ws");
      setBoot({
        tunnelUrl, ticket: issued.ticket, subprotocol: issued.subprotocol,
        username: username.trim(), password, fingerprint: normalizedFingerprint,
      });
      setAttempt((value) => value + 1);
      setPassword("");
      setStatus("Indlæser FreeRDP i PlanIQ Display …");
    } catch (error) {
      setStatus(error?.message || "FreeRDP kunne ikke startes.");
      setWorking(false);
    }
  }, [clientId, sessionId, username, password, normalizedFingerprint, working]);

  const onLoad = useCallback(() => {
    if (!boot || !iframeRef.current?.contentWindow) return;
    iframeRef.current.contentWindow.postMessage({
      type: "planiq-native-rdp-start",
      sessionId,
      tunnelUrl: boot.tunnelUrl,
      ticket: boot.ticket,
      subprotocol: boot.subprotocol,
      username: boot.username,
      password: boot.password,
      fingerprint: boot.fingerprint,
      displayMode,
    }, window.location.origin);
    setBoot(null);
  }, [boot, sessionId, displayMode]);

  const chooseDisplayMode = useCallback((mode) => {
    if (mode !== "fit" && mode !== "native") return;
    setDisplayMode(mode);
    iframeRef.current?.contentWindow?.postMessage(
      { type: "planiq-native-rdp-display-mode", mode },
      window.location.origin
    );
  }, []);

  return (
    <Paper sx={{ p: 2, bgcolor: "rgba(2,6,23,0.9)", color: "white" }}>
      <Stack spacing={1.2}>
        <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
          GNOME RDP · FreeRDP WebAssembly · Viborg1-pilot
        </Typography>
        <Typography variant="body2">
          Skærm, mus og tastatur håndteres direkte af FreeRDP inde i denne webside. RDP-brugernavn
          og adgangskode indtastes kun i browseren og gemmes ikke i PlanIQ-databasen.
        </Typography>
        {!working && (
          <Stack spacing={1}>
            <TextField
              size="small" label="Verificeret SHA-256-fingeraftryk for GNOME RDP-certifikatet"
              value={fingerprint} onChange={(event) => setFingerprint(event.target.value)}
              autoComplete="off" placeholder="AA:BB:CC:… (64 hextegn)"
              error={fingerprint.trim().length > 0 && !normalizedFingerprint}
              helperText="Hentes fra Viborg1 via en betroet administrationsterminal. Indtast ikke et fingeraftryk fra en ukendt RDP-forbindelse."
              slotProps={{ htmlInput: { maxLength: 120, spellCheck: "false" } }}
              sx={{ bgcolor: "white", borderRadius: 1 }}
            />
            <Stack direction={{ xs: "column", md: "row" }} spacing={1}>
            <TextField size="small" label="GNOME RDP-brugernavn"
              value={username} onChange={(event) => setUsername(event.target.value)}
              autoComplete="off" slotProps={{ htmlInput: { maxLength: 128 } }}
              sx={{ bgcolor: "white", borderRadius: 1, flex: 1 }} />
            <TextField size="small" type="password" label="GNOME RDP-adgangskode"
              value={password} onChange={(event) => setPassword(event.target.value)}
              autoComplete="off" sx={{ bgcolor: "white", borderRadius: 1, flex: 1 }} />
            <Button variant="contained" disabled={!username.trim() || !password || !sessionId || !normalizedFingerprint}
              onClick={start}>Forbind GNOME RDP</Button>
            </Stack>
          </Stack>
        )}
        <Typography variant="body2" aria-live="polite">{status}</Typography>
        {working && (
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
            <Button variant={displayMode === "fit" ? "contained" : "outlined"}
              color="inherit" onClick={() => chooseDisplayMode("fit")}>
              Tilpas uden opskalering
            </Button>
            <Button variant={displayMode === "native" ? "contained" : "outlined"}
              color="inherit" onClick={() => chooseDisplayMode("native")}>
              Original pixelstørrelse (1:1)
            </Button>
          </Stack>
        )}
        {working && resolution && (
          <Typography variant="caption" sx={{ color: "#cbd5e1" }}>
            FreeRDP-canvas: {resolution.sourceWidth} × {resolution.sourceHeight} px ·
            vist: {resolution.displayWidth} × {resolution.displayHeight} CSS-px
            ({resolution.mode === "native" ? "1:1" : "tilpasset uden opskalering"}).
            Dette er browserens billedflade, ikke en verificeret måling af Viborg1’s fysiske skærmopløsning.
          </Typography>
        )}
        {working && performance?.pointerEvents > 0 && (
          <Typography variant="caption" sx={{ color: "#cbd5e1" }}>
            Browserens musehændelser: {performance.pointerEvents} ·
            maksimal lokal eventforsinkelse {performance.eventLag} ms ·
            maksimal WSS-afsendelseskø {performance.queueKiB} KiB ·
            største lokal timerforsinkelse {performance.timerSlip} ms.
            Målingerne er ikke RDP-returforsinkelse.
          </Typography>
        )}
        {working && <Button variant="outlined" color="inherit" onClick={() => {
          iframeRef.current?.contentWindow?.postMessage(
            { type: "planiq-native-rdp-visible-confirmed" }, window.location.origin
          );
        }}>Jeg kan se GNOME-skrivebordet (bekræft fysisk billede)</Button>}
        {working && <Button variant="outlined" color="inherit" onClick={() => {
          setBoot(null);
          setWorking(false);
          setStatus("RDP-session lukket. Indtast login igen for at genforbinde.");
          setResolution(null);
        }}>Afbryd RDP</Button>}
        {working && (
          <Box sx={{ width: "100%", minHeight: 520, bgcolor: "#000", borderRadius: 1, overflow: "hidden" }}>
            <iframe
              key={sessionId + ":" + attempt}
              ref={iframeRef}
              title="PlanIQ indbygget GNOME Remote Desktop"
              src="/native-rdp/viewer.html"
              onLoad={onLoad}
              allowFullScreen
              style={{ border: 0, width: "100%", minHeight: "70vh", display: "block" }}
            />
          </Box>
        )}
        <Button variant="outlined" color="inherit" onClick={onFallback}>
          Brug almindelig HTTPS/JPEG-visning
        </Button>
      </Stack>
    </Paper>
  );
}
