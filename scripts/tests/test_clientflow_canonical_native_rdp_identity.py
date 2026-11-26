"""Host-free regression of the immutable generic RDP helper bundle."""
import hashlib
import importlib
from pathlib import Path
import sys
import time
import types
import uuid
import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "canonical_rdp_identity_test"
source = ROOT / "client/native-rdp-root"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(source)]
sys.modules[PACKAGE] = package
guard = importlib.import_module(PACKAGE + ".clientflow_63d29_persistent_rdp_guard")
proof = importlib.import_module(PACKAGE + ".clientflow_63d53_rdp_proof")
life = importlib.import_module(PACKAGE + ".clientflow_63d53_rdp_lifecycle")
runner = importlib.import_module(PACKAGE + ".clientflow_63d30_local_rdp_pilot")
broker = importlib.import_module(PACKAGE + ".clientflow_63d49_autologin_broker")


@pytest.mark.parametrize("client_id", [3, 37, 1001])
def test_canonical_identity_parser(client_id):
    assert guard.parse_client_id({"schema_version": 1, "client_id": client_id,
                                 "kiosk_user": "clientflow-kiosk"}) == client_id


@pytest.mark.parametrize("mutation", [
    {"client_id": True}, {"client_id": 0}, {"client_id": "37"},
    {"schema_version": True}, {"kiosk_user": "root"}, {"CLIENT_ID": 3},
])
def test_malformed_identity_is_denied(mutation):
    value = {"schema_version": 1, "client_id": 37, "kiosk_user": "clientflow-kiosk"}
    value.update(mutation)
    with pytest.raises(RuntimeError):
        guard.parse_client_id(value)


@pytest.fixture
def bound(monkeypatch, tmp_path):
    boot, session = str(uuid.uuid4()), str(uuid.uuid4())
    host = "another-client"
    monkeypatch.setattr(guard, "local_client_id", lambda: 37)
    monkeypatch.setattr(proof, "EXPECTED_CLIENT_ID", 37)
    monkeypatch.setattr(proof.socket, "gethostname", lambda: host)
    boot_path = tmp_path / "boot"
    boot_path.write_text(boot)
    monkeypatch.setattr(proof, "BOOT", boot_path)
    monkeypatch.setattr(proof, "process_start", lambda pid: "owner-start")
    now, mono = time.time(), time.monotonic()
    evidence = {"schema": 1, "client_id": 37, "boot_id": boot, "session_id": session,
                "pid": 42, "process_start": "owner-start", "fingerprint": "a"*64,
                "expires_wall": now+15, "expires_mono": mono+15}
    grant = {"schema": 1, "client_id": 37, "hostname": host, "boot_id": boot,
             "expires_wall": now+90, "expires_mono": mono+90}
    state = {"phase": "63D-30", "client_id": 37, "hostname": host, "boot_id": boot,
             "deadline_wall": now+90, "deadline_mono": mono+90}
    records = {proof.PROOF: evidence, proof.APPROVAL: grant, proof.STATE: state}
    monkeypatch.setattr(proof, "root_json", lambda path, mode: records[path])
    return session, evidence, grant, state


def test_nonpilot_session_proof_and_identity_changes(bound, monkeypatch):
    session, evidence, grant, state = bound
    assert proof.authorize(session)[1] == "a"*64
    for record, field, invalid in ((evidence, "client_id", 3), (grant, "client_id", 3),
                                   (state, "client_id", True), (grant, "hostname", "elsewhere"),
                                   (state, "boot_id", "other"), (evidence, "process_start", "stale")):
        old = record[field]
        record[field] = invalid
        with pytest.raises(proof.ProofDenied):
            proof.authorize(session)
        record[field] = old
    monkeypatch.setattr(guard, "local_client_id", lambda: 38)
    with pytest.raises(proof.ProofDenied):
        proof.authorize(session)


def test_root_entrypoint_binding_required(monkeypatch):
    monkeypatch.setattr(guard, "local_client_id", lambda: 37)
    monkeypatch.setattr(proof, "EXPECTED_CLIENT_ID", None)
    with pytest.raises(proof.ProofDenied):
        proof.bound_client_id()


