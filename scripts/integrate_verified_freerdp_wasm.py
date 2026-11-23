#!/usr/bin/env python3
"""Integrate exactly one verified FreeRDP 3.33.1 WASM build into a staging commit.

Run only after the isolated Chromium/Playwright startup + WebSocket proof passes.
The script never deploys, alters Render, changes client releases, or pushes.
It fails closed if provenance, source locks, hashes, sizes, or local assets differ.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import re
import shutil
import sys

SOURCE = "65bcca1913a28cbdd7eb913599f692bd2b707991"
OLD = {
    "sdl-freerdp.js": ("609715445d2dc9f637f386572566b10fa8b3b9f0736f483a1d6a5ed423ee8cb5", 269234),
    "sdl-freerdp.wasm": ("808752fe85bb1d65964d19f4b5d40cf990d1708c437ff0e40ec92f5994d7cf90", 11089855),
}
NEW = {
    "sdl-freerdp.js": ("c7d0a7e20a7b6473c5743892086b00dfb096807b8386adf992ab294867ad8112", 269234),
    "sdl-freerdp.wasm": ("f5cfa907421b47c3ed6acdee329f5ebda7e9279c4a5972e02139dc8e2fe6f315", 11086426),
}
ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "frontend" / "public" / "native-rdp"
ASSET_GATE = ROOT / "frontend" / "scripts" / "checkNativeRdpWasm.mjs"
MANIFEST = ROOT / "SHA256SUMS.txt"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError("STOP: " + message)


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def validate_file(path: Path, sha: str, size: int) -> None:
    require(path.is_file() and not path.is_symlink(), "source missing or symlink: " + path.name)
    require(path.stat().st_size == size and digest(path.read_bytes()) == sha,
            "source identity mismatch: " + path.name)


def parse_manifest() -> dict[str, str]:
    entries = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([a-f0-9]{64})  (.+)", line)
        require(match is not None, "malformed SHA256SUMS line")
        sha, relative = match.groups()
        require(relative not in entries, "duplicate source manifest path")
        entries[relative] = sha
    return entries


def main() -> None:
    require(len(sys.argv) == 2, "usage: integrate_verified_freerdp_wasm.py /path/to/artifact")
    artifact = Path(sys.argv[1]).resolve(strict=True)
    require(artifact.is_dir() and not artifact.is_symlink(), "artifact directory missing")
    require({p.name for p in artifact.iterdir()} ==
            {"sdl-freerdp.js", "sdl-freerdp.wasm", "provenance.json"},
            "unexpected or missing artifact files")
    info = json.loads((artifact / "provenance.json").read_text(encoding="utf-8"))
    require(info.get("freerdp_source_commit") == SOURCE and
            info.get("freerdp_version") == "3.33.1" and
            info.get("emsdk") == "6.0.12", "untrusted FreeRDP provenance")
    require(set(info.get("files", {})) == set(NEW), "untrusted artifact file inventory")

    for name, (sha, size) in NEW.items():
        validate_file(artifact / name, sha, size)
        require(info["files"][name] == {"sha256": sha, "bytes": size},
                "untrusted per-file artifact provenance")
    require((artifact / "sdl-freerdp.wasm").read_bytes()[:4] == b"\x00asm",
            "invalid WebAssembly binary")

    original = json.loads((ASSETS / "provenance.json").read_text(encoding="utf-8"))
    require(original.get("freerdp_source_commit") == SOURCE and
            original.get("freerdp_version") == "3.33.1" and
            original.get("emsdk") == "6.0.12", "unexpected repository FreeRDP source")
    for name, (sha, size) in OLD.items():
        require(original["files"].get(name) == {"sha256": sha, "bytes": size},
                "repository provenance has changed")
        validate_file(ASSETS / name, sha, size)

    contents = ASSET_GATE.read_text(encoding="utf-8")
    for name, (sha, size) in OLD.items():
        line = f'"{name}": {{ sha256: "{sha}", bytes: {size} }}'
        require(contents.count(line) == 1, "unexpected frontend asset source lock: " + name)
        newsha, newsize = NEW[name]
        contents = contents.replace(line, f'"{name}": {{ sha256: "{newsha}", bytes: {newsize} }}')

    entries = parse_manifest()
    paths = [
        "frontend/public/native-rdp/sdl-freerdp.js",
        "frontend/public/native-rdp/sdl-freerdp.wasm",
        "frontend/public/native-rdp/provenance.json",
        "frontend/scripts/checkNativeRdpWasm.mjs",
    ]
    for name in OLD:
        require(entries[f"frontend/public/native-rdp/{name}"] == OLD[name][0],
                "old binary source manifest differs")
    require(entries["frontend/scripts/checkNativeRdpWasm.mjs"] ==
            digest(ASSET_GATE.read_bytes()), "old gate source manifest differs")
    require(entries["frontend/public/native-rdp/provenance.json"] ==
            digest((ASSETS / "provenance.json").read_bytes()), "old provenance manifest differs")
    for item in paths:
        require(item in entries, "required source manifest entry missing")

    # All validation is complete. Write only the four reviewed target paths,
    # followed by the signed repository checksum manifest.
    for name in NEW:
        shutil.copyfile(artifact / name, ASSETS / name)
    (ASSETS / "provenance.json").write_bytes((artifact / "provenance.json").read_bytes())
    ASSET_GATE.write_text(contents, encoding="utf-8")
    for relative in paths:
        entries[relative] = digest((ROOT / relative).read_bytes())
    MANIFEST.write_text(
        "\n".join(f"{value}  {name}" for name, value in sorted(entries.items())) + "\n",
        encoding="utf-8",
    )
    # Validate the entire source freeze after updating the binary.
    for relative, sha in entries.items():
        destination = ROOT / relative
        require(destination.is_file() and digest(destination.read_bytes()) == sha,
                "checksum mismatch in complete source manifest: " + relative)
    for name, (sha, size) in NEW.items():
        validate_file(ASSETS / name, sha, size)
    print("VERIFIED_FREERDP_WASM_INTEGRATED=PASS", flush=True)
    print("SOURCE_COMMIT=" + SOURCE, flush=True)
    print("JS_SHA256=" + NEW["sdl-freerdp.js"][0], flush=True)
    print("WASM_SHA256=" + NEW["sdl-freerdp.wasm"][0], flush=True)
    print("MANIFEST_COMPLETE=PASS", flush=True)
    print("CLIENTFLOW_RELEASE_1248_UNCHANGED=True", flush=True)
    print("RENDER_DEPLOY_UNCHANGED=True", flush=True)


if __name__ == "__main__":
    main()
