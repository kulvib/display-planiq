"""63D-48: no shortcuts between GNOME-native, WASM and Guacamole evidence."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "scripts" / "clientflow_63d48_native_reference.py"
GATE = ROOT / "scripts" / "clientflow_63d48_evidence_gate.py"
GUAC = ROOT / "experiments" / "63d48-guacamole" / "compose.offline.yaml"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def valid_run(engine: str, p50: int = 80, p95: int = 180):
    return {
        "engine": engine,
        "source": {"width": 2560, "height": 1080, "scale": 1.0},
        "canvas": {"width": 2560, "height": 1080},
        "method": "high-speed-video",
        "mouse_samples_ms": [p50] * 28 + [p95] * 2,
        "interaction": {
            "pointer": True, "click": True, "drag": True,
            "scroll": True, "keyboard": True,
        },
        "security": {
            "rdp_port_local_only": True, "session_authorized": True,
            "expiry_enforced": True, "secrets_not_logged": True,
            "agent_rollback_verified": True, "trust_boundary_reviewed": True,
        },
        "resource": {
            "cpu_cores": 0.3, "memory_mb": 150, "traffic_mbps": 2.0,
        },
    }


def valid_doc():
    g = load("cf_63d48_gate_ok", GATE)
    return {
        "schema": 1, "client_id": 3, "network_group": "same-lan-20261124",
        "runs": [valid_run(x) for x in g.ENGINES],
    }


def test_compare_requires_end_to_end_evidence_without_automatic_approval():
    gate = load("cf_63d48_gate_a", GATE)
    report = gate.compare(valid_doc())
    assert report["status"] == "COMPARABLE_EVIDENCE"
    assert report["options_meeting_latency_gate"] == list(gate.ENGINES)
    assert report["release_1249_approved"] is False
    assert report["winner_requires_operator_approval"] is True
    assert report["results"][0]["p95_ms"] == 180
    assert report["results"][0]["samples"] == 30


@pytest.mark.parametrize(
    "mutator",
    [
        lambda d: d["runs"].pop(),
        lambda d: d["runs"][0]["canvas"].update(width=1024, height=768),
        lambda d: d["runs"][0].update(method="websocket-first-byte"),
        lambda d: d["runs"][0].update(mouse_samples_ms=[50] * 5),
        lambda d: d["runs"][0]["interaction"].update(keyboard=False),
        lambda d: d["runs"][0]["security"].update(expiry_enforced=False),
        lambda d: d["runs"][0]["security"].update(secrets_not_logged=False),
        lambda d: d["runs"][0]["security"].update(trust_boundary_reviewed=False),
        lambda d: d["runs"][0].update(password="should-never-exist"),
        lambda d: d["runs"][0]["resource"].update(cpu_cores=float("nan")),
        lambda d: d["runs"][2].update(engine="native-freerdp"),
        lambda d: d.update(network_group="untrusted net"),
        lambda d: d.update(client_id=56),
    ],
)
def test_compare_fails_closed_if_unmeasured_or_unsafe(mutator):
    gate = load("cf_63d48_gate_negative", GATE)
    data = valid_doc()
    mutator(data)
    with pytest.raises(gate.EvidenceError):
        gate.compare(data)


def test_bad_latency_gates_all_candidates():
    gate = load("cf_63d48_gate_slow", GATE)
    data = valid_doc()
    for r in data["runs"]:
        r["mouse_samples_ms"] = [450] * 30
    report = gate.compare(data)
    assert report["status"] == "ALL_OPTIONS_FAILED_LATENCY_GATE"
    assert report["options_meeting_latency_gate"] == []
    assert report["release_1249_approved"] is False


def test_native_only_requires_guarded_local_physical_kiosk():
    native = load("cf_63d48_native", NATIVE)
    assert native.HOST == "viborg1-NUC14MNK-B2"
    assert native.RELEASE == "clientflow-1.3.47-seq-1248"
    assert native.DISPLAY_MODE == "2560x1080"
    assert native.MAX_NATIVE_SECONDS <= 30
    source = NATIVE.read_text()
    assert "GUARD_KERNEL_VERIFIED= True" in source
    assert "ROOT_WATCHDOG_VERIFIED= True" in source
    assert "GNOME_RDP_SETTING= true" in source
    assert "RDP_LISTENERS_3389_3398= [3389]" in source
    assert "PILOT_EXPIRED= False" in source
    assert "remaining < seconds + 20" in source
    assert '"/args-from:stdin"' in source
    assert '"/cert:fingerprint:sha256:"' in source
    assert '"/size:" + DISPLAY_MODE' in source
    assert '"-nolisten tcp"' in source
    assert 'stdout=subprocess.DEVNULL' in source
    assert 'stderr=subprocess.DEVNULL' in source
    assert 'start_new_session=True' in source
    assert 'os.killpg' in source
    assert "NO_SCREEN_PIXELS_SAVED" in source
    assert "NATIVE_INPUT_TO_PIXEL_LATENCY" in source
    assert '"/cert:ignore"' not in source
    assert "grdctl" not in source
    assert "gsettings" not in source
    assert "systemctl restart" not in source


def test_native_cli_stays_read_only_on_non_viborg1(monkeypatch):
    native = load("cf_63d48_native_denied", NATIVE)
    monkeypatch.setattr(native.os, "geteuid", lambda: 1000)
    with pytest.raises(native.PreflightError, match="WRONG_HOST_OR_PRIVILEGE"):
        native.checked_target()


def test_guacamole_reference_cannot_publish_ports_or_production_access():
    compose = GUAC.read_text()
    assert "guacamole/guacd@sha256:" in compose
    assert "internal: true" in compose
    assert "no-new-privileges:true" in compose
    assert "read_only: true" in compose
    assert "cap_drop:" in compose
    assert "pids_limit:" in compose
    assert "mem_limit:" in compose
    # Strip comment-only lines before checking effective content.
    active = "\n".join(line.split("#", 1)[0] for line in compose.splitlines())
    for forbidden in (
        "ports:", "privileged:", "network_mode:", "host.docker.internal",
        "PASSWORD", "/var/run/docker.sock", "volumes:",
        "api.display.planiq.dk", "display.planiq.dk",
        "4822:4822", "0.0.0.0",
    ):
        assert forbidden not in active
    assert active.count("expose:") == 1
    assert '"4822"' in active