def test_canonical_internal_pins_match_and_historic_sources_are_unchanged():
    for name, digest in life.PINNED.items():
        assert hashlib.sha256((source / name).read_bytes()).hexdigest() == digest
    assert runner.EXPECTED_GUARD_SHA256 == life.PINNED[life.GUARD] == broker.GNOME_GUARD_SHA256
    assert broker.GNOME_RUNNER_SHA256 == life.PINNED[life.RUNNER]
    assert hashlib.sha256((ROOT / "scripts" / life.GUARD).read_bytes()).hexdigest() == "709a5d9b1eba3364dfd2ac21f4e24525b0dc3261236456a9127aac7cfd54c000"
    assert hashlib.sha256((ROOT / "scripts" / life.RUNNER).read_bytes()).hexdigest() == "78972f7c7173a4894abc22d4518b1fc4d3189c76e30dd463715af03ef069af69"
    historical = importlib.import_module("scripts.clientflow_63d29_persistent_rdp_guard")
    assert guard.RULES == historical.RULES and guard.DROPIN == historical.DROPIN


@pytest.mark.parametrize("failure", ["identity_changed", "identity_missing", "hostname_changed", "deadline_nan"])
def test_watchdog_cleanup_does_not_depend_on_live_enrollment(monkeypatch, failure):
    state = {"phase": "63D-30", "client_id": 37, "hostname": "client-37",
             "kiosk_uid": 1001, "boot_id": "boot", "baseline": runner.EXPECTED_BASE,
             "deadline_wall": time.time() + 60, "deadline_mono": time.monotonic() + 60}
    monkeypatch.setattr(runner, "cleanup_state", lambda: state)
    monkeypatch.setattr(runner, "boot_id", lambda: "boot")
    monkeypatch.setattr(runner.socket, "gethostname", lambda: "client-37")
    monkeypatch.setattr(runner.pwd, "getpwnam", lambda _: types.SimpleNamespace(pw_uid=1001))
    monkeypatch.setattr(guard, "local_client_id", lambda: 37)
    monkeypatch.setattr(guard, "guard_verified", lambda: True)
    if failure == "identity_changed":
        monkeypatch.setattr(guard, "local_client_id", lambda: 38)
    elif failure == "identity_missing":
        def missing():
            raise FileNotFoundError("identity")
        monkeypatch.setattr(guard, "local_client_id", missing)
    elif failure == "hostname_changed":
        monkeypatch.setattr(runner.socket, "gethostname", lambda: "renamed")
    else:
        state["deadline_wall"] = float("nan")
    calls = []
    monkeypatch.setattr(runner, "stop", lambda: calls.append("stop"))
    runner.tick()
    assert calls == ["stop"]
    if failure != "deadline_nan":
        with pytest.raises(RuntimeError, match="kun sikker oprydning"):
            runner.state_load()


def test_shutdown_uses_owned_kiosk_uid_and_never_admits_new_identity(monkeypatch):
    state = {"kiosk_uid": 1001, "baseline": runner.EXPECTED_BASE}
    monkeypatch.setattr(runner, "cleanup_state", lambda: state)
    monkeypatch.setattr(runner, "_local_kiosk", lambda: (1002, Path("/run/user/1002")))
    monkeypatch.setattr(runner, "kiosk_ok", lambda *a, **k: pytest.fail("foreign kiosk mutation"))
    monkeypatch.setattr(guard, "remove_guard", lambda *a: pytest.fail("firewall mutation"))
    with pytest.raises(RuntimeError, match="Kiosk UID ændret"):
        runner.stop()


def test_cleanup_revokes_owned_attestation_only(tmp_path, monkeypatch):
    import json
    # CI runs unprivileged; isolate only the explicit root ownership check.
    marker = tmp_path / "grant"
    data = {"client_id": 37, "boot_id": "boot", "hostname": "client-37"}
    marker.write_text(json.dumps({"schema": 1, **data}))
    marker.chmod(0o644)
    if marker.stat().st_uid != 0 or tmp_path.stat().st_uid != 0:
        # Never monkeypatch global os.stat or lower production file checks.
        with pytest.raises(RuntimeError, match="Ukendt RDP attestation"):
            runner._remove_owned_attestation(marker, data, 0o644, hostname=True)
        assert marker.exists()
        return
    foreign = dict(data, client_id=38)
    with pytest.raises(RuntimeError, match="Fremmed RDP attestation"):
        runner._remove_owned_attestation(marker, foreign, 0o644, hostname=True)
    assert marker.exists()
    runner._remove_owned_attestation(marker, data, 0o644, hostname=True)
    assert not marker.exists()
