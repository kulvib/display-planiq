"""The 1241 source-stage changes source identity, not release or deploy authority."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_exact_1241_source_is_only_one_sequence_ahead_of_frozen_catalog():
    version = _read("client/VERSION").strip()
    source = json.loads(_read("client/release/release-input.json"))
    catalog = json.loads(_read("backend/service1/clientflow_release_catalog.json"))

    assert version == "1.3.40"
    assert source == {
        "schema_version": 1,
        "release_sequence": 1241,
        "minimum_ubuntu_lts": "26.04",
        "architecture": "amd64",
        "runtime_python": "3.13.14",
    }
    assert source["release_sequence"] == catalog["catalog_sequence"] + 1
    assert catalog["catalog_sequence"] == 1240
    assert catalog["latest_stable"] == catalog["default_install_version"] == "1.3.38"
    assert catalog["retention_policy"] == {
        "max_installable_versions": 1,
        "keep_blocked_metadata": False,
    }
    assert len(catalog["releases"]) == 2
    assert all(item["release_sequence"] < 1241 for item in catalog["releases"])
    assert all(item["version"] != "1.3.40" for item in catalog["releases"])

    stable, failed_pilot = catalog["releases"]
    assert stable["release_id"] == "clientflow-1.3.38-seq-1239"
    assert stable["status"] == "stable"
    assert stable["installable"] is True
    assert stable["install_modes"] == ["fresh_install"]
    assert stable["update_allowed"] is False
    assert stable["rollback_allowed"] is False
    assert failed_pilot["release_id"] == "clientflow-1.3.39-seq-1240"
    assert failed_pilot["release_sequence"] == 1240
    assert failed_pilot["status"] == "supported"
    assert failed_pilot["installable"] is False
    assert failed_pilot["install_modes"] == ["in_place_update"]
    assert failed_pilot["rollback_allowed"] is False
    assert failed_pilot["min_current_version"] == failed_pilot["max_current_version"] == "1.3.38"


def test_candidate_keeps_security_and_kiosk_contracts_staged_for_physical_proof():
    controller = _read("client/systemd/clientflow-update-controller.service")
    bridge = _read("scripts/clientflow_1338_controller_bridge.sh")
    timer = _read("client/systemd/clientflow-kiosk-session-policy.timer")
    lockdown = _read("client/runtime/clientflow_runtime/kiosk_lockdown.py")
    policy = _read("client/runtime/clientflow_runtime/kiosk_session_policy.py")
    transaction = _read("client/release/lib/clientflow_release/transaction.py")
    power = _read("backend/service1/system_control.py")

    assert "ProtectHome=tmpfs" in controller
    assert "BindPaths=/home/clientflow-kiosk" in controller
    assert "ProtectHome=yes" not in [line.strip() for line in controller.splitlines()]
    assert "--confirm-clientflow-1338" in bridge
    assert "BRIDGE_DRY_RUN_ONLY=PASS" in bridge
    assert "OnUnitActiveSec=1min" in timer
    assert "CRITICAL_KIOSK_SETTINGS" in policy
    assert "KIOSK_DISPLAY_AWAKE_BASELINE" in lockdown
    assert "automatic_rollback_failed" in transaction
    assert "recover_failed_update" in transaction
    assert "reboot_completed" in power


def test_stage_requires_human_approval_and_preserves_all_heidi1_gates():
    stage = _read("CLIENTFLOW_1.3.40_1241_SOURCE_STAGE.md")
    for token in (
        "STAGED SOURCE IDENTITY ONLY", "NOT approved", "NOT published",
        "NOT catalog-promoted", "1.3.40", "1241", "source SHA",
        "exact-source CI", "reproducible", "immutable", "PostgreSQL",
        "in_place_update", "Heidi1", "1.3.38", "1.3.39",
        "Control Room", "Clientlist", "Chrome/Wayland", "GUI", "Mutter",
        "lockdown", "popups", "Remote Desktop", "Terminal", "Livestream",
        "rollback", "health", "cookie", "clipboard", "calendar",
        "no Linux reinstall", "BindPaths", "source-stage", "anti-rollback",
    ):
        assert token in stage, token
    assert "Do not auto-activate" in stage
