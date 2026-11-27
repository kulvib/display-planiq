"""Plan whether the exact already-proven WASM build can be reused.

No cache, network or mutable artifact trust. The only fast path is the
specific compiled bytes and complete build recipe previously verified by
the full native-WASM suite and Chromium (run 46016976607, PR 442).
The pinned-action recipe produced the same JS/WASM hashes and sizes as the
previous verified build (run 45468688912); no binary update was required.
Manual dispatch and any input/recipe mismatch require a full rebuild.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = Path(".github/workflows/freerdp-wasm-pilot.yml")
RECIPE_SHA256 = "ee2d166fc21f366119374da9698d003ddc3c7f4fb3ac694184646c57b6fc547d"
PINS = {
    "scripts/apply_freerdp_em_screen_fix.py": "5c0a9f34c915a5599aab90b51e70e55aa2671e16adfe240de384d1df05d7db85",
    "frontend/public/native-rdp/provenance.json": "b41c67644c046edd9e746ee9dd3afa7d62bcccdceea0db684dacb3d60c076335",
    "frontend/scripts/checkNativeRdpWasm.mjs": "aaad679245bd6a9cbf3c40f9e18dba8c80e9e82bab68743b237ed9021ad536b4",
    "frontend/public/native-rdp/sdl-freerdp.js": "c7d0a7e20a7b6473c5743892086b00dfb096807b8386adf992ab294867ad8112",
    "frontend/public/native-rdp/sdl-freerdp.wasm": "f5cfa907421b47c3ed6acdee329f5ebda7e9279c4a5972e02139dc8e2fe6f315"
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_recipe(workflow: str) -> str:
    # Orchestration may change, but every compile step, runner/container,
    # action revision, argument and artifact upload remains part of the lock.
    body = workflow.split("  compile-wasm:\n", 1)[1].split("\n  chromium-wasm-proof:", 1)[0]
    prefix = "    needs: plan-build\n    if: needs.plan-build.outputs.rebuild == 'true'\n"
    if not body.startswith(prefix):
        raise ValueError("unexpected compile orchestration")
    return body[len(prefix):]


def needs_rebuild(root: Path, *, manual: bool = False) -> bool:
    if manual:
        return True
    try:
        if digest(build_recipe((root / WORKFLOW).read_text()).encode()) != RECIPE_SHA256:
            return True
        for relative, expected in PINS.items():
            file = root / relative
            if file.is_symlink() or not file.is_file() or digest(file.read_bytes()) != expected:
                return True
        return False
    except (OSError, IndexError, ValueError):
        return True


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"pull_request", "workflow_dispatch"}:
        raise SystemExit("Unsupported workflow event")
    print("rebuild=" + str(needs_rebuild(ROOT, manual=sys.argv[1] == "workflow_dispatch")).lower())
