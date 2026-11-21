#!/usr/bin/env python3
"""Read-only, offline chain-of-custody gate for an *unapproved* ClientFlow handoff.

Run after independent reproducible builds AND immediately before manual approval.
This verifies bytes, transport provenance, release identity, embedded tar members,
and the original stable catalog. It never signs, approves, publishes or installs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import tarfile

from clientflow_63d6_active_catalog_contract import ActiveCatalogDenied, verified_mode

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
VERSION = re.compile(r"\d+\.\d+\.\d+\Z")
STATIC = {"clientflow-payload.tar", "manifest.candidate.json", "SHA256SUMS"}
MAX_JSON = 1024 * 1024


class HandoffError(ValueError):
    pass


def _json_no_duplicates(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise HandoffError("duplicate_json_field")
        result[k] = v
    return result


def _reject_nonfinite(_value):
    raise HandoffError("non_finite_json_number")


def _regular(path: Path, max_size: int | None = None) -> Path:
    if path.is_symlink() or not path.is_file():
        raise HandoffError("missing_or_symlinked_artifact")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or (max_size is not None and info.st_size > max_size):
        raise HandoffError("invalid_artifact_file")
    return path


def _load(path: Path, *, max_size: int = MAX_JSON):
    data = _regular(path, max_size).read_bytes()
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_json_no_duplicates,
                          parse_constant=_reject_nonfinite)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HandoffError("invalid_json") from exc


def _hash(stream):
    digest = hashlib.sha256()
    size = 0
    while True:
        part = stream.read(1024 * 1024)
        if not part:
            break
        size += len(part)
        digest.update(part)
    return size, digest.hexdigest()


def _file_hash(path: Path):
    with _regular(path).open("rb") as handle:
        return _hash(handle)


def _require(ok: bool, problem: str):
    if not ok:
        raise HandoffError(problem)


def _verify_original_catalog(repo: Path, release_id: str, sequence: int) -> None:
    """Require the exact pinned catalog; a later update-only stage is not a new stable default."""
    try:
        mode = verified_mode(repo)
    except ActiveCatalogDenied as exc:
        raise HandoffError("stable_catalog_changed") from exc
    allowed = {
        "stable_1245_only": (1245, 1),
        "update_only_1246_pilot_catalog": (1246, 2),
        "update_only_1247_pilot_catalog": (1247, 3),
    }
    _require(mode in allowed, "stable_catalog_changed")
    catalog_sequence, release_count = allowed[mode]
    stable = _load(repo / "backend/service1/clientflow_release_catalog.json")
    releases = stable.get("releases")
    _require(stable.get("latest_stable") == "1.3.44"
             and stable.get("default_install_version") == "1.3.44"
             and stable.get("catalog_sequence") == catalog_sequence
             and type(releases) is list and len(releases) == release_count
             and releases[0].get("release_id") == "clientflow-1.3.44-seq-1245"
             and release_id != releases[0]["release_id"], "stable_catalog_changed")
    # 1248 must follow the pinned, already approved 1247 pilot stage; do not
    # accept a source accidentally checked out with an older active catalog.
    if sequence == 1248:
        _require(mode == "update_only_1247_pilot_catalog", "stable_catalog_changed")


def verify(repo: Path, handoff: Path, *, source_sha: str,
           candidate_sha256: str | None = None,
           installer_sha256: str | None = None,
           runtime_transport_sha256: str | None = None) -> dict:
    """Verify exact artifact set; no FS mutations, Git, network, secrets or DB."""
    _require(bool(GIT_SHA.fullmatch(source_sha)), "invalid_expected_source")
    for value in (candidate_sha256, installer_sha256, runtime_transport_sha256):
        _require(value is None or bool(SHA256.fullmatch(value)), "invalid_expected_sha256")
    _require(repo.is_dir() and not repo.is_symlink() and handoff.is_dir()
             and not handoff.is_symlink(), "invalid_directory")

    version = _regular(repo / "client/VERSION", 128).read_text(encoding="ascii").strip()
    _require(bool(VERSION.fullmatch(version)), "invalid_version")
    inputs = _load(repo / "client/release/release-input.json")
    seq = inputs.get("release_sequence")
    _require(type(seq) is int and seq > 0, "invalid_sequence")
    release_id = f"clientflow-{version}-seq-{seq}"
    candidate = f"{release_id}-candidate.tar"
    installer = f"clientflow-installer-{version}.pyz"
    expected_artifacts = STATIC | {candidate, installer}
    expected_handoff = expected_artifacts | {"REPRODUCIBILITY.json"}
    _require({p.name for p in handoff.iterdir()} == expected_handoff, "unexpected_handoff_files")
    for name in expected_handoff:
        _regular(handoff / name)

    _verify_original_catalog(repo, release_id, seq)
    fleet = _load(repo / "backend/service1/clientflow_1245_fleet_acceptance.json")
    _require(fleet.get("physical_pilot_accepted") is False, "pilot_acceptance_not_disarmed")

    record = _load(handoff / "REPRODUCIBILITY.json")
    _require(record.get("schema_version") == 1 and record.get("reproducible") is True,
             "not_reproducible")
    _require(record.get("source_commit") == source_sha
             and record.get("release_id") == release_id
             and record.get("version") == version
             and type(record.get("release_sequence")) is int
             and record["release_sequence"] == seq,
             "reproducibility_identity_mismatch")
    epoch = record.get("source_date_epoch")
    _require(type(epoch) is int and 1 <= epoch <= 4354819199, "invalid_epoch")
    transport_sha = record.get("runtime_inputs_transport_sha256")
    _require(isinstance(transport_sha, str) and bool(SHA256.fullmatch(transport_sha))
             and (runtime_transport_sha256 is None or transport_sha == runtime_transport_sha256),
             "runtime_input_provenance_mismatch")
    toolchain = _load(repo / "client/release/release-build-toolchain.json")
    _require(record.get("build_toolchain") == {
        "python": toolchain["python"], "pip": toolchain["pip"],
        "setuptools": toolchain["setuptools"]}, "toolchain_mismatch")

    recorded = record.get("artifacts")
    _require(isinstance(recorded, dict) and set(recorded) == expected_artifacts,
             "reproducibility_artifact_set_mismatch")
    actual = {}
    for name in sorted(expected_artifacts):
        size, digest = _file_hash(handoff / name)
        _require(recorded.get(name) == {"size": size, "sha256": digest},
                 "reproducibility_artifact_mismatch:" + name)
        actual[name] = {"size": size, "sha256": digest}
    _require(candidate_sha256 is None or actual[candidate]["sha256"] == candidate_sha256,
             "candidate_sha_mismatch")
    _require(installer_sha256 is None or actual[installer]["sha256"] == installer_sha256,
             "installer_sha_mismatch")

    sums = _regular(handoff / "SHA256SUMS", 4096).read_text(encoding="ascii").splitlines()
    seen = {}
    for line in sums:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        _require(match is not None, "invalid_sha256sums_record")
        digest, name = match.groups()
        _require(name in expected_artifacts - {"SHA256SUMS"} and name not in seen,
                 "unexpected_sha256sums_entry")
        seen[name] = digest
    _require(set(seen) == expected_artifacts - {"SHA256SUMS"}, "incomplete_sha256sums")
    for name, digest in seen.items():
        _require(actual[name]["sha256"] == digest, "sha256sums_mismatch:" + name)

    manifest = _load(handoff / "manifest.candidate.json")
    _require(manifest.get("release_id") == release_id
             and manifest.get("version") == version
             and type(manifest.get("release_sequence")) is int
             and manifest["release_sequence"] == seq
             and manifest.get("source_date_epoch") == epoch,
             "candidate_identity_mismatch")
    _require(manifest.get("source") == {"commit": source_sha, "dirty": False},
             "candidate_source_mismatch")
    _require(manifest.get("deployable") is False
             and manifest.get("release_approval") == {"reference": None, "candidate_sha256": None}
             and (manifest.get("activation") or {}).get("automatic") is False
             and (manifest.get("activation") or {}).get("requires_manual_approval") is True,
             "candidate_already_approved_or_automatic")
    _require(manifest.get("runtime", {}).get("offline_wheelhouse_complete") is True,
             "incomplete_offline_runtime")
    _require(manifest.get("runtime", {}).get("python") == inputs.get("runtime_python")
             and manifest.get("platform", {}).get("architecture") == inputs.get("architecture")
             and manifest.get("platform", {}).get("minimum_lts") == inputs.get("minimum_ubuntu_lts"),
             "platform_identity_mismatch")
    _require(manifest.get("payload", {}).get("file") == "clientflow-payload.tar"
             and manifest["payload"].get("size") == actual["clientflow-payload.tar"]["size"]
             and manifest["payload"].get("sha256") == actual["clientflow-payload.tar"]["sha256"]
             and manifest.get("fresh_installer", {}).get("file") == installer
             and manifest["fresh_installer"].get("size") == actual[installer]["size"]
             and manifest["fresh_installer"].get("sha256") == actual[installer]["sha256"],
             "candidate_descriptors_mismatch")

    with tarfile.open(handoff / candidate, "r:") as archive:
        expected_members = {"manifest.json", "clientflow-payload.tar", installer}
        seen_members: set[str] = set()
        for member in archive:
            _require(member.name in expected_members and member.name not in seen_members
                     and member.isfile(), "unsafe_or_unexpected_candidate_members")
            seen_members.add(member.name)
            _require(member.uid == 0 and member.gid == 0 and member.mtime == epoch,
                     "candidate_tar_metadata_mismatch")
            stream = archive.extractfile(member)
            _require(stream is not None, "unreadable_candidate_member")
            with stream:
                size, digest = _hash(stream)
            if member.name == "manifest.json":
                external = (handoff / "manifest.candidate.json").read_bytes()
                _require(size == len(external) and digest == hashlib.sha256(external).hexdigest(),
                         "embedded_manifest_mismatch")
            else:
                _require(actual[member.name] == {"size": size, "sha256": digest},
                         "embedded_artifact_mismatch:" + member.name)
        _require(seen_members == expected_members, "missing_candidate_members")

    return {"result": "VERIFIED_UNSIGNED_HANDOFF_ONLY", "release_id": release_id,
            "source_commit": source_sha, "candidate_sha256": actual[candidate]["sha256"],
            "installer_sha256": actual[installer]["sha256"],
            "runtime_inputs_transport_sha256": transport_sha,
            "release_approved": False, "deployment_authorized": False,
            "physical_pilot_accepted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-candidate-sha256")
    parser.add_argument("--expected-installer-sha256")
    parser.add_argument("--expected-runtime-transport-sha256")
    args = parser.parse_args()
    try:
        result = verify(args.repo.resolve(), args.handoff.resolve(),
                        source_sha=args.expected_source_sha,
                        candidate_sha256=args.expected_candidate_sha256,
                        installer_sha256=args.expected_installer_sha256,
                        runtime_transport_sha256=args.expected_runtime_transport_sha256)
    except (HandoffError, OSError, KeyError, TypeError, ValueError, tarfile.TarError) as exc:
        parser.exit(1, f"STOP: invalid candidate handoff: {type(exc).__name__}: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
