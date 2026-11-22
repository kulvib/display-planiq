"""63D-39: source-only negative tests for non-executing CI .deb inventory."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import clientflow_63d39_rfb_ci_audit as audit


def fake_archives(tmp_path: Path) -> dict[str, Path]:
    paths = {}
    for name in audit.PACKAGES:
        path = tmp_path / (name + "_candidate_amd64.deb")
        path.write_bytes((name + "-test-package").encode())
        paths[name] = path
    return paths


def metadata(paths: dict[str, Path], versions=None):
    versions = versions or {}
    by_name = {str(path): name for name, path in paths.items()}
    def control(path, field):
        name = by_name[str(path)]
        return {
            "Package": name,
            "Version": versions.get(
                name, "0.9.15+dfsg-3ubuntu0.2"
                if name.startswith("libvnc") else
                ("0.9.17-2" if name == "x11vnc" else "1.15.0+dfsg-2build1")
            ),
            "Architecture": "amd64",
        }[field]
    return control


def test_archives_are_evidence_not_approval(tmp_path):
    paths = fake_archives(tmp_path)
    result = audit.inventory(tmp_path, control=metadata(paths), compare=lambda _: True)
    assert result["audit_evidence_pass"]
    assert result["archive_versions_and_sha256"]["x11vnc"]["sha256"] == (
        hashlib.sha256(paths["x11vnc"].read_bytes()).hexdigest()
    )
    for key in ("producer_approved", "activation_permitted", "browser_rdp_proven",
                "package_installed", "package_executed"):
        assert result[key] is False


@pytest.mark.parametrize("missing", audit.PACKAGES)
def test_missing_package_denied(tmp_path, missing):
    paths = fake_archives(tmp_path)
    paths[missing].unlink()
    with pytest.raises(audit.AuditError):
        audit.inventory(tmp_path, control=metadata(paths), compare=lambda _: True)


def test_duplicate_or_extra_archive_denied(tmp_path):
    paths = fake_archives(tmp_path)
    (tmp_path / "x11vnc_other_amd64.deb").write_bytes(b"extra")
    with pytest.raises(audit.AuditError):
        audit.inventory(tmp_path, control=metadata(paths), compare=lambda _: True)


def test_symlink_archive_denied(tmp_path):
    paths = fake_archives(tmp_path)
    paths["x11vnc"].unlink()
    paths["x11vnc"].symlink_to(paths["libvncserver1"])
    with pytest.raises(audit.AuditError):
        audit.inventory(tmp_path, control=metadata(paths), compare=lambda _: True)


def test_metadata_mismatch_denied(tmp_path):
    paths = fake_archives(tmp_path)
    control = metadata(paths)
    def wrong(path, field):
        return "arm64" if field == "Architecture" else control(path, field)
    with pytest.raises(audit.AuditError):
        audit.inventory(tmp_path, control=wrong, compare=lambda _: True)


def test_malicious_version_denied_without_compare(tmp_path):
    paths = fake_archives(tmp_path)
    called = []
    control = metadata(paths, {"libvncserver1": "1;rm -rf /"})
    with pytest.raises(audit.AuditError):
        audit.inventory(
            tmp_path, control=control, compare=lambda v: called.append(v) or True,
        )
    assert not called


def test_unpatched_library_denied(tmp_path):
    paths = fake_archives(tmp_path)
    with pytest.raises(audit.AuditError, match="USN-8494"):
        audit.inventory(tmp_path, control=metadata(paths), compare=lambda _: False)


def test_ci_host_identity_enforced():
    env = {"CI": "true", "GITHUB_ACTIONS": "true",
           "GITHUB_REPOSITORY": "kulvib/display-planiq"}
    release = 'ID=ubuntu\nVERSION_ID="26.04"\n'
    assert audit.ci_host_ok(env, release, 1000)
    assert not audit.ci_host_ok(dict(env, CI="false"), release, 1000)
    assert not audit.ci_host_ok(dict(env, GITHUB_REPOSITORY="other/repo"), release, 1000)
    assert not audit.ci_host_ok(env, release, 0)
    assert not audit.ci_host_ok(env, 'ID=ubuntu\nVERSION_ID="24.04"\n', 1000)


def test_only_dpkg_control_inspection(monkeypatch, tmp_path):
    commands = []
    class Done:
        returncode = 0
        stdout = "x11vnc\n"
    def run(args, **kwargs):
        commands.append(args)
        return Done()
    monkeypatch.setattr(audit.subprocess, "run", run)
    assert audit.read_control(tmp_path / "fake.deb", "Package") == "x11vnc"
    assert commands == [("dpkg-deb", "-f", str(tmp_path / "fake.deb"), "Package")]
    with pytest.raises(audit.AuditError):
        audit.read_control(tmp_path / "fake.deb", "Maintainer")
    assert len(commands) == 1


def test_comparison_uses_dpkg_not_lexical_order(monkeypatch):
    commands = []
    class Done:
        returncode = 0
    def run(args, **kwargs):
        commands.append(args)
        return Done()
    monkeypatch.setattr(audit.subprocess, "run", run)
    assert audit.compare_version("1:0.9.15+dfsg-3ubuntu0.2")
    assert commands == [(
        "dpkg", "--compare-versions",
        "1:0.9.15+dfsg-3ubuntu0.2", "ge", audit.SECURITY_BASELINE,
    )]
    with pytest.raises(audit.AuditError):
        audit.compare_version("2;evil")
