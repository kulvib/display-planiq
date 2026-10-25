"""RD capture must not depend on optional GNOME keyboard injection initialization."""
from __future__ import annotations

import ast
import base64
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "client/runtime/clientflow_runtime/remote_desktop_mutter_worker.py"


def test_capture_does_not_initialize_keyboard_but_text_still_does() -> None:
    source = WORKER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    worker_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Worker")

    calls = {"keyboard_init": 0, "capture": 0, "keyboard_close": 0}

    class Cast:
        def __init__(self):
            pass

        def start(self, monitor):
            return 111, "DP-1"

        def close(self):
            pass

    class Pipeline:
        def __init__(self):
            pass

        def close(self):
            pass

        def ensure(self, *_args, **_kwargs):
            pass

        def capture(self):
            calls["capture"] += 1
            return b"jpeg-frame", 1280, 720

    class Keyboard:
        def __init__(self):
            calls["keyboard_init"] += 1

        def type_text(self, text):
            assert text == "ok"

        def close(self):
            calls["keyboard_close"] += 1

    namespace: dict[str, Any] = {
        "Any": Any, "base64": base64, "MutterScreenCast": Cast,
        "MutterKeyboard": Keyboard, "FramePipeline": Pipeline,
    }
    exec(compile(ast.Module(body=[worker_class], type_ignores=[]), str(WORKER), "exec"), namespace)
    worker = namespace["Worker"]()
    assert calls["keyboard_init"] == 0
    result = worker.capture({"action": "capture", "width": 1280, "height": 720, "quality": 85})
    assert result["ok"] is True
    assert calls["capture"] == 1
    assert calls["keyboard_init"] == 0
    assert worker.text({"text": "ok"})["ok"] is True
    assert calls["keyboard_init"] == 1
    worker.close()
    assert calls["keyboard_close"] == 1
    assert worker.keyboard is None
