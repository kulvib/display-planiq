"""Regression: an immutable release must retain an executable transaction wrapper.

This is checked against the *actual payload tar*, not merely a source file's
mode. ZIP downloads and Git checkouts are not trusted as executable-bit input.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import stat
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT / "backend", ROOT / "client/release/lib"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from clientflow_release import builder, transaction  # noqa: E402

WRAPPER = "release/bin/clientflow-release-transaction"
VERSION = "9.9.9"
PAYLOAD_ROOT = f"clientflow-{VERSION}"


def test_transaction_wrapper_mode_is_independent_of_source_git_or_zip_mode(tmp_path):
    source = tmp_path / "clientflow-release-transaction"
    source.write_text("#!/opt/clientflow/active/runtime/bin/python\n", encoding="utf-8")

    for mode in (0o644, 0o444, 0o755):
        source.chmod(mode)
        assert builder._payload_source_mode(
            source, PurePosixPath(PAYLOAD_ROOT) / WRAPPER
        ) == 0o755

    # Only known executables get upgraded; ordinary release files stay read-only.
    source.chmod(0o644)
    assert builder._payload_source_mode(
        source, PurePosixPath(PAYLOAD_ROOT) / "release/release-input.json"
    ) == 0o644


def test_real_payload_tar_and_immutable_seal_preserve_executable_wrapper(tmp_path):
    source_wrapper = ROOT / "client/release/bin/clientflow-release-transaction"
    assert source_wrapper.is_file()

    updater_pyz = tmp_path / "clientflow-updater.pyz"
    updater_pyz.write_bytes(b"test-updater")
    updater_pyz.chmod(0o755)
    payload_tar = tmp_path / "payload.tar"

    # This calls the same production builder used by the release workflow,
    # without producing, approving, publishing or installing any release.
    builder._create_payload(
        ROOT,
        payload_tar,
        version=VERSION,
        epoch=1_700_000_000,
        runtime_inputs=None,
        updater_pyz=updater_pyz,
    )

    with tarfile.open(payload_tar, "r:") as archive:
        member = archive.getmember(f"{PAYLOAD_ROOT}/{WRAPPER}")
        assert member.isfile()
        assert member.mode == 0o755
        stream = archive.extractfile(member)
        assert stream is not None
        assert stream.read() == source_wrapper.read_bytes()

        ordinary = archive.getmember(
            f"{PAYLOAD_ROOT}/release/release-input.json"
        )
        assert ordinary.mode == 0o644

    # Installation seals executable payload files as 0555, not 0444.
    staged = tmp_path / "staged" / PAYLOAD_ROOT
    installed_wrapper = staged / WRAPPER
    installed_wrapper.parent.mkdir(parents=True)
    installed_wrapper.write_bytes(source_wrapper.read_bytes())
    installed_wrapper.chmod(member.mode)
    transaction._make_immutable(staged)

    assert stat.S_IMODE(installed_wrapper.stat().st_mode) == 0o555
    assert stat.S_IMODE(staged.stat().st_mode) == 0o555
