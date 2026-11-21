"""Isolated Remote Desktop network agent with dedicated capture, input and file channels."""
from __future__ import annotations

import asyncio
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import ssl
import time
from typing import Any, Protocol
import uuid

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from .atomic import atomic_write_json
from .config import DomainCredential
from .constants import Domain
from .logging_utils import configure_logging
from .remote_desktop_net import DomainTransport, TransportError, backoff_seconds
from .remote_desktop_files import FileArea
from .remote_desktop_input_queue import InputLaneQueue
from .remote_desktop_media_pressure import MediaPressure, socket_send_queue_bytes
from .status import report_status
from .unix_rpc import RpcError, call

CAPTURE_SOCKET = os.getenv("CLIENTFLOW_RD_CAPTURE_SOCKET", "/run/clientflow/remote-desktop-capture.sock")
INPUT_SOCKET = os.getenv("CLIENTFLOW_RD_INPUT_SOCKET", "/run/clientflow/remote-desktop-input.sock")
FILE_ROOT = Path(os.getenv("CLIENTFLOW_RD_FILE_ROOT", "/home/clientflow-kiosk"))
FILE_STAGING_ROOT = Path(
    os.getenv("CLIENTFLOW_RD_STAGING_ROOT", "/var/lib/clientflow/remote-desktop/uploads")
)
FPS = min(12.0, max(0.5, float(os.getenv("CLIENTFLOW_RD_FPS", "6"))))


TELEMETRY_PATH = Path(os.getenv("CLIENTFLOW_RD_MEDIA_TELEMETRY_PATH", "/var/lib/clientflow/remote-desktop/media-telemetry.json"))


class RemoteDesktopMediaTransport(Protocol):
    """Media-plane abstraction used for measurable JPEG/WebRTC comparison."""
    name: str

    async def capture(self, options: dict[str, Any]) -> tuple[dict[str, Any], float]: ...


class JpegRpcMediaTransport:
    name = "jpeg_rpc"

    async def capture(self, options: dict[str, Any]) -> tuple[dict[str, Any], float]:
        started = time.monotonic()
        result = await asyncio.to_thread(
            call,
            CAPTURE_SOCKET,
            {
                "action": "capture",
                "native": bool(options.get("native", False)),
                "width": int(options["width"]),
                "height": int(options["height"]),
                "screen_width": int(options["screen_width"]),
                "screen_height": int(options["screen_height"]),
                "quality": int(options["quality"]),
            },
            timeout=15,
        )
        return result, (time.monotonic() - started) * 1000.0


class _HttpRelaySocket:
    def __init__(self, transport: DomainTransport, client_id: int, channel: str, relay_id: str) -> None:
        self.transport = transport
        self.client_id = client_id
        self.channel = channel
        self.relay_id = relay_id

    async def send(self, raw: str) -> None:
        await asyncio.to_thread(
            self.transport.json_request,
            "POST",
            f"/api/remote-desktop-agent/clients/{self.client_id}/{self.channel}/http/{self.relay_id}/send",
            json_body={"payload": json.loads(raw)},
            timeout=20,
        )


