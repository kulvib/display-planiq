"""Exact new release identity, fail-closed runtime selection and physical blockers.

This source-staging contract is not publication or physical approval.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_source_1237_is_staged_one_sequence_ahead_of_immutable_1236() -> None:
    assert (ROOT / "client/VERSION").read_text(encoding="utf-8").strip() == "1.3.36"
    source = json.loads((ROOT / "client/release/release-input.json").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "backend/service1/clientflow_release_catalog.json").read_text(encoding="utf-8"))
    assert source == {
        "schema_version": 1,
        "release_sequence": 1237,
        "minimum_ubuntu_lts": "26.04",
        "architecture": "amd64",
        "runtime_python": "3.13.14",
    }
    assert catalog["catalog_sequence"] == 1236
    assert catalog["latest_stable"] == catalog["default_install_version"] == "1.3.35"
    assert len(catalog["releases"]) == 1
    previous = catalog["releases"][0]
    assert previous["release_id"] == "clientflow-1.3.35-seq-1236"
    assert previous["release_sequence"] == 1236
    assert previous["install_modes"] == ["fresh_install"]
    assert previous["installable"] is True
    assert previous["update_allowed"] is False
    assert previous["rollback_allowed"] is False
    assert not any(x["release_sequence"] == 1237 for x in catalog["releases"])


def test_1237_candidate_keeps_guard_and_chrome_regressions() -> None:
    quick = (ROOT / "client/systemd/clientflow-kiosk-quicksettings-guard.service").read_text(encoding="utf-8")
    policy = (ROOT / "client/runtime/clientflow_runtime/kiosk_session_policy.py").read_text(encoding="utf-8")
    acceptance = (ROOT / "client/runtime/clientflow_runtime/post_final_reboot_acceptance.py").read_text(encoding="utf-8")
    assert "AmbientCapabilities=CAP_SETUID CAP_SETGID CAP_SETPCAP" in quick
    assert "NoNewPrivileges=yes" in quick
    assert "ProtectSystem=strict" in quick
    for arg in ('"--bounding-set=-all"', '"--inh-caps=-all"', '"--no-new-privs"'):
        assert arg in policy
    assert "_verify_chrome_process" in acceptance
    assert "CANONICAL_CHROME_EXECUTABLE" in acceptance
    assert "pw_uid" in acceptance
    assert "--remote-debugging-address=127.0.0.1" in acceptance
    assert "--remote-debugging-port=9222" in acceptance
    assert "scripts/tests/test_clientflow_post_final_reboot_acceptance.py" in (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8")
