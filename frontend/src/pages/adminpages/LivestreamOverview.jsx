import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Paper,
  Stack,
  TextField,
  MenuItem,
  Tooltip,
  Typography,
  useMediaQuery,
} from "@mui/material";
import FullscreenIcon from "@mui/icons-material/Fullscreen";
import GridViewIcon from "@mui/icons-material/GridView";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import { Link } from "react-router-dom";
import { apiUrl, authHeaders, authenticatedFetch, getAuthSessionSignal, getControlRoomClients, getOrganizations } from "../../api";
import { compactDarkChipSx } from "../../utils/chipStyles";
import AdminRefreshButton from "../../components/AdminRefreshButton";
import { clientMatchesSearch, organizationNamesById, sortLivestreamClients } from "../../utils/clientSearchSort.mjs";
import { MOBILE_LIVESTREAM_DURATIONS } from "../../utils/mobileLivestreamTiming.mjs";
import { useMobileLivestreamSession } from "../../utils/useMobileLivestreamSession";
import { createHlsReserveController, hlsHttpTransportLabel, livestreamLatencyStatus } from "../clientdetailspage/livestreamBrowserTiming.mjs";
import { createHlsGenerationObserver, createPilotTransport, generationFromHeartbeat, pilotGenerationFromHeartbeat } from "../clientdetailspage/livestreamPilotTransport.mjs";

const VIEWER_HEARTBEAT_MS = 25_000;
const PAGE_HIDDEN_WARM_GRACE_MS = 30_000;
const HEALTH_STARTUP_POLL_MS = 2_000;
const HEALTH_STARTUP_WARNING_MS = 15_000;

function isRequestTimeout(error) {
  return error?.name === "TimeoutError" || /signal.*timed out|timeout/i.test(String(error?.message || ""));
}

function makeViewerId(clientId) {
  const suffix = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `livestream-wall-${clientId}-${suffix}`.slice(0, 120);
}

async function sendViewerLeave(clientId, viewerId, source = "livestream_wall_leave") {
  if (!clientId || !viewerId) return;
  try {
    await fetch(`${apiUrl}/api/livestream-v2/hls/${encodeURIComponent(clientId)}/viewer-leave`, {
      method: "POST",
      credentials: "include",
      keepalive: true,
      headers: {
        ...authHeaders(),
        "Content-Type": "application/json",
        accept: "application/json",
      },
      body: JSON.stringify({ viewer_id: viewerId, source }),
    });
  } catch {
    // Best effort: backend lease remains the crash/reload recovery path.
  }
}

