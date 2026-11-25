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


def test_stale_or_future_media_is_rejected(tmp_path):
    import os
    import time
    media.publish_latest(tmp_path, media.wire_pair(INIT, FRAGMENT, 1, 10))
    assert media.read_latest(tmp_path, max_age_seconds=3)
    file = tmp_path / media.FILENAME
    for stamp in (time.time() - 10, time.time() + 10):
        os.utime(file, (stamp, stamp))
        with pytest.raises(ValueError, match="stale"):
            media.read_latest(tmp_path, max_age_seconds=3)


def test_opt_in_pipeline_retains_one_capture_encoder_and_legacy_hls(tmp_path):
    import ast
    from types import SimpleNamespace
    capture = ROOT / "client/runtime/clientflow_runtime/livestream_wayland_capture.py"
    tree = ast.parse(capture.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_build_pipeline")
    descriptions = []
    class Pipeline:
        pass
    def parse_launch(description):
        descriptions.append(description)
        return Pipeline()
    scope = {"Gst": SimpleNamespace(Pipeline=Pipeline, parse_launch=parse_launch), "Path": Path}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(capture), "exec"), scope)
    build = scope["_build_pipeline"]
    build(63, tmp_path, 10, 12000, "veryfast", 2, 8)
    build(63, tmp_path, 10, 12000, "veryfast", 1, 8, continuous=True)
    old, dual = descriptions
    assert "cf_mp4" not in old and "target-duration=2" in old
    assert dual.count("pipewiresrc") == 1 and dual.count("x264enc") == 1
    assert "tee name=cf_encode" in dual and "cf_encode." in dual
    assert "key-int-max=10" in dual and "hlssink target-duration=1" in dual
    assert "mp4mux fragment-duration=1000" in dual and "leaky=downstream" in dual
    assert "max-size-bytes=4194304" in dual and "max-buffers=4" in dual
    assert "width=" not in dual and "height=" not in dual
    with pytest.raises(ValueError, match="one-second"):
        build(63, tmp_path, 10, 12000, "veryfast", 2, 8, continuous=True)
