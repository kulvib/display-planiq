"""Physical-only 63D-74 media-format probe; never installed or deployed.

Runs as the existing kiosk user, uses the hash-pinned installed Mutter helper,
one capture/encode, parallel local HLS and fMP4 outputs, and tests independent
fragment decode. No networking, service edits, credentials or permanent config.
This proves only the candidate media format on the physical host, not WSS/MSE.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time

MAX_INIT = 128 * 1024
MAX_FRAGMENT = 2 * 1024 * 1024
HELPER_SHA256 = "680fe4b5714ade9e2011ddf5704f3ba35544cc38dde243b4f7c65c3706fd881f"
STATE = Path("/var/lib/clientflow/livestream")
CONFIG = Path("/etc/clientflow/livestream.json")
USER = "clientflow-kiosk"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    value = json.loads(path.read_text())
    require(isinstance(value, dict), "invalid JSON object")
    return value


class BoxAssembler:
    """Strict candidate ftyp/moov then moof/mdat, bounded incremental input.

    No assertion of decodability from framing alone. Unexpected top-level
    boxes fail the probe rather than silently dropping potentially needed data.
    """
    def __init__(self):
        self.pending = bytearray()
        self.prefix = None
        self.init = None
        self.moof = None

    def feed(self, data):
        require(0 < len(data) <= MAX_FRAGMENT, "oversized/empty mux sample")
        require(len(self.pending) + len(data) <= 2 * MAX_FRAGMENT,
                "partial box capacity")
        self.pending.extend(data)
        out = []
        while len(self.pending) >= 8:
            size, kind = struct.unpack_from(">I4s", self.pending)
            header = 8
            if size == 1:
                if len(self.pending) < 16:
                    break
                size = struct.unpack_from(">Q", self.pending, 8)[0]
                header = 16
            require(header <= size <= MAX_FRAGMENT, "invalid/unbounded MP4 box size")
            if len(self.pending) < size:
                break
            box = bytes(self.pending[:size])
            del self.pending[:size]
            if self.init is None:
                if self.prefix is None:
                    require(kind == b"ftyp" and len(box) <= MAX_INIT, "expected ftyp")
                    self.prefix = box
                else:
                    require(kind == b"moov" and len(self.prefix) + len(box) <= MAX_INIT,
                            "expected bounded moov")
                    self.init = self.prefix + box
                    self.prefix = None
            elif self.moof is None:
                require(kind == b"moof", "expected moof, got " + repr(kind))
                self.moof = box
            else:
                require(kind == b"mdat" and len(self.moof) + len(box) <= MAX_FRAGMENT,
                        "expected bounded mdat")
                out.append(self.moof + box)
                self.moof = None
        return out


def self_test():
    def box(kind, data):
        return struct.pack(">I4s", 8 + len(data), kind) + data
    init = box(b"ftyp", b"a") + box(b"moov", b"b")
    media = box(b"moof", b"c") + box(b"mdat", b"d")
    a = BoxAssembler()
    got = []
    for byte in init + media * 3:
        got.extend(a.feed(bytes([byte])))
    require(a.init == init and got == [media] * 3, "split-box test")
    for bad in (struct.pack(">I4s", 0, b"ftyp"),
                struct.pack(">I4s", MAX_FRAGMENT + 1, b"ftyp"),
                box(b"mdat", b"x")):
        try:
            BoxAssembler().feed(bad)
        except RuntimeError:
            pass
        else:
            raise RuntimeError("malformed box accepted")
    print("ASSEMBLER_SELF_TEST=PASS", flush=True)


def ensure_idle():
    require(read_json(STATE / "desired-state.json").get("desired") == "stopped",
            "Livestream desired state is not stopped")
    producer = read_json(STATE / "producer-status.json")
    require(producer.get("state") == "stopped" and not producer.get("pid"),
            "Livestream producer is not stopped")


def decode_fragment(Gst, target, payload, minimum_frames):
    target.write_bytes(payload)
    pipeline = Gst.parse_launch(
        'filesrc location="' + str(target) + '" ! qtdemux ! h264parse name=parser '
        '! video/x-h264,alignment=au ! avdec_h264 ! fakesink name=decoded sync=false signal-handoffs=true'
    )
    first = []
    frames = [0]

    def observe(_pad, info):
        buf = info.get_buffer()
        if buf is not None and not first:
            first.append(not buf.has_flags(Gst.BufferFlags.DELTA_UNIT))
        return Gst.PadProbeReturn.OK

    def handoff(*_args):
        frames[0] += 1

    pipeline.get_by_name("parser").get_static_pad("src").add_probe(
        Gst.PadProbeType.BUFFER, observe)
    pipeline.get_by_name("decoded").connect("handoff", handoff)
    try:
        require(pipeline.set_state(Gst.State.PLAYING) != Gst.StateChangeReturn.FAILURE,
                "fragment decode start failed")
        msg = pipeline.get_bus().timed_pop_filtered(
            8 * Gst.SECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS)
        require(msg is not None and msg.type == Gst.MessageType.EOS,
                "fragment decode error or timeout")
        require(first == [True] and frames[0] >= minimum_frames,
                "fragment did not start with a sync sample and decode enough frames")
        return frames[0]
    finally:
        pipeline.set_state(Gst.State.NULL)
        target.unlink(missing_ok=True)


def child(helper_path, work_path, cfg_path):
    require(os.getuid() == pwd.getpwnam(USER).pw_uid, "wrong graphical user")
    require(os.environ.get("XDG_SESSION_TYPE") == "wayland", "not Wayland")
    helper_path = Path(helper_path)
    require(digest(helper_path) == HELPER_SHA256, "capture helper hash mismatch")
    spec = importlib.util.spec_from_file_location("approved_capture_helper", helper_path)
    require(spec is not None and spec.loader is not None, "helper unavailable")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    Gst = helper.Gst
    Gst.init(None)
    required = ("pipewiresrc", "queue", "videoconvert", "videorate",
                "x264enc", "tee", "h264parse", "mpegtsmux", "hlssink",
                "mp4mux", "appsink", "qtdemux", "avdec_h264", "fakesink")
    missing = [name for name in required if Gst.ElementFactory.find(name) is None]
    require(not missing, "missing GStreamer elements: " + ", ".join(missing))
    print("GSTREAMER=" + Gst.version_string(), flush=True)
    cfg = read_json(Path(cfg_path))
    fps = int(cfg.get("fps", 10))
    bitrate = int(cfg.get("bitrate_kbit", 12000))
    preset = str(cfg.get("preset") or "veryfast")
    require(1 <= fps <= 30 and 1000 <= bitrate <= 15000,
            "profile outside bounded probe budget")
    require(preset in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium"},
            "invalid x264 preset")
    print(f"PROFILE=fps:{fps},bitrate_kbit:{bitrate},preset:{preset},"
          f"configured_segment:{cfg.get('segment_seconds', 2)},probe_segment:1", flush=True)
    root = Path(work_path)
    hls = root / "hls"
    hls.mkdir(mode=0o700)
    capture = helper.MutterScreenCast()
    pipeline = None
    assembler = BoxAssembler()
    fragments = []
    try:
        capture.create_session()
        capture.record_monitor()
        node_id = capture.start()
        # No arbitrary dropping of encoded delta frames before either muxer.
        # Both local consumers have finite queues; this is a format probe, not
        # the final production nonblocking network fanout.
        description = (
            f"pipewiresrc path={node_id} do-timestamp=true on-disconnect=error "
            f"keepalive-time={max(1, round(1000 / fps))} "
            "! queue max-size-buffers=8 leaky=downstream "
            "! videoconvert ! videorate "
            f"! video/x-raw,format=I420,framerate={fps}/1 "
            f"! x264enc tune=zerolatency speed-preset={preset} "
            f"key-int-max={fps} bframes=0 bitrate={bitrate} ! tee name=encoded "
            "encoded. ! queue max-size-buffers=30 max-size-bytes=4194304 max-size-time=2000000000 "
            "! h264parse config-interval=-1 ! mpegtsmux "
            f'! hlssink target-duration=1 playlist-length=8 max-files=10 '
            f'location="{hls}/segment-%09d.ts" playlist-location="{hls}/index.m3u8" '
            "encoded. ! queue max-size-buffers=30 max-size-bytes=4194304 max-size-time=2000000000 "
            "! h264parse config-interval=-1 ! video/x-h264,stream-format=avc,alignment=au "
            "! mp4mux fragment-duration=1000 streamable=true "
            "! appsink name=media sync=false max-buffers=8 drop=false"
        )
        pipeline = Gst.parse_launch(description)
        sink = pipeline.get_by_name("media")
        require(pipeline.set_state(Gst.State.PLAYING) != Gst.StateChangeReturn.FAILURE,
                "capture pipeline start failed")
        bus = pipeline.get_bus()
        start = time.monotonic()
        while time.monotonic() - start < 15:
            msg = bus.pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS)
            if msg is not None:
                if msg.type == Gst.MessageType.ERROR:
                    err, _debug = msg.parse_error()
                    raise RuntimeError("GStreamer pipeline error: " + str(err)[:300])
                raise RuntimeError("unexpected live EOS")
            sample = sink.emit("try-pull-sample", 200 * Gst.MSECOND)
            if sample is not None:
                buf = sample.get_buffer()
                size = buf.get_size()
                require(0 < size <= MAX_FRAGMENT, "mux buffer exceeds wire budget")
                for fragment in assembler.feed(buf.extract_dup(0, size)):
                    if len(fragments) < 6:
                        fragments.append(fragment)
            if len(fragments) >= 6 and len(list(hls.glob("segment-*.ts"))) >= 6:
                break
        elapsed = time.monotonic() - start
        require(assembler.init is not None and len(fragments) >= 6,
                "insufficient complete live fMP4 fragments before EOS")
        manifest = (hls / "index.m3u8").read_text()
        durations = [float(line.split(":", 1)[1].split(",", 1)[0])
                     for line in manifest.splitlines() if line.startswith("#EXTINF:")]
        require(len(durations) >= 4 and "#EXT-X-TARGETDURATION:1" in manifest.splitlines()
                and all(0 < d <= 1.5 for d in durations),
                "parallel one-second HLS manifest not verified")
        print(f"LIVE_MUX=PASS fragments={len(fragments)} init_bytes={len(assembler.init)} "
              f"elapsed_seconds={elapsed:.2f}", flush=True)
        print("HLS_PARALLEL=PASS durations=" + ",".join(f"{d:.3f}" for d in durations),
              flush=True)
    finally:
        if pipeline is not None:
            pipeline.set_state(Gst.State.NULL)
        capture.close()

    for i, fragment in enumerate(fragments, 1):
        frames = decode_fragment(Gst, root / "decode.mp4", assembler.init + fragment,
                                 max(1, fps // 2))
        print(f"FRAGMENT_{i}=PASS bytes={len(fragment)} decoded_frames={frames}", flush=True)
    print("PHYSICAL_MEDIA_FORMAT=PASS (not WSS/MSE acceptance)", flush=True)


def parent():
    require(os.geteuid() == 0 and socket.gethostname() == "viborg1-NUC14MNK-B2",
            "wrong host or user")
    identity = read_json(Path("/etc/clientflow/identity.json"))
    require(str(identity.get("CLIENT_ID", identity.get("client_id"))) == "3", "wrong client")
    ensure_idle()
    cfg = read_json(CONFIG)
    require(cfg.get("schema_version") == 1, "unexpected config schema")
    config_hash = digest(CONFIG)
    candidates = sorted(Path("/opt/clientflow/releases").glob(
        "*1248*/**/livestream_wayland_capture.py"))
    matches = [p for p in candidates if p.is_file() and digest(p) == HELPER_SHA256]
    require(len(matches) == 1, "exact approved 1248 capture helper not uniquely found")
    account = pwd.getpwnam(USER)
    runtime = Path("/run/user") / str(account.pw_uid)
    require((runtime / "bus").is_socket(), "kiosk session bus unavailable")
    require(shutil.disk_usage("/dev/shm").free >= 128 * 1024 * 1024,
            "insufficient temporary RAM storage")
    self_test()
    with tempfile.TemporaryDirectory(prefix="cf63d74-", dir="/dev/shm") as d:
        root = Path(d)
        root.chmod(0o755)
        work = root / "media"
        work.mkdir(mode=0o700)
        os.chown(work, account.pw_uid, account.pw_gid)
        config_copy = root / "config.json"
        # Copy only the non-secret encoder settings, not the full client config.
        config_copy.write_text(json.dumps({k: cfg[k] for k in
            ("fps", "bitrate_kbit", "preset", "segment_seconds") if k in cfg}))
        config_copy.chmod(0o644)
        script = root / "probe.py"
        shutil.copyfile(__file__, script)
        script.chmod(0o644)
        helper_copy = root / "capture_helper.py"
        shutil.copyfile(matches[0], helper_copy)
        helper_copy.chmod(0o644)
        require(digest(helper_copy) == HELPER_SHA256, "copied helper hash mismatch")
        env = [
            "HOME=" + account.pw_dir, "USER=" + USER, "LOGNAME=" + USER,
            "PATH=/usr/bin:/bin", "LANG=C.UTF-8", "XDG_RUNTIME_DIR=" + str(runtime),
            "DBUS_SESSION_BUS_ADDRESS=unix:path=" + str(runtime / "bus"),
            "XDG_SESSION_TYPE=wayland", "PYTHONDONTWRITEBYTECODE=1",
            "PYTHONUNBUFFERED=1",
        ]
        command = ["/usr/sbin/runuser", "-u", USER, "--", "/usr/bin/env", "-i",
                   *env, "/usr/bin/python3", "-B", "-u", str(script),
                   "--child", str(helper_copy), str(work), str(config_copy)]
        process = subprocess.Popen(command, start_new_session=True)
        try:
            deadline = time.monotonic() + 110
            while process.poll() is None:
                ensure_idle()
                require(time.monotonic() < deadline, "physical probe deadline")
                time.sleep(0.25)
            require(process.returncode == 0, "physical child failed")
            ensure_idle()
            require(digest(CONFIG) == config_hash, "live config changed during probe")
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
    print("CLEANUP=PASS; no persistent changes or uploads", flush=True)


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--self-test"]:
            self_test()
        elif len(sys.argv) == 5 and sys.argv[1] == "--child":
            child(*sys.argv[2:])
        elif len(sys.argv) == 1:
            parent()
        else:
            raise RuntimeError("invalid arguments")
    except Exception as exc:
        print("STOP: " + str(exc)[:400], file=sys.stderr, flush=True)
        raise SystemExit(1)