function LivestreamTile({ client, pageMediaActive }) {
  const rootRef = useRef(null);
  const previewRef = useRef(null);
  const videoRef = useRef(null);
  const hlsRef = useRef(null);
  const transportControllerRef = useRef(null);
  const wssActiveRef = useRef(false);
  const hlsReserveRef = useRef(null);
  const heartbeatTimerRef = useRef(null);
  const healthTimerRef = useRef(null);
  const viewerIdRef = useRef(makeViewerId(client.id));
  const mediaCapabilityRef = useRef("");
  const activeRef = useRef(false);
  const isTouchHandset = useMediaQuery("(hover: none) and (pointer: coarse) and (max-width: 1023.95px)");
  const mobileSession = useMobileLivestreamSession(isTouchHandset);
  const mobileViewerActive = !isTouchHandset || mobileSession.isActive;

  const [intersecting, setIntersecting] = useState(false);
  const [state, setState] = useState("idle");
  const [message, setMessage] = useState("");
  const [activeViewers, setActiveViewers] = useState(null);
  const [latencySeconds, setLatencySeconds] = useState(null);
  const [mediaTransport, setMediaTransport] = useState(null);
  const [needsTapToPlay, setNeedsTapToPlay] = useState(false);

  const clientOnline = client?.presence?.is_online === true;
  const shouldRun = Boolean(pageMediaActive && intersecting && clientOnline && mobileViewerActive);

  const updateLatency = useCallback(() => {
    if (wssActiveRef.current) return;
    const video = videoRef.current;
    let measured = hlsRef.current?.latency;
    if ((!Number.isFinite(measured) || measured < 0) && video?.seekable?.length) {
      try {
        measured = Math.max(0, Number(video.seekable.end(video.seekable.length - 1)) - Number(video.currentTime));
      } catch {
        measured = Number.NaN;
      }
    }
    setLatencySeconds(Number.isFinite(measured) && measured >= 0 ? measured : null);
  }, []);

  const handleFullscreen = useCallback(async () => {
    const video = videoRef.current;
    // Safari on iPhone only exposes video.webkitEnterFullscreen.
    if (typeof video?.webkitEnterFullscreen === "function") {
      video.webkitEnterFullscreen();
      return;
    }
    const element = previewRef.current;
    if (!element) return;
    try {
      if (document.fullscreenElement === element) {
        await document.exitFullscreen?.();
      } else if (element.requestFullscreen) {
        await element.requestFullscreen();
      } else if (element.webkitRequestFullscreen) {
        element.webkitRequestFullscreen();
      }
    } catch {
      setMessage("Browseren kunne ikke åbne preview i fuld skærm.");
    }
  }, []);

  const destroyPlayer = useCallback(() => {
    transportControllerRef.current?.dispose();
    transportControllerRef.current = null;
    wssActiveRef.current = false;
    hlsReserveRef.current?.dispose();
    hlsReserveRef.current = null;
    if (hlsRef.current) {
      try { hlsRef.current.destroy(); } catch {}
      hlsRef.current = null;
    }
    setLatencySeconds(null);
    setMediaTransport(null);
    setNeedsTapToPlay(false);
    const video = videoRef.current;
    if (video) {
      try {
        video.pause();
        video.removeAttribute("src");
        video.load();
      } catch {}
    }
  }, []);

  const stopLocalWork = useCallback((leave = true) => {
    if (heartbeatTimerRef.current) {
      window.clearInterval(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }
    if (healthTimerRef.current) {
      window.clearTimeout(healthTimerRef.current);
      healthTimerRef.current = null;
    }
    destroyPlayer();
    mediaCapabilityRef.current = "";
    if (leave && activeRef.current) {
      activeRef.current = false;
      void sendViewerLeave(client.id, viewerIdRef.current, "livestream_wall_inactive");
    }
  }, [client.id, destroyPlayer]);

  useEffect(() => {
    const node = rootRef.current;
    if (!node || typeof IntersectionObserver === "undefined") {
      // Do not activate every stream when viewport observation is unavailable.
      setIntersecting(false);
      return undefined;
    }
    const observer = new IntersectionObserver(
      (entries) => setIntersecting(entries.some((entry) => entry.isIntersecting && entry.intersectionRatio > 0)),
      { root: null, rootMargin: "240px 0px", threshold: 0.01 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!shouldRun) {
      stopLocalWork(true);
      setState(clientOnline ? "paused" : "offline");
      setMessage(!mobileViewerActive ? "Tryk Start for et tidsbegrænset mobil-preview." : clientOnline ? "Preview er sat på pause uden for visningen." : "Klienten er offline.");
      return undefined;
    }

    let cancelled = false;
    let mediaReady = false;
    let startupWarned = false;
    let generation = null;
    let observedGeneration = null;
    let manifestGenerationSeen = false;
    let healthInFlight = false;
    const startupWarning = window.setTimeout(() => {
      if (!cancelled && !mediaReady) {
        startupWarned = true;
        setMessage("Ingen livestream-video efter 15 sekunder – undersøger fortsat streamen automatisk …");
      }
    }, HEALTH_STARTUP_WARNING_MS);
    if (isTouchHandset) viewerIdRef.current = makeViewerId(client.id);
    const sessionViewerId = viewerIdRef.current;
    activeRef.current = true;
    setState("starting");
    setMessage("Starter preview …");

    const startPlayer = () => {
      if (cancelled || transportControllerRef.current) return;
      const video = videoRef.current;
      if (!video) return;
      const startHls = (callbacks = {}) => {
      let cancelled = false;
      let activeHls = null;
      let reserve = null;
      let httpTransport = null;
      manifestGenerationSeen = false;
      const observeManifestGeneration = createHlsGenerationObserver({
        onObserved: () => { if (!cancelled) manifestGenerationSeen = true; },
        onChange: () => queueMicrotask(() => {
          if (cancelled || generation) return;
          destroyPlayer();
          mediaReady = false;
          setState("starting");
          setMessage("Tilpasser livestream …");
          startPlayer();
        }),
      });
      let reportedPlayable = false;
      const reportPlayable = () => queueMicrotask(() => {
        if (cancelled || reportedPlayable || video.paused || video.readyState < 2) return;
        reportedPlayable = true;
        setMediaTransport(httpTransport);
        callbacks.onHttpTransport?.(httpTransport);
        callbacks.onPlayable?.();
      });
      video.addEventListener("playing", reportPlayable);
      const initialise = async () => {
      try {
        const { default: Hls } = await import("hls.js");
        if (cancelled) return;
        const hlsUrl = `${apiUrl}/hls/${client.id}/index.m3u8?_wall=${Date.now()}`;
        httpTransport = hlsHttpTransportLabel(hlsUrl, window.location.href);
        if (Hls.isSupported()) {
          const hls = new Hls({
            enableWorker: true,
            lowLatencyMode: false,
            liveSyncDurationCount: 3,
            initialLiveManifestSize: 3,
            maxLiveSyncPlaybackRate: 1,
            maxBufferLength: 12,
            maxMaxBufferLength: 32,
            backBufferLength: 8,
            xhrSetup: (xhr) => {
              const token = mediaCapabilityRef.current;
              if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
              xhr.addEventListener("load", () => {
                if (!cancelled) observeManifestGeneration(xhr);
              }, { once: true });
            },
          });
          activeHls = hls;
          hlsRef.current = hls;
          reserve = createHlsReserveController(video, {
            onReady: () => {
              if (cancelled) return;
              mediaReady = true;
              window.clearTimeout(startupWarning);
              setState("live");
              setMessage("");
            },
            onBuffering: (value) => {
              if (cancelled) return;
              setState(value ? "starting" : "live");
              setMessage(value ? "Genopbygger videobuffer …" : "");
            },
            onTapRequired: (value) => { if (!cancelled) setNeedsTapToPlay(value); },
          });
          hlsReserveRef.current = reserve;
          reserve.bindLiveVisibility(hls, document, Hls.Events.LEVEL_UPDATED, {
            onFailure: () => {
              if (cancelled) return;
              if (generation) { hls.loadSource(hlsUrl); return; }
              // Rebuild only the local HLS player; preserve viewer heartbeat,
              // capability and backend generation.
              destroyPlayer();
              mediaReady = false;
              setState("starting");
              setMessage("Genindlæser HLS-afspiller …");
              startPlayer();
            },
          });
          hls.on(Hls.Events.BUFFER_APPENDED, () => reserve.pump());
          hls.on(Hls.Events.MEDIA_ATTACHED, () => hls.loadSource(hlsUrl));
          hls.on(Hls.Events.MANIFEST_PARSED, () => reserve.pump());
          hls.on(Hls.Events.LEVEL_LOADED, (_event, data) => {
            reserve.setTargetDuration(data?.details?.targetduration);
            reserve.catchUp(hls.liveSyncPosition);
          });
          hls.attachMedia(video);
          hls.on(Hls.Events.FRAG_CHANGED, () => {
            if (!cancelled) updateLatency();
          });
          hls.on(Hls.Events.LEVEL_UPDATED, () => {
            if (!cancelled) updateLatency();
          });
          hls.on(Hls.Events.ERROR, (_event, data) => {
            if (!data?.fatal || cancelled) return;
            if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
              try { reserve.rearm(); hls.recoverMediaError(); } catch {}
              return;
            }
            setState("starting");
            setMessage(startupWarned
              ? "Streamen er endnu ikke klar – kontroller skærmoptagelsen på klienten."
              : "Venter på friske segmenter …");
          });
          return;
        }

        if (video.canPlayType("application/vnd.apple.mpegurl")) {
          video.crossOrigin = "use-credentials";
          video.src = hlsUrl;
          video.muted = true;
          video.autoplay = true;
          video.playsInline = true;
          mediaReady = true;
          window.clearTimeout(startupWarning);
          setState("live");
          setMessage("");
          video.play().then(() => { if (!cancelled) setNeedsTapToPlay(false); }).catch(() => { if (!cancelled) setNeedsTapToPlay(true); });
          return;
        }

        setState("error");
        setMessage("Browseren understøtter ikke HLS-preview.");
      } catch {
        if (!cancelled) {
          setState("error");
          setMessage("Kunne ikke indlæse HLS-preview.");
        }
      }
      };
      void initialise();
      return { dispose() {
        if (cancelled) return;
        cancelled = true;
        video.removeEventListener("playing", reportPlayable);
        reserve?.dispose();
        if (hlsReserveRef.current === reserve) hlsReserveRef.current = null;
        if (activeHls) {
          try { activeHls.destroy(); } catch {}
          if (hlsRef.current === activeHls) hlsRef.current = null;
        }
        try { video.pause(); video.removeAttribute("src"); video.load(); } catch {}
        setLatencySeconds(null);
        setMediaTransport(null);
      } };
      };

      transportControllerRef.current = generation && !isTouchHandset
        ? createPilotTransport(video, {
            apiUrl, clientId: client.id, generation, viewerId: sessionViewerId,
            authenticatedFetch, authHeaders, getAuthSessionSignal, startHls,
            onTransport: label => {
              wssActiveRef.current = label === "WSS";
              setMediaTransport(label);
              if (label === null) {
                mediaReady = false;
                setLatencySeconds(null);
                setState("starting");
              }
            },
            onWssPlayable: () => {
              mediaReady = true;
              window.clearTimeout(startupWarning);
              setState("live");
              setMessage("");
              setNeedsTapToPlay(false);
              setLatencySeconds(null);
            },
            onFailure: () => { setState("error"); setMessage("Kunne ikke genetablere preview."); },
          })
        : startHls();
    };

    const checkHealthUntilReady = async () => {
      healthTimerRef.current = null;
      if (cancelled || healthInFlight || transportControllerRef.current || !mediaCapabilityRef.current) return;
      healthInFlight = true;
      try {
        const resp = await fetch(`${apiUrl}/api/hls-cap/${client.id}/health`, {
          credentials: "omit",
          headers: { Authorization: `Bearer ${mediaCapabilityRef.current}` },
          signal: AbortSignal.any([getAuthSessionSignal(), AbortSignal.timeout(6000)]),
        });
        if (resp.ok) {
          const health = await resp.json();
          if (health?.has_segments && !health?.is_stale) {
            await startPlayer();
            return;
          }
        }
      } catch {} finally { healthInFlight = false; }
      if (!cancelled && !transportControllerRef.current) {
        healthTimerRef.current = window.setTimeout(checkHealthUntilReady, HEALTH_STARTUP_POLL_MS);
      }
    };

    const heartbeat = async () => {
      if (cancelled) return;
      try {
        const resp = await authenticatedFetch(`${apiUrl}/api/livestream-v2/hls/${encodeURIComponent(client.id)}/viewer-heartbeat`, {
          method: "POST",
          credentials: "include",
          headers: {
            ...authHeaders(),
            "Content-Type": "application/json",
            accept: "application/json",
          },
          body: JSON.stringify({
            viewer_id: sessionViewerId,
            source: "superadmin_livestream_wall",
          }),
          signal: AbortSignal.timeout(8000),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const payload = await resp.json();
        if (cancelled) {
          // An in-flight heartbeat might have arrived after Stop/timeout.
          void sendViewerLeave(client.id, sessionViewerId, "livestream_wall_late_heartbeat");
          return;
        }
        if (payload?.media_capability) {
          mediaCapabilityRef.current = String(payload.media_capability);
        }
        if (Number.isFinite(Number(payload?.active_viewers))) {
          setActiveViewers(Number(payload.active_viewers));
        }
        const nextGeneration = pilotGenerationFromHeartbeat(payload);
        const nextObservedGeneration = generationFromHeartbeat(payload);
        const generationChanged = generation !== nextGeneration ||
          (!manifestGenerationSeen && observedGeneration !== nextObservedGeneration);
        observedGeneration = nextObservedGeneration;
        if (generationChanged) {
          generation = nextGeneration;
          destroyPlayer();
          mediaReady = false;
          setState("starting");
        }
        if (!transportControllerRef.current && !healthTimerRef.current && !healthInFlight) {
          void checkHealthUntilReady();
        }
      } catch (error) {
        if (!cancelled) {
          if (isRequestTimeout(error)) {
            setState((current) => (current === "live" ? current : "starting"));
            setMessage("Livestream-kontakt er forsinket — prøver igen automatisk …");
          } else {
            setState("error");
            setMessage(error?.message || "Kunne ikke registrere livestream-viewer.");
          }
        }
      }
    };

    void heartbeat();
    heartbeatTimerRef.current = window.setInterval(heartbeat, VIEWER_HEARTBEAT_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(startupWarning);
      stopLocalWork(true);
    };
  }, [client.id, clientOnline, shouldRun, mobileViewerActive, isTouchHandset, stopLocalWork, updateLatency, destroyPlayer]);

  useEffect(() => () => stopLocalWork(true), [stopLocalWork]);

  const latencyStatus = livestreamLatencyStatus(state === "live" && shouldRun ? latencySeconds : null);
  const tone = state === "live" ? latencyStatus.severity : state === "error" ? "error" : state === "offline" ? "neutral" : "info";
  const statusChipSx = tone === "elevated"
    ? compactDarkChipSx("neutral", { color: "#fb923c", bgcolor: "rgba(249,115,22,0.14)", borderColor: "rgba(251,146,60,0.45)" })
    : compactDarkChipSx(tone);

  return (
    <Paper
      ref={rootRef}
      elevation={0}
      sx={{
        overflow: "hidden",
        borderRadius: 2,
        background: "rgba(15,23,42,0.78)",
        border: "1px solid rgba(148,163,184,0.16)",
      }}
    >
      {isTouchHandset && (
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="center" sx={{ px: 1.4, pt: 1.4 }}>
          <TextField
            select size="small" label="Varighed" value={mobileSession.durationSeconds}
            onChange={(event) => mobileSession.selectDuration(event.target.value)}
            disabled={mobileSession.isActive}
            sx={{ minWidth: 114 }}
          >
            {MOBILE_LIVESTREAM_DURATIONS.map((seconds) => (
              <MenuItem key={seconds} value={seconds}>{seconds} sek.</MenuItem>
            ))}
          </TextField>
          <Button
            variant="contained" size="medium" sx={{ minHeight: 44, textTransform: "none" }}
            disabled={!clientOnline && !mobileSession.isActive}
            onClick={mobileSession.isActive ? () => mobileSession.stop() : mobileSession.start}
            aria-label={mobileSession.isActive ? `Stop preview for ${client.name}` : `Start preview for ${client.name}`}
          >
            {mobileSession.isActive ? "Stop" : "Start"}
          </Button>
          <Typography variant="caption" color="text.secondary" aria-live="polite">
            {mobileSession.isActive
              ? `Stopper om ${mobileSession.remainingSeconds} sek.`
              : mobileSession.expired ? "Tiden er udløbet" : "Afspilning er stoppet"}
          </Typography>
        </Stack>
      )}
      <Box
        ref={previewRef}
        sx={{
          position: "relative",
          aspectRatio: "16 / 9",
          background: "#020617",
          "@media (hover: none) and (pointer: coarse) and (max-width: 1023.95px)": {
            width: "100%", minWidth: 0,
            maxHeight: "min(55dvh, 480px)",
          },
          "@media (orientation: landscape) and (hover: none) and (pointer: coarse) and (max-width: 1023.95px)": {
            maxHeight: "min(72dvh, 480px)",
          },
          "&:fullscreen": { width: "100vw", height: "100vh", aspectRatio: "auto" },
        }}
      >
        <video
          ref={videoRef}
          muted
          playsInline
          onPlaying={() => setNeedsTapToPlay(false)}
          onTimeUpdate={updateLatency}
          style={{ width: "100%", height: "100%", display: "block", objectFit: "contain" }}
        />
        {needsTapToPlay && shouldRun && (
          <Button
            variant="contained"
            onClick={() => {
              const video = videoRef.current;
              if (hlsReserveRef.current) hlsReserveRef.current.playFromGesture();
              else if (video) void video.play().then(() => setNeedsTapToPlay(false)).catch(() => {});
            }}
            sx={{
              position: "absolute", top: "50%", left: "50%", zIndex: 5,
              transform: "translate(-50%, -50%)", minHeight: 44,
              background: "rgba(15,23,42,0.94)", color: "white",
            }}
          >
            Afspil livestream
          </Button>
        )}
        <Tooltip title="Vis i fuld skærm">
          <IconButton
            aria-label={`Vis ${client.name || "livestream"} i fuld skærm`}
            onClick={() => void handleFullscreen()}
            size="small"
            sx={{
              position: "absolute",
              top: 8,
              right: 8,
              zIndex: 3,
              color: "white",
              background: "rgba(2,6,23,0.62)",
              "&:hover": { background: "rgba(2,6,23,0.82)" },
            }}
          >
            <FullscreenIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        {state !== "live" && (
          <Stack
            spacing={1}
            sx={{
              position: "absolute",
              inset: 0,
              alignItems: "center",
              justifyContent: "center",
              p: 2,
              textAlign: "center",
              background: "rgba(2,6,23,0.58)",
            }}
          >
            {state === "starting" && <CircularProgress size={28} />}
            <Typography variant="body2" sx={{ color: "rgba(226,232,240,0.9)" }}>
              {message || "Venter på livestream …"}
            </Typography>
          </Stack>
        )}
      </Box>

      <Stack spacing={1} sx={{ p: 1.4 }}>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center", justifyContent: "space-between" }}>
          <Box sx={{ minWidth: 0 }}>
            <Typography sx={{ fontWeight: 900 }} noWrap>{client.name}</Typography>
            <Typography variant="caption" color="text.secondary" noWrap>
              {client.locality || "Ingen lokalitet"}
            </Typography>
          </Box>
          <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap" justifyContent="flex-end">
            {mediaTransport && shouldRun && <Chip size="small" label={mediaTransport === "WSS" ? "WSS" : `HLS · ${mediaTransport}`} sx={compactDarkChipSx("neutral")} />}
            <Chip
              size="small"
              label={state === "live" ? latencyStatus.text : state === "offline" ? "Offline" : state === "error" ? "Fejl" : state === "paused" ? "På pause" : "Klargør"}
              sx={statusChipSx}
            />
          </Stack>
        </Stack>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center", justifyContent: "space-between", minWidth: 0, flexWrap: "wrap" }}>
          <Typography variant="caption" color="text.secondary" sx={{ minWidth: 0, overflowWrap: "anywhere" }}>
            {[
              activeViewers == null ? "" : `${activeViewers} aktiv${activeViewers === 1 ? "" : "e"} seer${activeViewers === 1 ? "" : "e"}`,
            ].filter(Boolean).join(" · ")}
          </Typography>
          <Button
            component={Link}
            to={`/clients/${client.id}`}
            size="small"
            endIcon={<OpenInNewIcon fontSize="small" />}
            sx={{ textTransform: "none" }}
          >
            Control Room
          </Button>
        </Stack>
      </Stack>
    </Paper>
  );
}

export default function LivestreamOverview() {
  const [clients, setClients] = useState([]);
  const [organizations, setOrganizations] = useState([]);
  const [search, setSearch] = useState("");
  const [sortOrder, setSortOrder] = useState("online");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [pageMediaActive, setPageMediaActive] = useState(document.visibilityState !== "hidden");
  const hiddenTimerRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const data = await getControlRoomClients();
      setClients(Array.isArray(data) ? data.filter((client) => String(client.status || "").toLowerCase() === "approved") : []);
      setError("");
    } catch (err) {
      setError(err?.message || "Kunne ikke hente klienter.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // One scoped organization read per page mount, never per keystroke/poll.
    // Access restrictions are enforced by the existing organizations endpoint.
    let active = true;
    getOrganizations().then((items) => {
      if (active) setOrganizations(Array.isArray(items) ? items : []);
    }).catch(() => {
      if (active) setError("Organisationsnavne kunne ikke indlæses. Prøv at opdatere siden.");
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "hidden") void load();
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    const applyVisibility = () => {
      if (document.visibilityState !== "hidden") {
        if (hiddenTimerRef.current) {
          window.clearTimeout(hiddenTimerRef.current);
          hiddenTimerRef.current = null;
        }
        setPageMediaActive(true);
        return;
      }
      if (!hiddenTimerRef.current) {
        hiddenTimerRef.current = window.setTimeout(() => {
          hiddenTimerRef.current = null;
          if (document.visibilityState === "hidden") setPageMediaActive(false);
        }, PAGE_HIDDEN_WARM_GRACE_MS);
      }
    };
    document.addEventListener("visibilitychange", applyVisibility);
    return () => {
      document.removeEventListener("visibilitychange", applyVisibility);
      if (hiddenTimerRef.current) window.clearTimeout(hiddenTimerRef.current);
    };
  }, []);

  const organizationNameMap = useMemo(() => organizationNamesById(organizations), [organizations]);
  const sortedClients = useMemo(
    () => sortLivestreamClients(
      clients.filter((client) => clientMatchesSearch(client, search, organizationNameMap)),
      sortOrder,
      organizationNameMap,
    ),
    [clients, search, sortOrder, organizationNameMap],
  );

  return (
    <Stack spacing={2}>
      <Paper
        elevation={0}
        sx={{
          p: 2,
          borderRadius: 2,
          background: "rgba(15,23,42,0.72)",
          border: "1px solid rgba(148,163,184,0.16)",
        }}
      >
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} sx={{ justifyContent: "space-between", alignItems: { md: "center" } }}>
          <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
            <GridViewIcon />
            <Box>
              <Typography variant="h6" sx={{ fontWeight: 950 }}>Livestream oversigt</Typography>
              <Typography variant="body2" color="text.secondary">
                Synlige previews aktiveres efter behov. Flere brugere kan se samme klient samtidig uden ekstra klient-producer.
              </Typography>
            </Box>
          </Stack>
          <AdminRefreshButton onClick={() => void load()} loading={loading} ariaLabel="Opdater livestreams" />
        </Stack>
      </Paper>

      <Paper elevation={0} sx={{ p: 1.5, borderRadius: 2, background: "rgba(15,23,42,0.72)", border: "1px solid rgba(148,163,184,0.16)" }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
          <TextField
            type="search"
            size="small"
            fullWidth
            label="Søg i livestream"
            placeholder="Organisation, klient, lokation eller klient-ID"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            slotProps={{ htmlInput: { maxLength: 160 } }}
          />
          <TextField
            select
            size="small"
            label="Sortér efter"
            value={sortOrder}
            onChange={(event) => setSortOrder(event.target.value)}
            sx={{ minWidth: { xs: "100%", md: 250 } }}
          >
            <MenuItem value="online">Online først</MenuItem>
            <MenuItem value="name">Klientnavn A–Å</MenuItem>
            <MenuItem value="name_desc">Klientnavn Å–A</MenuItem>
            <MenuItem value="organization">Organisation A–Å</MenuItem>
            <MenuItem value="location">Lokation A–Å</MenuItem>
            <MenuItem value="manual">Rækkefølge fra Clientlist</MenuItem>
          </TextField>
        </Stack>
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
          {sortedClients.length} af {clients.length} godkendte klienter · Søgning og sortering foregår lokalt.
        </Typography>
      </Paper>

      {error && <Alert severity="error">{error}</Alert>}
      {loading && sortedClients.length === 0 ? (
        <Stack sx={{ minHeight: 240, alignItems: "center", justifyContent: "center" }}><CircularProgress /></Stack>
      ) : sortedClients.length === 0 ? (
        <Alert severity="info">Ingen godkendte klienter matcher søgningen.</Alert>
      ) : (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))", xl: "repeat(3, minmax(0, 1fr))" },
            // Do not change desktop. Landscape phones often cross sm.
            "@media (hover: none) and (pointer: coarse) and (max-width: 1023.95px)": {
              gridTemplateColumns: "minmax(0, 1fr)",
            },
            gap: 1.5,
          }}
        >
          {sortedClients.map((client) => (
            <LivestreamTile key={client.id} client={client} pageMediaActive={pageMediaActive} />
          ))}
        </Box>
      )}
    </Stack>
  );
}
