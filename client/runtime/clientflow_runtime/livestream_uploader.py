"""Generation-aware HLS uploader. Stale generations are rejected by the backend."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Any
import uuid
from urllib.parse import quote

from .atomic import atomic_write_json
from .config import DomainCredential
from .constants import Domain
from .livestream_paths import DESIRED_PATH, GENERATIONS_DIR, UPLOADER_STATUS_PATH
from .logging_utils import configure_logging
from .net import DomainTransport, TransportError, backoff_seconds

_SEGMENT_PATTERN = re.compile(r"^segment-(\d{9})\.(?:ts|m4s)$")


class SegmentVanishedError(RuntimeError):
    """A rolling HLS segment disappeared between directory scan and open()."""


def _canonical_generation(value: object) -> str:
    raw = str(value or "")
    try:
        parsed = uuid.UUID(raw)
    except ValueError as exc:
        raise RuntimeError("Livestream desired state har ugyldig generation") from exc
    canonical = str(parsed)
    if raw != canonical:
        raise RuntimeError("Livestreamgeneration skal være en kanonisk UUID")
    return canonical


def _read_regular_file(path: Path, *, max_bytes: int = 64 * 1024 * 1024) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError as exc:
        if _SEGMENT_PATTERN.match(path.name):
            raise SegmentVanishedError("Rullende HLS-segment forsvandt før upload") from exc
        raise RuntimeError("Livestreamfil kunne ikke åbnes sikkert") from exc
    except OSError as exc:
        raise RuntimeError("Livestreamfil kunne ikke åbnes sikkert") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > max_bytes:
            raise RuntimeError("Livestreamfil er ugyldig eller for stor")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            payload = handle.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise RuntimeError("Livestreamfil er større end uploadkontrakten tillader")
        return payload
    finally:
        os.close(descriptor)


# The publisher must not spend bandwidth uploading segments already outside
# the playable window. Four complete segments (~8s at the existing 2s config)
# offer a recovery buffer without streaming the entire 8-segment HLS archive.
LOW_LATENCY_SEGMENT_WINDOW = 4


def _manifest_span(manifest: bytes) -> tuple[int, int] | None:
    """Return inclusive sequence span; reject reordering and partial playlists."""
    try:
        lines = manifest.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None
    sequences = [line for line in lines if line.startswith("#EXT-X-MEDIA-SEQUENCE:")]
    if len(sequences) != 1:
        return None
    try:
        first = int(sequences[0].partition(":")[2])
    except ValueError:
        return None
    names = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
    if first < 0 or not 2 <= len(names) <= 30 or len(names) != sum(line.startswith("#EXTINF:") for line in lines):
        return None
    for offset, name in enumerate(names):
        match = _SEGMENT_PATTERN.fullmatch(name)
        if match is None or int(match.group(1)) != first + offset:
            return None
    return first, first + len(names) - 1


def _safe_unmodified_playlist(output: Path, lines: list[str], raw: bytes) -> tuple[list[Path], bytes] | None:
    """Preserve valid but non-basic HLS metadata without risking a broken stream."""
    if any(line.startswith(("#EXT-X-KEY:", "#EXT-X-MAP:", "#EXT-X-SESSION-KEY:")) for line in lines):
        return None
    names = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if _manifest_span(raw) is None:
        return None
    paths = [output / name for name in names]
    if not all(path.is_file() and not path.is_symlink() for path in paths):
        return None
    return paths, raw


def current_playlist_uploads(output: Path) -> tuple[list[Path], bytes] | None:
    """Select only finalized, local HLS segments referenced by a safe manifest.

    On malformed/incomplete manifests, do not publish anything: a partially
    written playlist must never advance the backend to unavailable segments.
    The output is derived solely from the locally produced allowlisted names.
    """
    manifest_path = output / "index.m3u8"
    try:
        raw = _read_regular_file(manifest_path, max_bytes=1024 * 1024)
        lines = raw.decode("utf-8").splitlines()
    except (OSError, RuntimeError, UnicodeDecodeError):
        return None
    if not lines or lines[0] != "#EXTM3U":
        return None
    sequence_index = next((i for i, line in enumerate(lines) if line.startswith("#EXT-X-MEDIA-SEQUENCE:")), None)
    if sequence_index is None:
        return None
    try:
        first_sequence = int(lines[sequence_index].partition(":")[2])
    except ValueError:
        return None
    if first_sequence < 0:
        return None
    # A standard hlssink playlist consists of header directives followed by
    # EXTINF / segment pairs. Refuse to rewrite unsupported HLS extensions.
    allowed_headers = ("#EXTM3U", "#EXT-X-VERSION:", "#EXT-X-TARGETDURATION:",
                       "#EXT-X-MEDIA-SEQUENCE:", "#EXT-X-ALLOW-CACHE:")
    header: list[str] = []
    pairs: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("#EXTINF:"):
            if i + 1 >= len(lines) or not _SEGMENT_PATTERN.fullmatch(lines[i + 1].strip()):
                return None
            pairs.append((line, lines[i + 1].strip()))
            i += 2
            continue
        if line == "#EXT-X-ENDLIST":
            # Do not trim a completed playlist, but keep it playable.
            return _safe_unmodified_playlist(output, lines, raw)
        if not any(line == prefix or line.startswith(prefix) for prefix in allowed_headers):
            # A valid future producer may add program-date-time or
            # discontinuities. Preserve the original safe playlist instead
            # of making Livestream disappear on an unrecognised tag.
            return _safe_unmodified_playlist(output, lines, raw)
        if pairs:
            return _safe_unmodified_playlist(output, lines, raw)
        header.append(line)
        i += 1
    if len(pairs) < 2 or len(pairs) > 30:
        return None
    # The filenames must agree with HLS MEDIA-SEQUENCE to prevent reordering
    # or inadvertently replaying a stale generation.
    for offset, (_, name) in enumerate(pairs):
        match = _SEGMENT_PATTERN.fullmatch(name)
        if match is None or int(match.group(1)) != first_sequence + offset:
            return None
    skip = max(0, len(pairs) - LOW_LATENCY_SEGMENT_WINDOW)
    selected = pairs[skip:]
    header[header.index(lines[sequence_index])] = f"#EXT-X-MEDIA-SEQUENCE:{first_sequence + skip}"
    payload = ("\n".join(header + [entry for pair in selected for entry in pair]) + "\n").encode("utf-8")
    paths = [output / filename for _, filename in selected]
    if not all(path.is_file() and not path.is_symlink() for path in paths):
        return None
    if _manifest_span(payload) is None:
        return None
    return paths, payload


class Uploader:
    def __init__(self) -> None:
        self.logger = configure_logging("clientflow.livestream.uploader")
        self.credential = DomainCredential.load(Domain.LIVESTREAM)
        self.transport = DomainTransport(self.credential)
        self.uploaded: dict[tuple[str, str], str] = {}
        self.last_put_ms: float | None = None
        self.last_manifest_published_at: float | None = None
        self.last_manifest_sequence: int | None = None
        self.latest_segment_local_age_seconds: float | None = None
        self.published_manifest_generation: str | None = None
        self.published_manifest_span: tuple[int, int] | None = None
        self._restore_published_manifest()

    def _restore_published_manifest(self) -> None:
        """Preserve sequence monotonicity over a normal uploader restart."""
        try:
            previous = json.loads(UPLOADER_STATUS_PATH.read_text(encoding="utf-8"))
            generation = _canonical_generation(previous.get("manifest_generation_id"))
            first = int(previous["manifest_first_sequence"])
            last = int(previous["manifest_last_sequence"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, RuntimeError):
            return
        if 0 <= first <= last <= 999_999_999:
            self.published_manifest_generation = generation
            self.published_manifest_span = (first, last)

    def _manifest_can_advance(self, generation: str, payload: bytes) -> bool:
        span = _manifest_span(payload)
        if span is None:
            return False
        if self.published_manifest_generation != generation:
            return True
        previous = self.published_manifest_span
        return previous is None or (span[0] >= previous[0] and span[1] >= previous[1])

    def _read_desired(self) -> dict[str, Any]:
        try:
            value = json.loads(DESIRED_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Livestream desired state er ugyldig") from exc
        if not isinstance(value, dict):
            raise RuntimeError("Livestream desired state skal være et objekt")
        if value and value.get("schema_version") != 1:
            raise RuntimeError("Livestream desired state mangler schema_version 1")
        desired = value.get("desired")
        if desired not in {None, "running", "stopped"}:
            raise RuntimeError("Livestream desired state er ugyldig")
        generation = value.get("generation_id")
        if generation is not None:
            value = dict(value)
            value["generation_id"] = _canonical_generation(generation)
        return value

    def _sequence(self, generation_id: str, filename: str) -> int:
        match = _SEGMENT_PATTERN.match(filename)
        if match:
            return int(match.group(1))
        segment_sequences: list[int] = []
        for uploaded_generation, uploaded_filename in self.uploaded:
            if uploaded_generation != generation_id:
                continue
            uploaded_match = _SEGMENT_PATTERN.match(uploaded_filename)
            if uploaded_match:
                segment_sequences.append(int(uploaded_match.group(1)))
        return max(segment_sequences, default=0)

    def _upload(self, generation_id: str, path: Path, *, data: bytes | None = None) -> None:
        payload = _read_regular_file(path) if data is None else data
        sha256 = hashlib.sha256(payload).hexdigest()
        key = (generation_id, path.name)
        if self.uploaded.get(key) == sha256:
            return
        sequence = self._sequence(generation_id, path.name)
        client_id = self.credential.client_id
        filename = quote(path.name, safe="")
        content_type = {
            ".m3u8": "application/vnd.apple.mpegurl",
            ".ts": "video/mp2t",
            ".m4s": "video/iso.segment",
            ".mp4": "video/mp4",
        }[path.suffix.lower()]
        started = time.monotonic()
        self.transport.request(
            "PUT",
            f"/api/livestream-agent/clients/{client_id}/generations/{generation_id}/files/{filename}?sequence={sequence}&sha256={sha256}",
            data=payload,
            headers={"Content-Type": content_type},
            expected=(200,),
            timeout=60,
        )
        self.uploaded[key] = sha256
        self.last_put_ms = round((time.monotonic() - started) * 1000, 3)
        if path.name == "index.m3u8":
            self.published_manifest_generation = generation_id
            self.published_manifest_span = _manifest_span(payload)
            self.last_manifest_published_at = time.time()
            self.last_manifest_sequence = sequence

    @property
    def current_generation(self) -> str:
        desired = self._read_desired()
        return str(desired.get("generation_id") or "")

    def _status(self, state: str, **details: Any) -> None:
        payload = {
            "schema_version": 1,
            "state": state,
            "generation_id": self.current_generation or None,
            "uploaded_files": len(self.uploaded),
            "updated_at": time.time(),
            "last_put_ms": self.last_put_ms,
            "last_manifest_published_at": self.last_manifest_published_at,
            "last_manifest_sequence": self.last_manifest_sequence,
            "manifest_generation_id": self.published_manifest_generation,
            "manifest_first_sequence": (self.published_manifest_span[0] if self.published_manifest_span else None),
            "manifest_last_sequence": (self.published_manifest_span[1] if self.published_manifest_span else None),
            "latest_segment_local_age_seconds": self.latest_segment_local_age_seconds,
            **details,
        }
        atomic_write_json(UPLOADER_STATUS_PATH, payload, mode=0o640)

    def run(self) -> int:
        attempt = 0
        while True:
            try:
                desired = self._read_desired()
                generation = str(desired.get("generation_id") or "")
                if generation:
                    self.uploaded = {key: value for key, value in self.uploaded.items() if key[0] == generation}
                if desired.get("desired") != "running" or not generation:
                    self._status("idle")
                    attempt = 0
                    time.sleep(1)
                    continue
                output = GENERATIONS_DIR / generation / "out"
                if output.is_dir():
                    selected = current_playlist_uploads(output)
                    if selected is not None:
                        paths, manifest = selected
                        try:
                            self.latest_segment_local_age_seconds = round(
                                max(0.0, time.time() - paths[-1].stat().st_mtime), 3
                            )
                        except FileNotFoundError:
                            self.latest_segment_local_age_seconds = None
                        # Do not waste bandwidth or let a transient/stale
                        # playlist replace a newer already-published manifest.
                        complete = self._manifest_can_advance(generation, manifest)
                        for path in paths if complete else ():
                            try:
                                self._upload(generation, path)
                            except SegmentVanishedError:
                                # A rolling segment vanished mid-transfer. Never
                                # publish a manifest referencing missing content.
                                complete = False
                                break
                        if complete:
                            self._upload(generation, output / "index.m3u8", data=manifest)
                            # Never retain an unbounded in-memory digest history
                            # over multi-day streams (the manifest only needs
                            # the current rolling media window).
                            active = {path.name for path in paths} | {"index.m3u8"}
                            self.uploaded = {key: digest for key, digest in self.uploaded.items()
                                             if key[0] == generation and key[1] in active}
                self._status("uploading")
                attempt = 0
                time.sleep(0.5)
            except KeyboardInterrupt:
                return 0
            except TransportError as exc:
                if exc.status_code == 409:
                    self._status("stale_generation", error=str(exc))
                    time.sleep(5)
                    continue
                self.logger.exception("upload_failed")
                self._status("degraded", error=str(exc)[:1000])
                time.sleep(backoff_seconds(attempt))
                attempt += 1
            except Exception as exc:
                self.logger.exception("uploader_failed")
                try:
                    self._status("failed", error=str(exc)[:1000])
                except Exception:
                    pass
                time.sleep(backoff_seconds(attempt))
                attempt += 1


def main() -> int:
    return Uploader().run()
