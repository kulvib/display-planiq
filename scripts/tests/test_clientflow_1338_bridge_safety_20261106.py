"""Fail-closed source gates for the one-time 1.3.38 host controller bridge."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def test_bridge_is_attended_non_destructive_and_has_no_silent_overwrite():
    script = ROOT / "scripts/clientflow_1338_controller_bridge.sh"
    s = script.read_text(encoding="utf-8")
    assert subprocess.run(["bash", "-n", str(script)], check=False).returncode == 0
    for required in (
        "--check", "--confirm-clientflow-1338", "--confirm-backend-idle",
        "BRIDGE_DRY_RUN_ONLY=PASS", "CONTROLLER_DEFINITION_DRIFT",
        "BRIDGE_UPDATER_TIMER_MUST_BE_STOPPED", "BRIDGE_CONTROLLER_MUST_BE_IDLE",
        "BRIDGE_LOADED_POLICY_MISMATCH", "BRIDGE_UNEXPECTED_LOADED_DROPIN",
        "BRIDGE_EFFECTIVE_SYSTEMD_CONFIGURATION_INVALID", "NeedDaemonReload",
        "ProtectHome=tmpfs", "BindPaths=/home/clientflow-kiosk",
        'ln -- "$TMP" "$DROPIN"',
    ):
        assert required in s
    assert "mv -n" not in s.replace("unlike mv -n", "")
    assert 'state.get(\'activation_intent\') is None' in s
    assert 'state.get(\'previous_release_id\') is None' in s
    assert 'state.get(\'highest_release_sequence\'' in s
    assert "systemctl daemon-reload" in s
    assert "systemctl reboot" not in s
    assert "/var/lib/clientflow/release/state.json" in s
    assert "/opt/clientflow/active/client-runtime/systemd/" in s


def test_recovery_attestation_cannot_mutate_local_state_or_services():
    script = ROOT / "scripts/clientflow_local_recovery_attestation.sh"
    s = script.read_text(encoding="utf-8")
    assert subprocess.run(["bash", "-n", str(script)], check=False).returncode == 0
    for required in (
        "activation_intent", "previous_release_id", "automatic_rollback_failed",
        "automatic_rollback_completed", "NeedDaemonReload", "clientflow.target",
        "clientflow-status-agent.service", "clientflow-display-runtime.service",
        "RECOVERY_ATTESTATION=PASS",
    ):
        assert required in s
    for forbidden in ("systemctl restart", "systemctl daemon-reload", "systemctl reboot", "write_text(", "save_state("):
        assert forbidden not in s
