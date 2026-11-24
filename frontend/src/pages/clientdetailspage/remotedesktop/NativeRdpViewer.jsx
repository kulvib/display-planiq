import React, { useCallback, useEffect, useRef, useState } from "react";
import { Box, Button, ButtonGroup, IconButton, Paper, Stack, Tooltip, Typography } from "@mui/material";
import RemoveIcon from "@mui/icons-material/Remove";
import AddIcon from "@mui/icons-material/Add";
import FitScreenIcon from "@mui/icons-material/FitScreen";
import LinkOffIcon from "@mui/icons-material/LinkOff";
import FullscreenIcon from "@mui/icons-material/Fullscreen";
import FullscreenExitIcon from "@mui/icons-material/FullscreenExit";
import { createBrowserWsTicket, getRemoteDesktopBrowserWsUrl } from "../../../api";
import { normalizeNativeRdpFingerprint } from "./nativeRdpFingerprint";
import { createNativeRdpAutologin } from "./nativeRdpAutologin.mjs";

/**
 * Disposable, same-origin sandbox for the official FreeRDP SDL3/Emscripten client.
 * Removing the iframe destroys its WASM heap, sockets and threads.
 * RDP credentials never go through a PlanIQ HTTP endpoint or storage.
 */
export default function NativeRdpViewer({ clientId, sessionId, requestAutologin, autologinMessage, desired = true, onDesiredChange }) {
  const iframeRef = useRef(null);
  const panelRef = useRef(null);
  const autoLoginRef = useRef(null);
  const operationRef = useRef(0);
  const managedRequestRef = useRef(null);
  const autoAttemptedRef = useRef(false);
  const transportReadyRef = useRef(false);
  const retryCountRef = useRef(0);
  const [recovering, setRecovering] = useState(false);
  const [retryAllowed, setRetryAllowed] = useState(false);
  const launchInProgressRef = useRef(false);
  const [autoPendingRequestId, setAutoPendingRequestId] = useState(null);
  const automatic = import.meta.env.VITE_NATIVE_RDP_AUTOLOGIN === "true" && Number(clientId) === 3;
  const [boot, setBoot] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState("Klar til forbindelse");
  const [working, setWorking] = useState(false);
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
        const ready = event.data.message === "Forbundet";
        if (ready) {
          transportReadyRef.current = true;
          retryCountRef.current = 0;
        }
        setStatus(ready ? "Forbundet" : "Forbinder …");
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
        setResolution(null);
        const shouldRecover = transportReadyRef.current && desired;
        transportReadyRef.current = false;
        setRecovering(shouldRecover);
        launchInProgressRef.current = false;
        setRetryAllowed(!shouldRecover);
        setStatus(shouldRecover ? "Genopretter forbindelse …" : "Forbindelsen blev afbrudt. Prøv igen.");
        setWorking(false);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [cancelManaged, desired]);

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
      setStatus("Forbinder …");
    } catch {
      if (operationRef.current !== operation) return;
      cancelManaged();
      setBoot(null);
      launchInProgressRef.current = false;
      setRetryAllowed(true);
      setStatus("Forbindelsen kunne ikke oprettes. Prøv igen.");
      setWorking(false);
    }
  }, [clientId, sessionId, verifyWasm, cancelManaged]);

  const startAutomatic = useCallback(async () => {
    if (!automatic || !sessionId || working || launchInProgressRef.current || !requestAutologin) return;
    launchInProgressRef.current = true;
    setRetryAllowed(false);
    onDesiredChange?.(true);
    autoAttemptedRef.current = true;
    transportReadyRef.current = false;
    setRecovering(false);
    setWorking(true);
    setResolution(null);
    setStatus("Forbinder …");
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
      setStatus("Forbinder …");
    } catch {
      if (operationRef.current !== operation) return;
      cancelManaged();
      autoLoginRef.current = null;
      setAutoPendingRequestId(null);
      launchInProgressRef.current = false;
      setRetryAllowed(true);
      setWorking(false);
      setStatus("Forbindelsen kunne ikke oprettes. Prøv igen.");
    }
  }, [automatic, sessionId, working, requestAutologin, verifyWasm, cancelManaged, onDesiredChange]);

  useEffect(() => {
    if (!automatic || !desired || !sessionId || working || autoAttemptedRef.current) return undefined;
    // Defer until the mount is committed. A StrictMode setup/cleanup replay
    // must not consume this generation's one automatic opening.
    const timer = window.setTimeout(() => { void startAutomatic(); }, 0);
    return () => window.clearTimeout(timer);
  }, [automatic, desired, sessionId, working, startAutomatic]);

  // Retry an unexpectedly lost, previously active transport. A denied setup
  // requires explicit user action; no credentials or tickets are replayed.
  useEffect(() => {
    if (!recovering || !desired || !sessionId || working) return undefined;
    const delays = [3000, 6000, 12000];
    const delay = delays[retryCountRef.current];
    if (delay === undefined) {
      setRecovering(false);
      setRetryAllowed(true);
      setStatus("Forbindelsen blev afbrudt. Prøv igen.");
      return undefined;
    }
    const timer = window.setTimeout(() => {
      retryCountRef.current += 1;
      void startAutomatic();
    }, delay);
    return () => window.clearTimeout(timer);
  }, [recovering, desired, sessionId, working, startAutomatic]);

  useEffect(() => {
    if (!automatic || !working || !autologinMessage || !autoLoginRef.current) return;
    const handle = autoLoginRef.current;
    if (autologinMessage.request_id !== handle.request.request_id) return;
    autoLoginRef.current = null;
    setAutoPendingRequestId(null);
    if (autologinMessage.type === "native_rdp_autologin_denied") {
      cancelManaged();
      launchInProgressRef.current = false;
      setRetryAllowed(true);
      setWorking(false);
      setStatus("Forbindelse ikke tilgængelig. Prøv igen.");
      return;
    }
    if (autologinMessage.type !== "native_rdp_autologin_envelope") return;
    const operation = operationRef.current;
    void handle.open(autologinMessage.envelope).then((credentials) =>
      launchWithCredentials(credentials, operation)
    ).catch(() => {
      if (operationRef.current !== operation) return;
      cancelManaged();
      launchInProgressRef.current = false;
      setRetryAllowed(true);
      setWorking(false);
      setStatus("Forbindelsen kunne ikke godkendes.");
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
        launchInProgressRef.current = false;
        setRetryAllowed(true);
        setWorking(false);
        setStatus("Forbindelsen kunne ikke oprettes. Prøv igen.");
      }
    }, 190000);
    return () => window.clearTimeout(id);
  }, [automatic, working, autoPendingRequestId, cancelManaged]);

  useEffect(() => () => {
    operationRef.current += 1;
    cancelManaged();
    launchInProgressRef.current = false;
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
    launchInProgressRef.current = false;
    setRetryAllowed(true);
    onDesiredChange?.(false);
    autoAttemptedRef.current = true;
    retryCountRef.current = 0;
    transportReadyRef.current = false;
    setRecovering(false);
    setBoot(null);
    setWorking(false);
    autoLoginRef.current = null;
    setAutoPendingRequestId(null);
    setStatus("Forbindelsen er afsluttet.");
    setResolution(null);
  };

  useEffect(() => {
    if (!working && fullscreen && document.fullscreenElement === panelRef.current) {
      document.exitFullscreen().catch(() => {});
    }
  }, [working, fullscreen]);

  return (
    <Paper ref={panelRef} elevation={0} sx={{ p: { xs: 1, md: 1.25 }, bgcolor: "#0b0f14", color: "#f8fafc", border: "1px solid rgba(148,163,184,0.16)", borderRadius: 2,
      "&:fullscreen": { p: 1, width: "100%", height: "100%", boxSizing: "border-box" } }}>
      <Stack spacing={1} sx={fullscreen ? { height: "100%", minHeight: 0 } : undefined}>
        {!working && (
          <Stack alignItems="center" spacing={1} sx={{ py: 4 }}>
            {automatic && sessionId && (!desired || retryAllowed) && (
              <Button variant="contained" onClick={startAutomatic}>Forbind</Button>
            )}
            {automatic && desired && !retryAllowed && <Button size="small" onClick={disconnect}>Afbryd</Button>}
            <Typography variant="body2" aria-live="polite">
              {!automatic ? "Remote Desktop er ikke aktiveret for denne klient." :
                !desired ? "Forbindelsen er afsluttet." :
                !sessionId ? "Venter på klient …" :
                !retryAllowed && !recovering ? "Forbinder …" : status}
            </Typography>
          </Stack>
        )}
        {working && (
          <Stack direction="row" useFlexGap flexWrap="wrap" gap={1} alignItems="center"
            sx={{ p: 0.75, bgcolor: "rgba(15,23,42,0.65)", borderRadius: 1.5,
              border: "1px solid rgba(148,163,184,0.14)",
              "& .MuiButton-root": { height: 36, textTransform: "none", fontWeight: 650 },
              "& .MuiIconButton-root": { width: 36, height: 36 } }}>
            <ButtonGroup size="small" variant="outlined" aria-label="Visning" sx={{ "& .MuiButton-root": { borderColor: "rgba(148,163,184,0.26)" } }}>
              <Button variant={displayMode === "fit" ? "contained" : "outlined"}
                color={displayMode === "fit" ? "primary" : "inherit"} startIcon={<FitScreenIcon />}
                title="Tilpas uden opskalering" aria-pressed={displayMode === "fit"}
                onClick={() => chooseDisplayMode("fit")}>Tilpas</Button>
              <Button variant={displayMode === "native" ? "contained" : "outlined"}
                color={displayMode === "native" ? "primary" : "inherit"}
                title="Original pixelstørrelse (1:1)" aria-pressed={displayMode === "native"}
                onClick={() => chooseDisplayMode("native")}>1:1</Button>
            </ButtonGroup>
            <Stack direction="row" alignItems="center" role="group" aria-label="Zoom"
              sx={{ border: "1px solid rgba(148,163,184,0.26)", borderRadius: 1, height: 36, overflow: "hidden" }}>
              <IconButton size="small" color="inherit" aria-label="Zoom ud" disabled={selectedZoom <= 25}
                onClick={() => adjustZoom(-25)}><RemoveIcon fontSize="small" /></IconButton>
              <Box component="select" aria-label="Zoomniveau" value={displayMode === "zoom" ? zoom : ""}
                onChange={(event) => chooseDisplayMode("zoom", Number(event.target.value))}
                sx={{ bgcolor: "#141d2b", color: "white", height: "100%", minWidth: 76, px: 0.75,
                  border: 0, borderInline: "1px solid rgba(148,163,184,0.22)", font: "inherit", fontSize: 13 }}>
                {displayMode !== "zoom" && <option value="">{actualZoom}%</option>}
                {Array.from(new Set([25, 50, 75, 100, 125, 150, 175, 200,
                  ...(displayMode === "zoom" ? [zoom] : [])])).sort((a, b) => a - b)
                  .map((value) => <option key={value} value={value}>{value}%</option>)}
              </Box>
              <IconButton size="small" color="inherit" aria-label="Zoom ind" disabled={selectedZoom >= 200}
                onClick={() => adjustZoom(25)}><AddIcon fontSize="small" /></IconButton>
            </Stack>
            <Box sx={{ flex: 1 }} />
            <Tooltip title={fullscreen ? "Afslut fuldskærm" : "Fuldskærm"}>
              <IconButton size="small" color="inherit" onClick={toggleFullscreen} aria-label={fullscreen ? "Afslut fuldskærm" : "Fuldskærm"} sx={{ border: "1px solid rgba(148,163,184,0.26)", borderRadius: 1 }}>
                {fullscreen ? <FullscreenExitIcon /> : <FullscreenIcon />}
              </IconButton>
            </Tooltip>
            <Button size="small" variant="outlined" color="error" startIcon={<LinkOffIcon />} onClick={disconnect}>Afbryd</Button>
          </Stack>
        )}
        {working && fullscreenError && <Typography role="alert" variant="caption">{fullscreenError}</Typography>}
        {working && !resolution && (
          <Typography variant="body2" aria-live="polite">Forbinder …</Typography>
        )}
        {working && (
          <Box sx={{ width: "100%", height: fullscreen ? undefined : { xs: "65dvh", md: "max(480px, calc(100dvh - 230px))" },
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
