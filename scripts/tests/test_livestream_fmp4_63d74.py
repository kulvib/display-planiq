"""Pure runtime fragment/atomic handoff tests, no GStreamer installation needed."""
import importlib.util
from pathlib import Path
import struct

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "livestream_fmp4", ROOT / "client/runtime/clientflow_runtime/livestream_fmp4.py")
media = importlib.util.module_from_spec(spec)
spec.loader.exec_module(media)


def box(kind, data):
    return struct.pack(">I4s", len(data) + 8, kind) + data


INIT = box(b"ftyp", b"a") + box(b"moov", b"b")
FRAGMENT = box(b"moof", b"c") + box(b"mdat", b"d")


def test_incremental_assembler():
    a = media.BoxAssembler()
    result = []
    for byte in INIT + FRAGMENT * 3:
        result.extend(a.feed(bytes([byte])))
    assert a.init == INIT
    assert result == [FRAGMENT] * 3
    assert not a.pending
    assert a.moof is None


@pytest.mark.parametrize("bad", [box(b"mdat", b"x"), struct.pack(">I4s", 0, b"ftyp"),
                                  struct.pack(">I4s", media.MAX_FRAGMENT + 1, b"ftyp")])
def test_bad_box(bad):
    with pytest.raises(ValueError):
        media.BoxAssembler().feed(bad)


def test_wire_and_replace(tmp_path):
    for seq in range(1, 20):
        pair = media.wire_pair(INIT, FRAGMENT, seq, seq * 1000000)
        media.publish_latest(tmp_path, pair)
        first, second = media.read_latest(tmp_path)
        assert first + second == pair
        assert media.HEADER.unpack_from(second)[4] == seq
    assert sorted(p.name for p in tmp_path.iterdir()) == [media.FILENAME]
    for bad in (pair[:-1], pair + b"x", b"bad", pair[:5] + b"\x02" + pair[6:]):
        with pytest.raises(ValueError):
            media.split_pair(bad)


def test_symlink_and_fifo_fail_without_blocking(tmp_path):
    target = tmp_path / "other"
    target.write_bytes(media.wire_pair(INIT, FRAGMENT, 1, 0))
    latest = tmp_path / media.FILENAME
    latest.symlink_to(target)
    with pytest.raises(OSError):
        media.read_latest(tmp_path)
    latest.unlink()
    import os
    os.mkfifo(latest)
    with pytest.raises(ValueError):
        media.read_latest(tmp_path)
