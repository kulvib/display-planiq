"""Viborg1 1248 regression: strict, in-memory repair of hlssink's +1 header.

No display, backend credential, HTTP, or signed-release mutation is needed.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client/runtime"))

from clientflow_runtime import livestream_uploader as ls  # noqa: E402


def manifest(first: int, *, offset: int = 0, count: int = 8,
             gap: bool = False, suffix: str = "", extra: str = "") -> bytes:
    names = [f"segment-{first + i + (1 if gap and i >= 3 else 0):09d}.ts"
             for i in range(count)]
    headers = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-TARGETDURATION:2",
        f"#EXT-X-MEDIA-SEQUENCE:{first + offset}",
    ]
    if extra:
        headers.append(extra)
    return ("\n".join(headers + [entry
        for name in names for entry in ("#EXTINF:2.000,", name)]) + "\n").encode()


def output_dir(tmp_path: Path, raw: bytes) -> Path:
    out = tmp_path / "out"
    out.mkdir(parents=True)
    (out / "index.m3u8").write_bytes(raw)
    for name in [
        line for line in raw.decode().splitlines()
        if line.startswith("segment-")
    ]:
        (out / name).write_bytes(b"segment")
    return out


def test_viborg1_plus_one_sequence_normalizes_only_in_memory(tmp_path):
    raw = manifest(58, offset=1)
    out = output_dir(tmp_path, raw)
    assert ls._manifest_span(raw) is None
    paths, payload = ls.current_playlist_uploads(out)
    assert [int(path.stem.split("-")[-1]) for path in paths] == [62, 63, 64, 65]
    assert ls._manifest_span(payload) == (62, 65)
    assert b"#EXT-X-MEDIA-SEQUENCE:62\n" in payload
    assert (out / "index.m3u8").read_bytes() == raw
    assert ls._manifest_span(raw) is None


def test_already_correct_playlist_is_unchanged_except_latency_trim(tmp_path):
    raw = manifest(58)
    out = output_dir(tmp_path, raw)
    paths, payload = ls.current_playlist_uploads(out)
    assert len(paths) == ls.LOW_LATENCY_SEGMENT_WINDOW
    assert ls._manifest_span(payload) == (62, 65)
    assert b"#EXT-X-MEDIA-SEQUENCE:62\n" in payload
    assert ls._normalize_hlssink_media_sequence(raw) == raw


def test_non_one_offsets_missing_segments_and_gaps_never_pass(tmp_path):
    for offset, gap, missing in [(2, False, False), (-1, False, False),
                                 (1, True, False), (1, False, True)]:
        raw = manifest(10, offset=offset, gap=gap)
        out = output_dir(tmp_path / f"case_{offset}_{gap}_{missing}", raw)
        if missing:
            (out / "segment-000000016.ts").unlink()
        assert ls.current_playlist_uploads(out) is None


def test_untrusted_or_unsupported_headers_remain_restricted(tmp_path):
    key = "#EXT-X-KEY:METHOD=AES-128,URI=\"https://example.invalid/key\""
    raw = manifest(10, offset=1, extra=key)
    out = output_dir(tmp_path, raw)
    assert ls.current_playlist_uploads(out) is None
    assert (out / "index.m3u8").read_bytes() == raw


def test_future_safe_extensions_preserve_original_manifest_and_correct_offset(tmp_path):
    raw = manifest(20, offset=1, count=4, extra="#EXT-X-INDEPENDENT-SEGMENTS")
    out = output_dir(tmp_path, raw)
    paths, payload = ls.current_playlist_uploads(out)
    assert len(paths) == 4
    assert ls._manifest_span(payload) == (20, 23)
    assert b"#EXT-X-INDEPENDENT-SEGMENTS" in payload
    assert (out / "index.m3u8").read_bytes() == raw


def test_upload_contract_uses_corrected_sequence_sha_and_local_files(tmp_path):
    out = output_dir(tmp_path, manifest(30, offset=1))
    paths, payload = ls.current_playlist_uploads(out)
    calls = []
    class Transport:
        def request(self, method, path, *, data, headers, expected, timeout):
            calls.append((method, path, data, headers, expected, timeout))
    uploader = ls.Uploader.__new__(ls.Uploader)
    uploader.credential = SimpleNamespace(client_id=3)
    uploader.transport = Transport()
    uploader.uploaded = {}
    uploader.last_put_ms = None
    uploader.last_manifest_sequence = None
    uploader.last_manifest_published_at = None
    uploader.published_manifest_generation = None
    uploader.published_manifest_span = None
    generation = "12345678-1234-4234-8234-123456789abc"
    for path in paths:
        uploader._upload(generation, path)
    uploader._upload(generation, out / "index.m3u8", data=payload)
    assert len(calls) == 5
    assert uploader.published_manifest_span == (34, 37)
    assert uploader.last_manifest_sequence == 37
    for method, path, body, headers, expected, timeout in calls:
        assert method == "PUT" and expected == (200,) and timeout == 60
        assert generation in path
        assert f"sha256={hashlib.sha256(body).hexdigest()}" in path
        assert headers["Content-Type"] in {"video/mp2t", "application/vnd.apple.mpegurl"}
    assert calls[-1][2] == payload
    assert "sequence=37" in calls[-1][1]
