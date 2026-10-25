"""Phase 62 HLS progress instrumentation with phase 65A native-geometry guard."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
import io
from contextlib import redirect_stdout

ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / 'client/runtime/clientflow_runtime/livestream_wayland_capture.py'


def _functions(*names):
    tree = ast.parse(CAPTURE.read_text(encoding='utf-8'))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {n.name for n in selected} == set(names)
    return selected


def test_native_geometry_pipeline_encode_progress_and_hls_contract(tmp_path):
    class Pipeline:
        pass

    descriptions = []
    def parse_launch(description):
        descriptions.append(description)
        return Pipeline()

    Gst = SimpleNamespace(Pipeline=Pipeline, parse_launch=parse_launch)
    scope = {'Gst': Gst, 'Path': Path}
    exec(compile(ast.Module(body=_functions('_build_pipeline'), type_ignores=[]), str(CAPTURE), 'exec'), scope)
    pipeline = scope['_build_pipeline'](63, tmp_path, 10, 12000, 'veryfast', 2, 8)
    assert isinstance(pipeline, Pipeline)
    desc = descriptions[0]
    for fragment in (
        'pipewiresrc name=capture_source path=63',
        'video/x-raw,format=I420,framerate=10/1',
        'x264enc name=h264_encoder tune=zerolatency speed-preset=veryfast',
        'mpegtsmux name=ts_mux',
        'hlssink target-duration=2 playlist-length=8',
        'bitrate=12000',
    ):
        assert fragment in desc
    assert str(tmp_path / 'index.m3u8') in desc
    assert str(tmp_path / 'segment-%09d.ts') in desc
    # Fixed geometry is not part of the format negotiation: the active Mutter
    # monitor may be ultrawide, portrait, 16:10 or any supported native size.
    assert 'videoscale' not in desc
    assert 'add-borders' not in desc
    assert 'width=' not in desc and 'height=' not in desc
    for name in ('capture_source', 'h264_encoder', 'ts_mux'):
        assert f'name={name}' in desc


def test_stage_progress_reports_frames_without_frames_or_tokens(tmp_path):
    scope = {'_STOP': False}
    removed = []
    class Pad:
        def add_probe(self, _kind, cb, stage):
            for _ in range({'source': 3, 'encoded': 2, 'muxed': 1}[stage]):
                cb(self, None, stage)
            return 111
        def remove_probe(self, pid):
            removed.append(pid)

    class Element:
        def get_static_pad(self, name):
            assert name == 'src'
            return Pad()

    class Bus:
        ticks = 0
        def timed_pop_filtered(self, *_args):
            self.ticks += 1
            if self.ticks >= 2:
                scope['_STOP'] = True
            return None

    class Pipeline:
        def get_by_name(self, name):
            assert name in {'capture_source', 'h264_encoder', 'ts_mux'}
            return Element()
        def get_bus(self):
            return Bus()
        def set_state(self, state):
            assert state in {'PLAYING', 'NULL'}
            return 'SUCCESS'

    monotonic = iter([0, 6, 12, 13])
    scope.update({
        'Gst': SimpleNamespace(
            PadProbeReturn=SimpleNamespace(OK=1),
            PadProbeType=SimpleNamespace(BUFFER=1),
            State=SimpleNamespace(PLAYING='PLAYING', NULL='NULL'),
            StateChangeReturn=SimpleNamespace(FAILURE='FAILURE'),
            SECOND=1,
            MessageType=SimpleNamespace(ERROR=1, EOS=2),
        ),
        'time': SimpleNamespace(monotonic=lambda: next(monotonic)),
    })
    exec(compile(ast.Module(body=_functions('_run_pipeline'), type_ignores=[]), str(CAPTURE), 'exec'), scope)
    output = io.StringIO()
    with redirect_stdout(output):
        scope['_run_pipeline'](Pipeline(), tmp_path)
    message = output.getvalue()
    assert 'clientflow_hls_progress' in message
    assert 'clientflow_hls_final' in message
    assert 'source_buffers=3' in message
    assert 'encoded_buffers=2' in message
    assert 'muxed_buffers=1' in message
    assert len(removed) == 3


def test_capture_requires_only_native_pipeline_elements():
    tree = ast.parse(CAPTURE.read_text(encoding='utf-8'))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_require_elements')
    required = ast.unparse(fn)
    assert 'videoscale' not in required
    for element in ('pipewiresrc', 'queue', 'videoconvert', 'videorate', 'x264enc', 'h264parse', 'mpegtsmux', 'hlssink'):
        assert element in required
