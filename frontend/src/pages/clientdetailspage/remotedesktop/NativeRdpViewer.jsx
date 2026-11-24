import React, { useCallback, useEffect, useRef, useState } from "react";
import { Box, Button, Paper, Stack, TextField, Typography } from "@mui/material";
import { createBrowserWsTicket, getRemoteDesktopBrowserWsUrl } from "../../../api";
import { normalizeNativeRdpFingerprint } from "./nativeRdpFingerprint";
import { createNativeRdpAutologin } from "./nativeRdpAutologin.mjs";

/**
 * Disposable, same-origin sandbox for the official FreeRDP SDL3/Emscripten client.
 * Removing the iframe destroys its WASM heap, sockets and threads.
 * RDP credentials never go through a PlanIQ HTTP endpoint or storage.
 */
export default function NativeRdpViewer({ clientId, sessionId, onFallback, requestAutologin, autologinMessage }) {
  const iframeRef = useRef(null);
  const panelRef = useRef(null);
  const autoLoginRef = useRef(null);
  const operationRef = useRef(0);
  const managedRequestRef = useRef(null);
  const [autoPendingRequestId, setAutoPendingRequestId] = useState(null);
  // Explicit pilot flag: legacy login remains rollback until the root broker,
  // client agent and Render are validated together on physical Viborg1.
  const automatic = import.meta.env.VITE_NATIVE_RDP_AUTOLOGIN === "true" && Number(clientId) === 3;
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
  const [zoom, setZoom] = useState(100);
  const [fullscreen, setFullscreen] = useState(false);
  const [fullscreenError, setFullscreenError] = useState("");

  const cancelManaged = useCallback(() => {
    const requestId = managedRequestRef.current;
    managedRequestRef.current = null;
    if (requestId) requestAutologin?.({ type: "native_rdp_autologin_cancel", request_id: requestId });
  }, [requestAutologin]);

  useEffect(() => {
    const sync = () => setFullscreen(document.fullscreenElement === panelRef.current);
    document.addEventListener("fullscreenchange", sync);
    return () => document.removeEventListener("fullscreenchange", sync);
  }, []);

  const toggleFullscreen = useCallback(async () => {
    try {
      setFullscreenError("");
      if (document.fullscreenElement === panelRef.current) {
        await document.exitFullscreen();
      } else if (panelRef.current?.requestFullscreen) {
        await panelRef.current.requestFullscreen();
      } else {
        throw new Error("fullscreen-unavailable");
      }
    } catch {
      setFullscreenError("Fuldskærm er ikke tilgængelig i denne browser.");
    }
  }, []);

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
            (mode === "fit" || mode === "native" || mode === "zoom")) {
          setResolution({ sourceWidth, sourceHeight, displayWidth, displayHeight, mode });
        }
      }
      if (event.data?.type === "planiq-native-rdp-error") {
        operationRef.current += 1;
        cancelManaged();
        autoLoginRef.current = null;
        setAutoPendingRequestId(null);
        setBoot(null);
        setStatus(String(event.data.message || "RDP-fejl").slice(0, 180));
        setWorking(false);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [cancelManaged]);

  const verifyWasm = useCallback(async () => {
    if (!window.crossOriginIsolated || typeof SharedArrayBuffer === "undefined") {
      throw new Error("FreeRDP kræver COOP/COEP browserisolering på Remote Desktop-siden.");
    }
    const asset = await fetch("/native-rdp/sdl-freerdp.js", { method: "HEAD", cache: "no-store" });
    if (!asset.ok || !String(asset.headers.get("content-type") || "").includes("javascript")) {
      throw new Error("Det verificerede FreeRDP WebAssembly-build er endnu ikke installeret.");
    }
  }, []);

  const launchWithCredentials = useCallback(async (credentials, operation) => {
    try {
      if (operationRef.current !== operation) return;
      await verifyWasm();
      if (operationRef.current !== operation) return;
      const verifiedFingerprint = normalizeNativeRdpFingerprint(credentials?.fingerprint);
      if (!credentials?.username || !credentials?.password || !verifiedFingerprint || !sessionId) {
        throw new Error("GNOME RDP-login er ikke gyldigt.");
      }
      const issued = await createBrowserWsTicket(clientId, "remote_desktop");
      if (operationRef.current !== operation) return;
      const browserUrl = getRemoteDesktopBrowserWsUrl(clientId);
      if (!browserUrl.endsWith("/ws") || !issued?.ticket) {
        throw new Error("RDP-browsergodkendelsen blev ikke oprettet.");
      }
      const tunnelUrl = browserUrl.replace(/\/ws$/, "/native-rdp/" + encodeURIComponent(sessionId) + "/ws");
      setBoot({
        tunnelUrl, ticket: issued.ticket, subprotocol: issued.subprotocol,
        username: credentials.username, password: credentials.password, fingerprint: verifiedFingerprint,
      });
      setAttempt((value) => value + 1);
      setPassword("");
      setStatus("Indlæser FreeRDP med midlertidigt automatisk login …");
    } catch (error) {
      if (operationRef.current !== operation) return;
      cancelManaged();
      setBoot(null);
      setStatus(error?.message || "FreeRDP kunne ikke startes.");
      setWorking(false);
    }
  }, [clientId, sessionId, verifyWasm, cancelManaged]);

  const start = useCallback(() => {
    if (!sessionId || !username.trim() || !password || !normalizedFingerprint || working) return;
    setWorking(true);
    setPerformance(null);
    setResolution(null);
    setStatus("Kontrollerer WASM-browsermiljø …");
    const operation = ++operationRef.current;
    void launchWithCredentials({ username: username.trim(), password, fingerprint: normalizedFingerprint }, operation);
  }, [sessionId, username, password, normalizedFingerprint, working, launchWithCredentials]);

  const startAutomatic = useCallback(async () => {
    if (!automatic || !sessionId || working || !requestAutologin) return;
    setWorking(true);
    setPerformance(null);
    setResolution(null);
    setStatus("Godkender engangsadgang for superadministrator …");
    const operation = ++operationRef.current;
    try {
      await verifyWasm();
      if (operationRef.current !== operation) return;
      const handle = await createNativeRdpAutologin(sessionId);
      if (operationRef.current !== operation) return;
      autoLoginRef.current = handle;
      setAutoPendingRequestId(handle.request.request_id);
      managedRequestRef.current = handle.request.request_id;
      if (!requestAutologin({ ...handle.request, managed: true })) {
        throw new Error("Superadministratorens Remote Desktop-session er ikke forbundet.");
      }
      setStatus("Klargør sikker Remote Desktop-forbindelse …");
    } catch (error) {
      if (operationRef.current !== operation) return;
      cancelManaged();
      autoLoginRef.current = null;
      setAutoPendingRequestId(null);
      setWorking(false);
      setStatus(error?.message || "Automatisk RDP-login kunne ikke startes.");
    }
  }, [automatic, sessionId, working, requestAutologin, verifyWasm, cancelManaged]);

  useEffect(() => {
    if (!automatic || !working || !autologinMessage || !autoLoginRef.current) return;
    const handle = autoLoginRef.current;
    if (autologinMessage.request_id !== handle.request.request_id) return;
    autoLoginRef.current = null;
    setAutoPendingRequestId(null);
    if (autologinMessage.type === "native_rdp_autologin_denied") {
      cancelManaged();
      setWorking(false);
      setStatus("Viborg1's beskyttede RDP-autologin er ikke tilgængeligt.");
      return;
    }
    if (autologinMessage.type !== "native_rdp_autologin_envelope") return;
    const operation = operationRef.current;
    void handle.open(autologinMessage.envelope).then((credentials) =>
      launchWithCredentials(credentials, operation)
    ).catch(() => {
      if (operationRef.current !== operation) return;
      cancelManaged();
      setWorking(false);
      setStatus("Krypteret RDP-login kunne ikke verificeres.");
    });
  }, [automatic, working, autologinMessage, launchWithCredentials, cancelManaged]);

  useEffect(() => {
    // Do not retain an ECDH key or leave the UI indefinitely on a lost broker.
    if (!automatic || !working || !autoPendingRequestId) return undefined;
    const id = window.setTimeout(() => {
      if (autoLoginRef.current?.request.request_id === autoPendingRequestId) {
        operationRef.current += 1;
        cancelManaged();
        autoLoginRef.current = null;
        setAutoPendingRequestId(null);
        setWorking(false);
        setStatus("RDP-autologin udløb; prøv igen med en ny session.");
      }
    }, 190000);
    return () => window.clearTimeout(id);
  }, [automatic, working, autoPendingRequestId, cancelManaged]);

  useEffect(() => () => {
    operationRef.current += 1;
    cancelManaged();
    autoLoginRef.current = null;
  }, [cancelManaged]);

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
      displayMode, zoom,
    }, window.location.origin);
    setBoot(null);
  }, [boot, sessionId, displayMode, zoom]);

  const chooseDisplayMode = useCallback((mode, percent = 100) => {
    if (mode !== "fit" && mode !== "native" &&
        !(mode === "zoom" && Number.isInteger(percent) && percent >= 25 && percent <= 200)) return;
    setDisplayMode(mode);
    setZoom(percent);
    iframeRef.current?.contentWindow?.postMessage(
      { type: "planiq-native-rdp-display-mode", mode, zoom: percent },
      window.location.origin
    );
  }, []);

  const actualZoom = resolution
    ? Math.round(100 * resolution.displayWidth / resolution.sourceWidth)
    : displayMode === "zoom" ? zoom : 100;
  const selectedZoom = displayMode === "zoom" ? zoom : actualZoom;
  const adjustZoom = (delta) => chooseDisplayMode("zoom",
    Math.min(200, Math.max(25, selectedZoom + delta)));

  const disconnect = () => {
    operationRef.current += 1;
    cancelManaged();
    setBoot(null);
    setWorking(false);
    autoLoginRef.current = null;
    setAutoPendingRequestId(null);
    setStatus("Forbindelsen er afsluttet.");
    setResolution(null);
    setPerformance(null);
  };

  useEffect(() => {
    if (!working && fullscreen && document.fullscreenElement === panelRef.current) {
      document.exitFullscreen().catch(() => {});
    }
  }, [working, fullscreen]);

  return (
    <Paper ref={panelRef} sx={{ p: 1, bgcolor: "#080c16", color: "white",
      "&:fullscreen": { p: 1, width: "100%", height: "100%", boxSizing: "border-box" } }}>
      <Stack spacing={1} sx={fullscreen ? { height: "100%", minHeight: 0 } : undefined}>
        {!working && <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>Remote Desktop</Typography>}
        {!working && automatic && (
          <Button variant="contained" disabled={!sessionId} onClick={startAutomatic}>
            Forbind sikkert med automatisk RDP-login
          </Button>
        )}
        {!working && !automatic && (
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
        {!working && <Typography variant="body2" aria-live="polite">{status}</Typography>}
        {working && (
          <Stack direction="row" spacing={0} useFlexGap flexWrap="wrap" gap={0.75} alignItems="center">
            <Button size="small" variant={displayMode === "fit" ? "contained" : "outlined"}
              color="inherit" title="Tilpas uden opskalering" aria-pressed={displayMode === "fit"}
              onClick={() => chooseDisplayMode("fit")}>Tilpas</Button>
            <Button size="small" variant={displayMode === "native" ? "contained" : "outlined"}
              color="inherit" title="Original pixelstørrelse (1:1)" aria-pressed={displayMode === "native"}
              onClick={() => chooseDisplayMode("native")}>1:1</Button>
            <Button size="small" color="inherit" aria-label="Zoom ud" disabled={selectedZoom <= 25}
              onClick={() => adjustZoom(-25)}>−</Button>
            <Box component="select" aria-label="Zoomniveau" value={displayMode === "zoom" ? zoom : ""}
              onChange={(event) => chooseDisplayMode("zoom", Number(event.target.value))}
              sx={{ bgcolor: "#141d2b", color: "white", border: "1px solid #64748b", borderRadius: 1, p: 0.75 }}>
              {displayMode !== "zoom" && <option value="">{actualZoom}%</option>}
              {Array.from(new Set([25, 50, 75, 100, 125, 150, 175, 200,
                ...(displayMode === "zoom" ? [zoom] : [])])).sort((a, b) => a - b)
                .map((value) => <option key={value} value={value}>{value}%</option>)}
            </Box>
            <Button size="small" color="inherit" aria-label="Zoom ind" disabled={selectedZoom >= 200}
              onClick={() => adjustZoom(25)}>+</Button>
            <Button size="small" color="inherit" onClick={toggleFullscreen}>
              {fullscreen ? "Afslut fuldskærm" : "Fuldskærm"}
            </Button>
            <Box sx={{ flex: 1 }} />
            <Button size="small" variant="outlined" color="inherit" onClick={disconnect}>Afbryd</Button>
          </Stack>
        )}
        {working && fullscreenError && <Typography role="alert" variant="caption">{fullscreenError}</Typography>}
        <Box component="details" sx={{ color: "#cbd5e1", fontSize: "0.8rem" }}>
          <Box component="summary" sx={{ cursor: "pointer" }}>Diagnostik</Box>
          {working && <Typography variant="body2">{status}</Typography>}
        {working && resolution && (
          <Typography variant="caption" sx={{ color: "#cbd5e1" }}>
            FreeRDP-canvas: {resolution.sourceWidth} × {resolution.sourceHeight} px ·
            vist: {resolution.displayWidth} × {resolution.displayHeight} CSS-px
            ({resolution.mode === "native" ? "1:1" : resolution.mode === "zoom" ? "zoom" : "tilpasset uden opskalering"}).
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
        }}>Bekræft fysisk billede</Button>}
          <Button size="small" variant="text" color="inherit" onClick={onFallback}>
            Brug HTTPS/JPEG-visning
          </Button>
        </Box>
        {working && (
          <Box sx={{ width: "100%", height: fullscreen ? undefined : "70vh",
            flex: fullscreen ? "1 1 0" : undefined, minHeight: fullscreen ? 0 : 320,
            bgcolor: "#000", borderRadius: 1, overflow: "hidden" }}>
            <iframe
              key={sessionId + ":" + attempt}
              ref={iframeRef}
              title="PlanIQ indbygget GNOME Remote Desktop"
              src="/native-rdp/viewer.html"
              onLoad={onLoad}
              allowFullScreen
              style={{ border: 0, width: "100%", height: "100%", display: "block" }}
            />
          </Box>
        )}
      </Stack>
    </Paper>
  );
}