class RemoteDesktopAgent:
    def __init__(self) -> None:
        self.logger = configure_logging("clientflow.remote-desktop")
        self.credential = DomainCredential.load(Domain.REMOTE_DESKTOP)
        self.transport = DomainTransport(self.credential)
        self.file_area = FileArea(FILE_ROOT, FILE_STAGING_ROOT)
        self.stream_tasks: dict[str, asyncio.Task[None]] = {}
        self.stream_options: dict[str, dict[str, Any]] = {}
        self.last_frame_digest: dict[str, str] = {}
        self.last_frame_sent_at: dict[str, float] = {}
        self.control_ws: Any = None
        self.file_ws: Any = None
        self.input_ws: Any = None
        self.input_send_lock = asyncio.Lock()
        self.input_sessions: set[str] = set()
        # Input socket and its DB rechecks exist only while a browser session
        # is active. Control/files remain fully backwards compatible.
        self.input_demand = asyncio.Event()
        # Serialize cross-lane input during reconnect and dedupe replayed IDs.
        self.input_rpc_lock = asyncio.Lock()
        self.completed_input_ids: set[str] = set()
        self.recent_input_ids: deque[str] = deque()
        self.control_send_lock = asyncio.Lock()
        self.file_send_lock = asyncio.Lock()
        self.control_sessions: set[str] = set()
        self.file_sessions: set[str] = set()
        self.media_transport: RemoteDesktopMediaTransport = JpegRpcMediaTransport()
        self.media_telemetry: dict[str, dict[str, Any]] = {}
        self.pending_input_at: dict[str, float] = {}
        self._last_telemetry_write = 0.0
        self.media_pressure: dict[str, MediaPressure] = {}

    def ssl_context(self) -> ssl.SSLContext | None:
        if not self.transport.websocket_url("/").startswith("wss:"):
            return None
        context = ssl.create_default_context(cafile=self.credential.tls_ca_file)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        return context

    async def _send_control(self, payload: dict[str, Any]) -> None:
        if self.control_ws is None:
            return
        async with self.control_send_lock:
            await self.control_ws.send(json.dumps(payload, separators=(",", ":")))

    async def _send_input(self, payload: dict[str, Any]) -> None:
        if self.input_ws is None:
            return
        async with self.input_send_lock:
            await self.input_ws.send(json.dumps(payload, separators=(",", ":")))

    async def _send_file(self, payload: dict[str, Any]) -> None:
        if self.file_ws is None:
            return
        async with self.file_send_lock:
            await self.file_ws.send(json.dumps(payload, separators=(",", ":")))

    async def _event(self, session_id: str, event_type: str, details: dict[str, Any] | None = None) -> None:
        client_id = self.credential.client_id
        await asyncio.to_thread(
            self.transport.json_request,
            "POST",
            f"/api/remote-desktop-agent/clients/{client_id}/sessions/{session_id}/events",
            json_body={"event_type": event_type, "details": details or {}},
        )


    @staticmethod
    def _session_id(message: dict[str, Any]) -> str:
        session_id = str(message.get("session_id") or "")
        try:
            uuid.UUID(session_id)
        except ValueError as exc:
            raise ValueError("Remote Desktop-session-id er ugyldigt") from exc
        return session_id

    def _new_media_row(self) -> dict[str, Any]:
        return {
            "transport": self.media_transport.name,
            "captured_frames": 0,
            "relayed_frames": 0,
            "unchanged_frames": 0,
            "relayed_bytes": 0,
            "capture_ms_total": 0.0,
            "capture_ms_max": 0.0,
            "relay_send_samples": 0,
            "relay_send_ms_total": 0.0,
            "relay_send_ms_max": 0.0,
            "input_to_frame_samples": 0,
            "input_to_frame_ms_total": 0.0,
            "input_to_frame_ms_max": 0.0,
        }

    def _record_media_telemetry(
        self, session_id: str, *, capture_ms: float, frame_bytes: int, relayed: bool, unchanged: bool,
        relay_send_ms: float | None = None,
    ) -> None:
        row = self.media_telemetry.setdefault(session_id, self._new_media_row())
        row["captured_frames"] += 1
        row["relayed_frames"] += int(relayed)
        row["unchanged_frames"] += int(unchanged)
        row["relayed_bytes"] += int(frame_bytes if relayed else 0)
        row["capture_ms_total"] += float(capture_ms)
        row["capture_ms_max"] = max(float(row["capture_ms_max"]), float(capture_ms))
        row["updated_at"] = time.time()
        captured = max(1, int(row["captured_frames"]))
        row["unchanged_ratio"] = round(float(row["unchanged_frames"]) / captured, 4)
        row["capture_ms_avg"] = round(float(row["capture_ms_total"]) / captured, 3)
        if relay_send_ms is not None and relayed:
            row["relay_send_samples"] += 1
            row["relay_send_ms_total"] += float(relay_send_ms)
            row["relay_send_ms_max"] = max(float(row["relay_send_ms_max"]), float(relay_send_ms))
            row["relay_send_ms_last"] = round(float(relay_send_ms), 3)
            row["relay_send_ms_avg"] = round(float(row["relay_send_ms_total"]) / row["relay_send_samples"], 3)
        if relayed:
            input_started = self.pending_input_at.pop(session_id, None)
            if input_started is not None:
                input_to_frame_ms = max(0.0, (time.monotonic() - input_started) * 1000.0)
                row["input_to_frame_samples"] += 1
                row["input_to_frame_ms_total"] += input_to_frame_ms
                row["input_to_frame_ms_max"] = max(
                    float(row["input_to_frame_ms_max"]), input_to_frame_ms
                )
                samples = max(1, int(row["input_to_frame_samples"]))
                row["input_to_frame_ms_last"] = round(input_to_frame_ms, 3)
                row["input_to_frame_ms_avg"] = round(
                    float(row["input_to_frame_ms_total"]) / samples, 3
                )
        self._flush_media_telemetry()

    def _flush_media_telemetry(self) -> None:
        now = time.monotonic()
        if now - self._last_telemetry_write >= 5.0:
            self._last_telemetry_write = now
            try:
                atomic_write_json(TELEMETRY_PATH, {
                    "schema_version": 1,
                    "media_transport": self.media_transport.name,
                    "sessions": self.media_telemetry,
                    "updated_at": time.time(),
                }, mode=0o600)
            except OSError:
                self.logger.warning("rd_media_telemetry_write_failed", exc_info=True)

    async def _capture(self, session_id: str, options: dict[str, Any] | None = None, *, force: bool = False) -> bool:
        selected = options or self.stream_options.get(session_id, {})
        pressure = self.media_pressure.setdefault(session_id, MediaPressure())
        quality = pressure.jpeg_quality(int(selected.get("quality", 85)), now=time.monotonic())
        if isinstance(self.control_ws, _HttpRelaySocket):
            quality = min(quality, 40)
        native = bool(selected.get("native", False))
        width = min(7680, max(320, int(selected.get("width", 1280))))
        height = min(4320, max(200, int(selected.get("height", 720))))
        screen_width = min(7680, max(width, int(selected.get("screen_width", width))))
        screen_height = min(4320, max(height, int(selected.get("screen_height", height))))
        capture_options = {
            "native": native,
            "width": width,
            "height": height,
            "screen_width": screen_width,
            "screen_height": screen_height,
            "quality": min(95, max(35, quality)),
        }
        result, capture_ms = await self.media_transport.capture(capture_options)
        frame_data = str(result["data"])
        digest = hashlib.sha256(frame_data.encode("ascii", errors="ignore")).hexdigest()
        now = time.monotonic()
        unchanged = digest == self.last_frame_digest.get(session_id)
        # Static desktops are the normal RD idle case. Keep a sparse keyframe
        # every five seconds for freshness, but don't relay identical JPEG bytes.
        frame_bytes = max(0, len(frame_data) * 3 // 4)
        telemetry = self.media_telemetry.setdefault(session_id, self._new_media_row())
        telemetry["jpeg_bytes_last"] = frame_bytes
        telemetry["jpeg_quality_last"] = capture_options["quality"]
        if not force and unchanged and now - self.last_frame_sent_at.get(session_id, 0.0) < 5.0:
            self._record_media_telemetry(session_id, capture_ms=capture_ms, frame_bytes=frame_bytes, relayed=False, unchanged=True)
            return False
        self.last_frame_digest[session_id] = digest
        self.last_frame_sent_at[session_id] = now
        relay_started = time.monotonic()
        await self._send_control(
            {
                "type": "frame",
                "session_id": session_id,
                "native": native,
                "data": frame_data,
                "encoding": result["encoding"],
                "mime_type": result["mime_type"],
                "captured_at": time.time(),
                "width": int(result.get("width") or width),
                "height": int(result.get("height") or height),
                "screen_width": int(result.get("screen_width") or result.get("width") or width),
                "screen_height": int(result.get("screen_height") or result.get("height") or height),
                "fps": float(selected.get("fps", FPS)),
                "deduplicated": True,
            }
        )
        send_elapsed_ms = (time.monotonic() - relay_started) * 1000.0
        pressure.observe_send(send_elapsed_ms, now=time.monotonic())
        self._record_media_telemetry(
            session_id, capture_ms=capture_ms, frame_bytes=frame_bytes,
            relayed=True, unchanged=unchanged,
            relay_send_ms=send_elapsed_ms,
        )
        return True

    async def _stream_loop(self, session_id: str) -> None:
        try:
            await self._event(session_id, "capture_started")
            options = self.stream_options.get(session_id, {})
            await self._send_control({
                "type": "stream_started",
                "session_id": session_id,
                "width": int(options.get("width", 1280)),
                "height": int(options.get("height", 720)),
                "screen_width": int(options.get("screen_width", options.get("width", 1280))),
                "screen_height": int(options.get("screen_height", options.get("height", 720))),
                "fps": float(options.get("fps", FPS)),
            })
            while True:
                # Protect the actual TCP socket queue: backend latest-only
                # cannot remove JPEG bytes already buffered on this client.
                pressure = self.media_pressure.setdefault(session_id, MediaPressure())
                pending = socket_send_queue_bytes(self.control_ws)
                if pending is not None:
                    row = self.media_telemetry.setdefault(session_id, self._new_media_row())
                    row["control_tcp_sendq_bytes_last"] = pending
                    row["control_tcp_sendq_bytes_max"] = max(
                        int(row.get("control_tcp_sendq_bytes_max") or 0), pending
                    )
                if pressure.should_defer(pending, now=time.monotonic()):
                    row = self.media_telemetry.setdefault(session_id, self._new_media_row())
                    row["frames_deferred_for_control_sendq"] = pressure.deferred_frames
                    self._flush_media_telemetry()
                    await asyncio.sleep(0.06)
                    continue
                started = time.monotonic()
                await self._capture(session_id, options)
                fps = min(12.0, max(0.2, float(options.get("fps", FPS))))
                if isinstance(self.control_ws, _HttpRelaySocket):
                    fps = min(fps, 3.0)
                await asyncio.sleep(max(0.0, 1.0 / fps - (time.monotonic() - started)))
        except asyncio.CancelledError:
            raise
        except (WebSocketException, OSError, TransportError) as exc:
            # A broken websocket is not evidence of a Mutter/PipeWire fault.
            self.logger.warning("transport_disconnected", extra={"session_id": session_id, "event": type(exc).__name__})
        except Exception as exc:
            self.logger.exception("capture_stream_failed", extra={"session_id": session_id})
            try:
                await self._send_control({"type": "error", "session_id": session_id, "error": str(exc)[:500]})
            except (WebSocketException, OSError, TransportError):
                self.logger.info("capture_error_report_transport_closed", extra={"session_id": session_id})
            try:
                await self._event(session_id, "error", {"error": str(exc)[:500]})
            except Exception:
                self.logger.exception("capture_stream_error_audit_failed", extra={"session_id": session_id})
        finally:
            try:
                await self._send_control({"type": "stream_stopped", "session_id": session_id})
            except (WebSocketException, OSError, TransportError):
                # Reconnection and the session owner perform the remote cleanup.
                pass
            try:
                await self._event(session_id, "capture_stopped")
            except Exception:
                pass
            self.stream_tasks.pop(session_id, None)
            await self._stop_capture_if_idle()

    async def _start_stream(self, session_id: str, message: dict[str, Any]) -> None:
        updated = {
            "native": bool(message.get("native", False)),
            "width": int(message.get("width") or 1280),
            "height": int(message.get("height") or 720),
            "screen_width": int(message.get("screen_width") or message.get("width") or 1280),
            "screen_height": int(message.get("screen_height") or message.get("height") or 720),
            "fps": min(12.0, max(0.2, float(message.get("fps") or FPS))),
            "quality": min(95, max(35, int(message.get("quality") or 85))),
        }
        existing_options = self.stream_options.get(session_id)
        if existing_options is None:
            self.stream_options[session_id] = updated
        else:
            existing_options.clear()
            existing_options.update(updated)
        existing = self.stream_tasks.get(session_id)
        if existing and not existing.done():
            await self._send_control({
                "type": "stream_mode_updated",
                "session_id": session_id,
                "fps": updated["fps"],
                "quality": updated["quality"],
            })
            return
        self.stream_tasks[session_id] = asyncio.create_task(self._stream_loop(session_id))

    async def _capture_lifecycle_call(self, action: str) -> None:
        try:
            await asyncio.to_thread(call, CAPTURE_SOCKET, {"action": action}, timeout=5)
        except RpcError as exc:
            self.logger.warning(
                "capture_lifecycle_failed",
                extra={"event": action, "error": str(exc)[:300]},
            )

    async def _stop_capture_if_idle(self) -> None:
        if any(not task.done() for task in self.stream_tasks.values()):
            return
        await self._capture_lifecycle_call("stop_capture")

    async def _close_mutter_if_idle(self) -> None:
        if self.control_sessions:
            return
        if any(not task.done() for task in self.stream_tasks.values()):
            return
        await self._capture_lifecycle_call("close_worker")

    async def _stop_stream(self, session_id: str) -> None:
        self.stream_options.pop(session_id, None)
        self.media_pressure.pop(session_id, None)
        self.last_frame_digest.pop(session_id, None)
        self.last_frame_sent_at.pop(session_id, None)
        self.pending_input_at.pop(session_id, None)
        task = self.stream_tasks.pop(session_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self._stop_capture_if_idle()

    async def _handle_control(self, message: dict[str, Any]) -> None:
        message_type = str(message.get("type") or "")
        session_id = self._session_id(message)
        if message_type == "session_open":
            self.control_sessions.add(session_id)
            self.input_demand.set()
            await self._send_control({"type": "agent_ready", "session_id": session_id})
            return
        if session_id not in self.control_sessions:
            raise ValueError("Remote Desktop-controlsessionen er ikke åbnet")
        if message_type == "session_close":
            await self._stop_stream(session_id)
            self.control_sessions.discard(session_id)
            self.input_demand.set()
            await self._release_session_input(session_id)
            await self._close_mutter_if_idle()
            await self._send_control({"type": "session_closed", "session_id": session_id})
        elif message_type == "start_stream":
            await self._start_stream(session_id, message)
        elif message_type == "stop_stream":
            await self._stop_stream(session_id)
        elif message_type == "request_frame":
            await self._capture(session_id, message, force=True)
        elif message_type in {"mouse", "key"}:
            self.pending_input_at[session_id] = time.monotonic()
            fields = {"event", "x", "y", "button", "delta"} if message_type == "mouse" else {"event", "key"}
            request = {"action": message_type, "session_id": session_id,
                       **{key: value for key, value in message.items() if key in fields}}
            if message.get("input_id"):
                request["input_id"] = str(message["input_id"])
            try:
                result = await self._input_rpc(INPUT_SOCKET, request)
                await self._send_control({"type": "input_result", "session_id": session_id, "ok": True, "result": result})
            except RpcError as exc:
                await self._send_control({"type": "input_result", "session_id": session_id, "ok": False, "error": str(exc)[:500]})
        elif message_type == "text":
            self.pending_input_at[session_id] = time.monotonic()
            request = {"action": "text", "text": str(message.get("text") or "")[:1000]}
            if message.get("input_id"):
                request["input_id"] = str(message["input_id"])
            try:
                result = await self._input_rpc(CAPTURE_SOCKET, request)
                await self._send_control({"type": "input_result", "session_id": session_id, "ok": True, "result": result})
            except RpcError as exc:
                await self._send_control({"type": "input_result", "session_id": session_id, "ok": False, "error": str(exc)[:500]})
        elif message_type == "shout":
            request = {
                "action": "shout",
                "text": str(message.get("text") or "").strip()[:120],
                "duration": max(3, min(30, int(message.get("duration") or 8))),
            }
            try:
                await asyncio.to_thread(call, CAPTURE_SOCKET, request, timeout=5)
                await self._send_control({
                    "type": "shout_result", "session_id": session_id, "ok": True,
                    "message": "Shout out vist på klientskærmen",
                })
            except (RpcError, ValueError) as exc:
                await self._send_control({
                    "type": "shout_result", "session_id": session_id, "ok": False,
                    "message": str(exc)[:500],
                })
        else:
            raise ValueError("Ukendt Remote Desktop-controlmeddelelse")

    async def _handle_input(self, message: dict[str, Any]) -> None:
        """Only keyboard/mouse/text over a separate socket; no media or file RPC."""
        message_type = str(message.get("type") or "")
        session_id = self._session_id(message)
        if message_type == "session_open":
            self.input_sessions.add(session_id)
            # Backend must not route input until the agent confirms the local
            # session was installed on this particular input connection.
            await self._send_input({"type": "input_ready", "session_id": session_id})
            return
        if message_type == "session_close":
            self.input_sessions.discard(session_id)
            await self._release_session_input(session_id)
            return
        if session_id not in self.input_sessions or session_id not in self.control_sessions:
            raise ValueError("Remote Desktop-inputsessionen er ikke åbnet")
        if message_type not in {"mouse", "key", "text"}:
            raise ValueError("Inputkanalen accepterer kun muse- og tastaturhandlinger")
        self.pending_input_at[session_id] = time.monotonic()
        request = (
            {"action": "text", "text": str(message.get("text") or "")[:1000]}
            if message_type == "text" else
            {"action": message_type, **{key: value for key, value in message.items()
                                       if key in ({"event", "x", "y", "button", "delta"}
                                                  if message_type == "mouse" else {"event", "key"})}}
        )
        if message_type in {"mouse", "key"}:
            request["session_id"] = session_id
        if message.get("input_id"):
            request["input_id"] = str(message["input_id"])
        socket = CAPTURE_SOCKET if message_type == "text" else INPUT_SOCKET
        started = time.monotonic()
        try:
            result = await self._input_rpc(socket, request)
            self._record_input_telemetry(session_id, (time.monotonic() - started) * 1000)
            # A successful mouse move needs no acknowledgement. On HTTPS
            # fallback each acknowledgement would otherwise cost a POST+auth.
            if not (message_type == "mouse" and message.get("event") == "move"):
                await self._send_input({"type": "input_result", "session_id": session_id, "ok": True, "result": result})
        except RpcError as exc:
            await self._send_input({"type": "input_result", "session_id": session_id, "ok": False, "error": str(exc)[:500]})

    def _record_input_telemetry(self, session_id: str, duration_ms: float) -> None:
        row = self.media_telemetry.setdefault(session_id, self._new_media_row())
        samples = int(row.get("input_rpc_samples", 0)) + 1
        row["input_rpc_samples"] = samples
        row["input_rpc_ms_last"] = round(duration_ms, 3)
        row["input_rpc_ms_max"] = round(max(float(row.get("input_rpc_ms_max", 0)), duration_ms), 3)
        row["input_rpc_ms_total"] = round(float(row.get("input_rpc_ms_total", 0)) + duration_ms, 3)
        row["input_rpc_ms_avg"] = round(row["input_rpc_ms_total"] / samples, 3)

    async def _handle_file(self, message: dict[str, Any]) -> None:
        message_type = str(message.get("type") or "")
        session_id = self._session_id(message)
        transfer_id = str(message.get("transfer_id") or "")
        try:
            if message_type == "session_open":
                self.file_sessions.add(session_id)
                try:
                    await self._event(session_id, "file_channel_opened")
                except Exception:
                    self.file_sessions.discard(session_id)
                    self.file_area.close_session(session_id)
                    raise
                return
            if session_id not in self.file_sessions:
                raise ValueError("Remote Desktop-filsessionen er ikke åbnet")
            if message_type == "session_close":
                self.file_area.close_session(session_id)
                self.file_sessions.discard(session_id)
                await self._event(session_id, "file_channel_closed")
                return
            if message_type == "file_list_request":
                result = await asyncio.to_thread(self.file_area.list, message.get("path"))
                await self._send_file({"type": "file_list_result", "session_id": session_id, **result})
                return
            if message_type == "file_download_request":
                messages = self.file_area.download_messages(
                    session_id,
                    transfer_id,
                    message.get("path"),
                )
                while True:
                    response = await asyncio.to_thread(next, messages, None)
                    if response is None:
                        break
                    await self._send_file(response)
                return
            if message_type == "file_upload_offer":
                result = await asyncio.to_thread(self.file_area.upload_offer, session_id, message)
                await self._send_file({"type": "file_upload_result", "session_id": session_id, **result})
                return
            if message_type == "file_upload_chunk":
                result = await asyncio.to_thread(self.file_area.upload_chunk, session_id, message)
                await self._send_file({"type": "file_upload_result", "session_id": session_id, **result})
                return
            if message_type == "file_upload_complete":
                result = await asyncio.to_thread(self.file_area.upload_complete, session_id, message)
                await self._send_file({"type": "file_upload_result", "session_id": session_id, **result})
                return
            if message_type in {
                "file_delete_request",
                "file_rename_request",
                "file_mkdir_request",
                "file_move_request",
            }:
                result = await asyncio.to_thread(self.file_area.operation, message_type, message)
                await self._send_file({"type": "file_operation_result", "session_id": session_id, **result})
                return
            raise ValueError("Ukendt Remote Desktop-filmeddelelse")
        except Exception as exc:
            await self._send_file(
                {
                    "type": "file_error",
                    "session_id": session_id,
                    "transfer_id": transfer_id or None,
                    "error": str(exc)[:500],
                }
            )

    async def _process_channel_message(self, channel: str, raw: str) -> None:
        message: dict[str, Any] | None = None
        try:
            if not isinstance(raw, str):
                raise ValueError("Remote Desktop kræver tekstbaseret JSON")
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise ValueError("Remote Desktop-meddelelse skal være et objekt")
            if channel == "control":
                await self._handle_control(message)
            elif channel == "input":
                await self._handle_input(message)
            else:
                await self._handle_file(message)
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            session_id = ""
            if isinstance(message, dict):
                candidate = str(message.get("session_id") or "")
                try:
                    uuid.UUID(candidate)
                    session_id = candidate
                except ValueError:
                    pass
            payload = {"type": "file_error" if channel == "files" else "error", "error": str(exc)[:500]}
            if session_id:
                payload["session_id"] = session_id
            if channel == "control":
                await self._send_control(payload)
            elif channel == "input":
                await self._send_input(payload)
            else:
                await self._send_file(payload)

    async def _input_rpc(self, socket: str, request: dict[str, Any]) -> dict[str, Any]:
        input_id = str(request.get("input_id") or "")
        async with self.input_rpc_lock:
            session_id = str(request.get("session_id") or "")
            if session_id and session_id not in self.control_sessions:
                raise RpcError("Remote Desktop-sessionen er lukket")
            if input_id and input_id in self.completed_input_ids:
                return {"accepted": True, "duplicate": True}
            # Cancellation of to_thread() does not cancel the RPC thread.
            # Wait for completion before releasing remote-held buttons.
            wire_request = ({key: value for key, value in request.items() if key != "input_id"}
                            if socket == CAPTURE_SOCKET else request)
            task = asyncio.create_task(asyncio.to_thread(call, socket, wire_request, timeout=15))
            try:
                result = await asyncio.shield(task)
            except asyncio.CancelledError:
                await asyncio.gather(task, return_exceptions=True)
                raise
            if input_id:
                if len(self.recent_input_ids) >= 2048:
                    self.completed_input_ids.discard(self.recent_input_ids.popleft())
                self.recent_input_ids.append(input_id)
                self.completed_input_ids.add(input_id)
            return result

    async def _release_session_input(self, session_id: str) -> None:
        """Release only remote-held keys/buttons of this authorized session."""
        try:
            # Wait for any in-flight input RPC before releasing the held state.
            # A queued old 'down' must never execute after this cleanup.
            async with self.input_rpc_lock:
                await asyncio.to_thread(
                    call, INPUT_SOCKET, {"action": "release_session", "session_id": session_id}, timeout=5,
                )
        except (OSError, RpcError) as exc:
            self.logger.warning("remote_desktop_input_release_failed", extra={"event": str(exc)[:200]})

    async def _release_input_sessions(self) -> None:
        for session_id in tuple(self.input_sessions):
            await self._release_session_input(session_id)
        self.input_sessions.clear()

    async def _run_input_on_demand(self) -> None:
        """Do not keep an idle third WebSocket and 15s SQL recheck alive."""
        while True:
            while not self.control_sessions:
                self.input_demand.clear()
                await self.input_demand.wait()
            input_task = asyncio.create_task(self._channel("input"))
            try:
                while self.control_sessions:
                    self.input_demand.clear()
                    await self.input_demand.wait()
            finally:
                input_task.cancel()
                await asyncio.gather(input_task, return_exceptions=True)

    def _input_queue(self) -> InputLaneQueue:
        async def process(raw: str) -> None:
            await self._process_channel_message("input", raw)

        def record_delay(raw: str, delay_ms: float) -> None:
            try:
                value = json.loads(raw)
                session_id = str(value.get("session_id") or "")
                if session_id not in self.input_sessions:
                    return
                row = self.media_telemetry.setdefault(session_id, self._new_media_row())
                count = int(row.get("input_queue_samples", 0)) + 1
                row["input_queue_samples"] = count
                row["input_queue_ms_last"] = round(delay_ms, 3)
                row["input_queue_ms_max"] = round(max(float(row.get("input_queue_ms_max", 0)), delay_ms), 3)
                row["input_queue_ms_total"] = round(float(row.get("input_queue_ms_total", 0)) + delay_ms, 3)
                row["input_queue_ms_avg"] = round(row["input_queue_ms_total"] / count, 3)
            except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
                return

        return InputLaneQueue(process, max_pending=32, on_dequeue=record_delay)

    async def _http_channel_once(self, channel: str) -> None:
        client_id = self.credential.client_id
        opened = await asyncio.to_thread(
            self.transport.json_request, "POST",
            f"/api/remote-desktop-agent/clients/{client_id}/{channel}/http/open",
            json_body={}, timeout=20,
        )
        relay_id = str(opened.get("relay_id") or "")
        if not relay_id:
            raise RuntimeError("Remote Desktop HTTPS relay returnerede intet relay-id")
        socket = _HttpRelaySocket(self.transport, client_id, channel, relay_id)
        if channel == "control":
            self.control_ws = socket
        elif channel == "input":
            self.input_ws = socket
        else:
            self.file_ws = socket
        input_queue = self._input_queue() if channel == "input" else None
        worker = asyncio.create_task(input_queue.run()) if input_queue else None
        try:
            while True:
                response = await asyncio.to_thread(
                    self.transport.json_request, "GET",
                    f"/api/remote-desktop-agent/clients/{client_id}/{channel}/http/{relay_id}/poll?timeout_seconds=25",
                    timeout=35,
                )
                for raw in response.get("messages") or []:
                    decoded = json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(decoded, dict) and decoded.get("type") == "relay_closed":
                        raise RuntimeError(str(decoded.get("reason") or "Remote Desktop HTTPS relay lukket"))
                    raw_message = raw if isinstance(raw, str) else json.dumps(raw)
                    if input_queue is not None:
                        await input_queue.put(raw_message)
                    else:
                        await self._process_channel_message(channel, raw_message)
                if response.get("closed") is True:
                    raise RuntimeError("Remote Desktop HTTPS relay er lukket")
        finally:
            if worker is not None:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)

    async def _channel(self, channel: str) -> None:
        path = f"/api/remote-desktop-agent/clients/{self.credential.client_id}/{channel}/ws"
        attempt = 0
        while True:
            try:
                async with websockets.connect(
                    self.transport.websocket_url(path),
                    extra_headers=self.transport.websocket_headers(),
                    ssl=self.ssl_context(),
                    max_size=20 * 1024 * 1024 if channel == "control" else 4 * 1024 * 1024,
                    open_timeout=20,
                    close_timeout=10,
                    ping_interval=20,
                    ping_timeout=20,
                ) as websocket:
                    if channel == "control":
                        self.control_ws = websocket
                    elif channel == "input":
                        self.input_ws = websocket
                    else:
                        self.file_ws = websocket
                    attempt = 0
                    input_queue = self._input_queue() if channel == "input" else None
                    worker = asyncio.create_task(input_queue.run()) if input_queue else None
                    try:
                        async for raw in websocket:
                            if input_queue is not None:
                                await input_queue.put(raw)
                            else:
                                await self._process_channel_message(channel, raw)
                    finally:
                        if worker is not None:
                            worker.cancel()
                            await asyncio.gather(worker, return_exceptions=True)
            except KeyboardInterrupt:
                return
            except TransportError as exc:
                # A token-fetch failure happens before the WebSocket handshake.
                # HTTPS fallback requires that very same token, so attempting it
                # immediately duplicates 5xx traffic and obscures the cause.
                # The outer bounded backoff retries normally; never skip auth.
                self.logger.warning(
                    "remote_desktop_token_or_transport_unavailable",
                    extra={"event": channel, "status_code": exc.status_code},
                )
            except (WebSocketException, OSError, RuntimeError, json.JSONDecodeError):
                # InvalidStatusCode (e.g. proxy HTTP 500) is a WebSocketException,
                # NOT ConnectionClosed/RuntimeError. It previously escaped this
                # loop, killing the agent rather than trying HTTPS fallback.
                self.logger.warning("remote_desktop_websocket_unavailable_using_https_fallback", extra={"event": channel}, exc_info=True)
                try:
                    await self._http_channel_once(channel)
                    attempt = 0
                    continue
                except Exception:
                    self.logger.exception("remote_desktop_https_relay_failed", extra={"event": channel})
            finally:
                if channel == "control":
                    self.control_ws = None
                    tasks = list(self.stream_tasks.values())
                    for task in tasks:
                        task.cancel()
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
                    self.stream_tasks.clear()
                    self.stream_options.clear()
                    self.media_pressure.clear()
                    for session_id in tuple(self.control_sessions):
                        await self._release_session_input(session_id)
                    self.control_sessions.clear()
                    self.input_demand.set()
                    await self._close_mutter_if_idle()
                elif channel == "input":
                    self.input_ws = None
                    await self._release_input_sessions()
                else:
                    self.file_ws = None
                    for session_id in tuple(self.file_sessions):
                        self.file_area.close_session(session_id)
                    self.file_sessions.clear()
            await asyncio.sleep(backoff_seconds(attempt))
            attempt += 1

    async def run(self) -> None:
        await asyncio.to_thread(
            report_status,
            self.transport,
            observed_state="online",
            payload={
                "capture_socket": os.path.exists(CAPTURE_SOCKET),
                "input_socket": os.path.exists(INPUT_SOCKET),
                "file_root": str(FILE_ROOT),
            },
        )
        await asyncio.gather(
            self._channel("control"), self._run_input_on_demand(), self._channel("files")
        )


def main() -> int:
    asyncio.run(RemoteDesktopAgent().run())
    return 0
