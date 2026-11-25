"""Bounded media-only handoff candidate, derived from the physical 63D-74 probe.

No network, tokens, or service registration. A single producer owns the output
directory. Complete init+fragment wire pairs are published atomically; the
credential-bearing uploader must read only the latest pair and never backlog.
The muxer must be independently verified to emit sync-sample fragments.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import struct
import tempfile
import time

MAX_INIT = 128 * 1024
MAX_FRAGMENT = 2 * 1024 * 1024
MAX_INTEGER = (1 << 53) - 1
HEADER = struct.Struct(">4sBBHQQI")
MAX_PAIR = 2 * HEADER.size + MAX_INIT + MAX_FRAGMENT
FILENAME = "latest.cfls"


def require(condition, message):
    if not condition:
        raise ValueError(message)


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


def wire_pair(init, fragment, sequence, timestamp_us):
    require(type(init) is bytes and 0 < len(init) <= MAX_INIT, "invalid init")
    require(type(fragment) is bytes and 0 < len(fragment) <= MAX_FRAGMENT, "invalid fragment")
    require(type(sequence) is int and 0 < sequence <= MAX_INTEGER, "invalid sequence")
    require(type(timestamp_us) is int and 0 <= timestamp_us <= MAX_INTEGER, "invalid timestamp")
    return (HEADER.pack(b"CFLS", 1, 1, 0, 0, 0, len(init)) + init
            + HEADER.pack(b"CFLS", 1, 2, 0, sequence, timestamp_us, len(fragment)) + fragment)


def split_pair(payload):
    require(type(payload) is bytes and 2 * HEADER.size < len(payload) <= MAX_PAIR,
            "invalid pair size")
    offset = 0
    wires = []
    for expected in (1, 2):
        require(len(payload) - offset >= HEADER.size, "truncated wire")
        magic, version, kind, reserved, seq, timestamp, size = HEADER.unpack_from(payload, offset)
        cap = MAX_INIT if expected == 1 else MAX_FRAGMENT
        require(magic == b"CFLS" and version == 1 and kind == expected and reserved == 0,
                "invalid wire header")
        require(0 < size <= cap and offset + HEADER.size + size <= len(payload), "invalid wire length")
        require(seq <= MAX_INTEGER and timestamp <= MAX_INTEGER, "invalid wire integer")
        require((seq == 0 and timestamp == 0) if expected == 1 else seq > 0, "invalid wire metadata")
        end = offset + HEADER.size + size
        wires.append(payload[offset:end])
        offset = end
    require(offset == len(payload), "trailing wire bytes")
    return tuple(wires)


def publish_latest(directory: Path, payload: bytes):
    """One writer; caller owns lifecycle and must clear stale generation media."""
    split_pair(payload)
    fd, tmp = tempfile.mkstemp(prefix=".cfls-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o640)
            handle.write(payload)
        os.replace(tmp, directory / FILENAME)
    finally:
        Path(tmp).unlink(missing_ok=True)


def read_latest(directory: Path, *, max_age_seconds: float | None = None):
    """Open a bounded regular file; reject symlinks, devices and FIFO blocking."""
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(FILENAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= MAX_PAIR, "invalid media file")
            if max_age_seconds is not None:
                require(0 <= time.time() - info.st_mtime <= max_age_seconds, "stale media file")
            with os.fdopen(fd, "rb", closefd=False) as handle:
                payload = handle.read(MAX_PAIR + 1)
            require(len(payload) == info.st_size, "media file changed")
            return split_pair(payload)
        finally:
            os.close(fd)
    finally:
        os.close(directory_fd)
