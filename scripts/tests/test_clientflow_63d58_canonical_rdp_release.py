"""Native RDP packaging and fail-closed release transition tests."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT / "backend", ROOT / "client/release/lib"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
from clientflow_release import builder, transaction

SPEC = importlib.util.spec_from_file_location("native_rdp_entry", ROOT / "client/libexec/native-rdp/entrypoint.py")
assert SPEC and SPEC.loader
entry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(entry)


def test_actual_release_payload_contains_only_pinned_root_helpers(tmp_path):
    updater = tmp_path / "updater.pyz"
    updater.write_bytes(b"test")
    payload = tmp_path / "payload.tar"
    builder._create_payload(ROOT, payload, version="9.9.9", epoch=1700000000,
                            runtime_inputs=None, updater_pyz=updater)
    prefix = "clientflow-9.9.9/client-runtime/libexec/native-rdp/"
    with tarfile.open(payload) as tar:
        actual = {m.name.removeprefix(prefix + "scripts/") for m in tar.getmembers()
                  if m.isfile() and m.name.startswith(prefix + "scripts/")}
        assert actual == set(entry.PINS)
        assert set(builder.NATIVE_RDP_ROOT_SOURCES) == actual - {"__init__.py"}
        for name, expected in entry.PINS.items():
            member = tar.getmember(prefix + "scripts/" + name)
            assert member.uid == 0 and member.mode & 0o022 == 0
            assert hashlib.sha256(tar.extractfile(member).read()).hexdigest() == expected
        for name in (*transaction._NATIVE_RDP_SOCKET_UNITS, *transaction._NATIVE_RDP_TEMPLATES):
            text = tar.extractfile("clientflow-9.9.9/client-runtime/systemd/" + name).read().decode()
            if name.endswith("@.service"):
                assert "/opt/clientflow/active/client-runtime/libexec/native-rdp/entrypoint.py" in text
                assert "/usr/local/libexec/clientflow/native-rdp-pilot" not in text
            else:
                assert "Accept=yes" in text and "WantedBy=clientflow.target" in text


def test_generic_removal_preserves_physical_guard(tmp_path):
    layout = transaction.Layout(tmp_path)
    marker = layout.path(transaction._NATIVE_RDP_PHYSICAL_PATHS[0])
    marker.mkdir(parents=True)
    unit = layout.unit_root / "clientflow-63d29-rdp-guard.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("guard")
    with pytest.raises(transaction.TransactionError, match="preserve guard"):
        transaction._remove_managed_units(layout)
    assert unit.read_text() == "guard"


def test_quiesce_admission_then_agent_without_killing_templates(tmp_path, monkeypatch):
    layout = transaction.Layout(tmp_path)
    layout.unit_root.mkdir(parents=True)
    for name in (*transaction._NATIVE_RDP_SOCKET_UNITS, *transaction._NATIVE_RDP_TEMPLATES,
                 "clientflow-remote-desktop-agent.service"):
        (layout.unit_root / name).write_text("")
    calls = []
    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "inactive\n" if "show" in cmd else "", "")
    monkeypatch.setattr(transaction, "_run", run)
    transaction._quiesce_native_rdp(layout)
    assert calls[0][-1] == "clientflow-rdp-lifecycle.socket"
    assert calls[1][-1] == "clientflow-remote-desktop-agent.service"
    assert not transaction._NATIVE_RDP_TEMPLATES.intersection(transaction._runtime_unit_names(layout))
    assert any("list-units" in command for command in calls)


def test_previous_pilot_blocks_swap_before_mutation(tmp_path, monkeypatch):
    layout = transaction.Layout(tmp_path)
    marker = layout.path(transaction._NATIVE_RDP_PHYSICAL_PATHS[0])
    marker.mkdir(parents=True)
    monkeypatch.setattr(transaction, "_run", lambda *a, **k: pytest.fail("unsafe mutation"))
    with pytest.raises(transaction.TransactionError, match="Previous RDP pilot"):
        transaction._quiesce_native_rdp(layout)


@pytest.mark.parametrize("name", transaction._NATIVE_RDP_TEMPORARY_PATHS)
@pytest.mark.parametrize("dangling", [False, True])
def test_orphaned_temporary_sources_block_activation_without_mutation(tmp_path, monkeypatch, name, dangling):
    layout = transaction.Layout(tmp_path)
    path = layout.path(name)
    path.parent.mkdir(parents=True)
    if dangling:
        path.symlink_to(tmp_path / "missing")
    else:
        path.mkdir()
    monkeypatch.setattr(transaction, "_run", lambda *a, **k: pytest.fail("unsafe mutation"))
    with pytest.raises(transaction.TransactionError, match="Temporary RDP source"):
        transaction._quiesce_native_rdp(layout)
    assert path.is_symlink() if dangling else path.is_dir()


def test_passive_operator_receipt_does_not_block_canonical_activation(tmp_path):
    layout = transaction.Layout(tmp_path)
    receipt = layout.path("/run/clientflow-63d54-operator/operator.py")
    receipt.parent.mkdir(parents=True)
    receipt.write_text("passive rollback receipt")
    transaction._assert_no_temporary_rdp_override(layout)


def test_rebuilt_runtime_contains_exact_native_rdp_modules(tmp_path):
    wheel = tmp_path / "clientflow_runtime-test.whl"
    modules = builder.NATIVE_RDP_RUNTIME_MODULES

    def write_wheel(*, missing=None, changed=None, duplicate=None):
        with zipfile.ZipFile(wheel, "w") as archive:
            for name in modules:
                if name == missing:
                    continue
                source = ROOT / "client/runtime/clientflow_runtime" / name
                data = source.read_bytes()
                if name == changed:
                    data = bytes([data[0] ^ 1]) + data[1:]
                member = "clientflow_runtime/" + name
                archive.writestr(member, data)
                if name == duplicate:
                    with pytest.warns(UserWarning, match="Duplicate name"):
                        archive.writestr(member, data)

    write_wheel()
    builder.validate_native_rdp_wheel(ROOT, wheel)
    for scenario in ("missing", "changed", "duplicate"):
        write_wheel(**{scenario: modules[-1]})
        with pytest.raises(ValueError, match="Native RDP runtime wheel"):
            builder.validate_native_rdp_wheel(ROOT, wheel)


def test_build_rejects_mismatched_root_helper_before_packaging(tmp_path):
    import shutil
    repo = tmp_path / "repo"
    for name in builder.NATIVE_RDP_ROOT_SOURCES:
        target = repo / "scripts" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "scripts" / name, target)
    for name in ("entrypoint.py", "scripts/__init__.py"):
        target = repo / "client/libexec/native-rdp" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "client/libexec/native-rdp" / name, target)
    builder._validate_native_rdp_root_pins(repo)
    helper = repo / "scripts" / builder.NATIVE_RDP_ROOT_SOURCES[0]
    helper.write_bytes(helper.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="root helper pin mismatch"):
        builder._validate_native_rdp_root_pins(repo)


def test_livestream_runtime_wheel_exact_members(tmp_path):
    wheel = tmp_path / "clientflow_runtime-test.whl"
    modules = builder.LIVESTREAM_RUNTIME_MODULES

    def write_wheel(*, missing=None, changed=None, duplicate=None, symlink=None):
        with zipfile.ZipFile(wheel, "w") as archive:
            for name in modules:
                if name == missing:
                    continue
                data = (ROOT / "client/runtime/clientflow_runtime" / name).read_bytes()
                member = "clientflow_runtime/" + name
                if name == changed:
                    data = b"x" + data[1:]
                if name == symlink:
                    info = zipfile.ZipInfo(member)
                    info.create_system = 3
                    info.external_attr = 0o120777 << 16
                    archive.writestr(info, data)
                else:
                    archive.writestr(member, data)
                if name == duplicate:
                    with pytest.warns(UserWarning, match="Duplicate name"):
                        archive.writestr(member, data)

    write_wheel()
    builder.validate_livestream_wheel(ROOT, wheel)
    for scenario in ("missing", "changed", "duplicate", "symlink"):
        write_wheel(**{scenario: "livestream_fmp4_capture.py"})
        with pytest.raises(ValueError, match="Livestream runtime wheel"):
            builder.validate_livestream_wheel(ROOT, wheel)


@pytest.mark.parametrize("relative", (
    *transaction._TEMPORARY_LIVESTREAM_PATHS,
    "/run/systemd/system/clientflow-livestream-producer.service.d/63d77-hls.conf",
    "/run/systemd/system/clientflow-livestream-uploader.service.d/63d77-hls.conf",
    "/etc/systemd/system/clientflow-livestream-uploader.service.d/63d77-hls.conf",
    "/run/clientflow-63d54-operator/shadow",
))
def test_temporary_media_blocks_before_activation_intent_or_target_disable(tmp_path, monkeypatch, relative):
    layout = transaction.Layout(tmp_path)
    marker = layout.path(relative)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.symlink_to(tmp_path / "missing")
    previous = "clientflow-1.3.47-seq-1248"
    target = "clientflow-1.4.0-seq-1250"
    state = {"installed": {target: {}}, "active_release_id": previous}
    monkeypatch.setattr(transaction, "_read_active_release_id", lambda _: previous)
    monkeypatch.setattr(transaction, "_activation_intent", lambda *a, **k: pytest.fail("intent mutated"))
    monkeypatch.setattr(transaction, "_disable_target", lambda *a, **k: pytest.fail("target disabled"))
    with pytest.raises(transaction.TransactionError, match="Temporary (RDP|Livestream)"):
        transaction._activate_release(layout, state, target, "test")
    assert marker.is_symlink()


def test_livestream_dropin_directory_symlink_is_rejected(tmp_path):
    layout = transaction.Layout(tmp_path)
    folder = layout.path("/run/systemd/system/clientflow-livestream-producer.service.d")
    folder.parent.mkdir(parents=True)
    folder.symlink_to(tmp_path / "missing")
    with pytest.raises(transaction.TransactionError, match="Temporary Livestream override"):
        transaction._assert_no_temporary_livestream_override(layout)


def _installed_rdp_identity(root, client_id=37):
    import json
    from clientflow_release import transaction as txn
    release_id = "clientflow-1.4.0-seq-1250"
    layout = txn.Layout(root)
    release = layout.releases / release_id
    release.mkdir(parents=True)
    layout.state_root.mkdir(parents=True)
    layout.lock_file.touch(mode=0o600)
    identity_dir = root / "etc/clientflow"
    identity_dir.mkdir(parents=True)
    def write(path, value, mode=0o600):
        path.write_text(json.dumps(value))
        path.chmod(mode)
    write(identity_dir / "identity.json", {"schema_version": 1, "client_id": client_id,
                                         "kiosk_user": "clientflow-kiosk"})
    manifest = {"release_id": release_id, "version": "1.4.0", "release_sequence": 1250,
                "release_approval": {"reference": "fixture-approved", "candidate_sha256": "b"*64},
                "source": {"commit": "c"*40}}
    write(release / "release-manifest.json", manifest, 0o444)
    write(release / "release-ready.json", {"release_id": release_id, "version": "1.4.0",
                                          "release_sequence": 1250}, 0o444)
    state = txn._initial_state()
    state.update(active_release_id=release_id, highest_release_sequence=1250)
    state["installed"][release_id] = {"version": "1.4.0", "release_sequence": 1250,
        "activated_at": "fixture", "bundle_sha256": "a"*64, "bundle_size": 100,
        "release_approval_reference": "fixture-approved", "release_candidate_sha256": "b"*64,
        "source_commit": "c"*40, "manifest_sha256": txn._manifest_digest(manifest)}
    txn.save_state(layout, state)
    layout.active.symlink_to(release)
    return layout, release, state


@pytest.mark.parametrize("client_id", [3, 37, 1001])
def test_root_installed_identity_is_not_hostname_or_pilot_id_bound(tmp_path, client_id):
    _, release, _ = _installed_rdp_identity(tmp_path, client_id)
    assert entry.verify_installed_identity(release, root=tmp_path) == client_id


@pytest.mark.parametrize("failure", ["wrong_identity", "writable_identity", "symlink_identity",
                                      "uncommitted", "staged", "wrong_manifest", "maintenance",
                                      "missing_lock", "active_mismatch", "wrong_bundle"])
def test_root_installed_identity_fails_closed(tmp_path, failure):
    import json
    from clientflow_release import transaction as txn
    layout, release, state = _installed_rdp_identity(tmp_path)
    identity = tmp_path / "etc/clientflow/identity.json"
    if failure == "wrong_identity":
        identity.write_text(json.dumps({"schema_version": 1, "client_id": 37,
                                        "CLIENT_ID": 3, "kiosk_user": "clientflow-kiosk"}))
    elif failure == "writable_identity":
        identity.chmod(0o666)
    elif failure == "symlink_identity":
        original = identity.with_name("original.json")
        identity.rename(original)
        identity.symlink_to(original)
    elif failure == "uncommitted":
        state["activation_intent"] = {"release_id": release.name}
    elif failure == "staged":
        state["staged_release_id"] = "clientflow-1.4.1-seq-1251"
    elif failure == "wrong_manifest":
        path = release / "release-manifest.json"
        value = json.loads(path.read_text())
        value["source"]["commit"] = "d"*40
        path.unlink()
        path.write_text(json.dumps(value))
        path.chmod(0o444)
    elif failure == "maintenance":
        marker = layout.state_root.parent / "install-coordinator/state.json"
        marker.parent.mkdir()
        marker.write_text("{}")
    elif failure == "missing_lock":
        layout.lock_file.unlink()
    elif failure == "active_mismatch":
        layout.active.unlink()
        layout.active.symlink_to(layout.releases / "nonexistent")
    elif failure == "wrong_bundle":
        state["installed"][release.name]["bundle_sha256"] = "unknown"
    txn.save_state(layout, state)
    with pytest.raises((RuntimeError, OSError)):
        entry.verify_installed_identity(release, root=tmp_path)


def test_root_installed_identity_does_not_wait_for_active_transaction(tmp_path):
    import fcntl
    layout, release, _ = _installed_rdp_identity(tmp_path)
    with layout.lock_file.open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            entry.verify_installed_identity(release, root=tmp_path)
