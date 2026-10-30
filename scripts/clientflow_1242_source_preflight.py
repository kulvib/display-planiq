#!/usr/bin/env python3
"""Read-only ClientFlow 1.3.41/1242 source staging readiness check.

This is deliberately NOT a candidate builder, signing-key tool, publication
approval, production check, or replacement for the immutable release builder.
Never read, print, generate, or mutate the private rollback signing key.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def inspect_source(repo: Path) -> dict:
    checks: list[dict[str, object]] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    try:
        version = (repo / "client/VERSION").read_text(encoding="utf-8").strip()
        record("release_version", version == "1.3.41", "Forventet ClientFlow 1.3.41")
    except (OSError, UnicodeError):
        record("release_version", False, "ClientFlow-versionen mangler eller kan ikke læses")

    try:
        release_input = json.loads((repo / "client/release/release-input.json").read_text(encoding="utf-8"))
        sequence = release_input.get("release_sequence") if isinstance(release_input, dict) else None
        record("release_sequence", type(sequence) is int and sequence == 1242, "Forventet sekvens 1242")
    except (OSError, UnicodeError, ValueError):
        record("release_sequence", False, "Release-input mangler eller er ugyldigt")

    try:
        # Use the SAME fail-closed validator as the immutable release builder.
        for source_path in (ROOT / "backend", ROOT / "client/release/lib"):
            if str(source_path) not in sys.path:
                sys.path.insert(0, str(source_path))
        from clientflow_release.rollback_trust_build import validate_release_rollback_trust

        validate_release_rollback_trust(repo, 1242)
        # This is only an observation of the *source* trust mode; never infer
        # presence of a private key or readiness of the backend signer.
        trust = json.loads((repo / "client/release/rollback-trust.json").read_text(encoding="utf-8"))
        mode = "signed" if trust["enabled"] is True else "disabled"
    except (ImportError, OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        # No key bytes, raw configuration, environment variables, or payloads.
        record("manual_rollback_safety_mode", False, f"Build-gate afviser rollback-mode: {type(exc).__name__}")
        mode = "invalid"
    else:
        if mode == "disabled":
            record("manual_rollback_safety_mode", True, "Manuel rollback er blokeret fra sekvens 1242; automatisk recovery bevares")
        else:
            record("manual_rollback_safety_mode", True, "Signeret manuel rollback kræver separat signer- og pilotgodkendelse")

    passed = all(bool(c["passed"]) for c in checks)
    return {
        "target": "clientflow-1.3.41-seq-1242",
        "phase": "source_stage_only",
        "source_stage_ready": passed,
        "publish_authorized": False,
        "activation_authorized": False,
        "manual_rollback_mode": mode,
        "requires_operator_signer_identity_verification": mode == "signed",
        "requires_physical_pilot": True,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT, help="Repository root; read-only")
    args = parser.parse_args(argv)
    result = inspect_source(args.repo_root.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["source_stage_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
