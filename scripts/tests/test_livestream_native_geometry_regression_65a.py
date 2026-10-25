"""Regression gate 65A: native geometry without changing the proven pipeline stages."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "client/runtime/clientflow_runtime/livestream_wayland_capture.py"
MEDIA = ROOT / "backend/service1/routers/livestream_media.py"


def _build(tmp_path: Path, fps: int = 10):
    tree = ast.parse(CAPTURE.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_build_pipeline")
    descriptions: list[str] = []

    class Pipeline:
        pass

    def parse_launch(description):
        descriptions.append(description)
        return Pipeline()

    scope = {"Gst": SimpleNamespace(Pipeline=Pipeline, parse_launch=parse_launch), "Path": Path}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(CAPTURE), "exec"), scope)
    scope["_build_pipeline"](63, tmp_path, fps, 12000, "veryfast", 2, 8)
    return descriptions[0]


def test_native_monitor_geometry_kept_for_portrait_ultrawide_and_4k(tmp_path):
    # Same pipeline for every native size: no imposed width/height, letterboxing
    # or additional video source; PipeWire/Mutter remains the geometry authority.
    for fps in (1, 10, 30):
        pipeline = _build(tmp_path, fps=fps)
        assert f"framerate={fps}/1" in pipeline
        assert "width=" not in pipeline and "height=" not in pipeline
        assert "videoscale" not in pipeline
        assert "add-borders" not in pipeline
        assert "pipewiresrc name=capture_source path=63" in pipeline
        assert "x264enc name=h264_encoder" in pipeline
        assert "mpegtsmux name=ts_mux" in pipeline
        assert "hlssink" in pipeline


def test_hls_health_still_reports_missing_manifest_as_read_only_diagnostic():
    source = MEDIA.read_text(encoding="utf-8")
    assert '"Manifest ikke fundet"' in source
    assert '"index.m3u8"' in source
    assert '@router.get("/hls-cap/{client_id}/health")' in source


def test_remote_desktop_and_auth_transport_not_modified_by_65a():
    agent = (ROOT / "client/runtime/clientflow_runtime/remote_desktop_agent.py").read_text(encoding="utf-8")
    assert "except TransportError as exc:" in agent
    assert "except (WebSocketException, OSError, RuntimeError, json.JSONDecodeError)" in agent
    assert "await self._http_channel_once(channel)" in agent
    assert '"remote_desktop_token_or_transport_unavailable"' in agent
