"""1.4.0 baseline policy. No I/O, no env allowlists, no authorization side effects."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import re
from typing import Any

from .clientflow_release_governance_policy import GovernanceDenied, require_approved_physical_evidence

BASELINE_ID = "clientflow-1.4.0-seq-1250"
BASELINE_VERSION = "1.4.0"
BASELINE_SEQUENCE = 1250
MAX_REQUEST_CLIENTS = 25
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_VERSION = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")


class StandardReleaseDenied(ValueError):
    """The operation must not create or activate a deployment."""


def validate_baseline_catalog(catalog: Mapping[str, Any]) -> Mapping[str, Any]:
    rows = catalog.get("releases")
    if (
        catalog.get("manifest_schema") != 4
        or catalog.get("channel") != "canonical-release-catalog"
        or catalog.get("catalog_sequence") != BASELINE_SEQUENCE
        or catalog.get("latest_stable") != BASELINE_VERSION
        or catalog.get("default_install_version") != BASELINE_VERSION
        or catalog.get("retention_policy") != {
            "max_selectable_versions": 1,
            "max_installable_versions": 1,
            "keep_blocked_metadata": False,
        }
        or not isinstance(rows, list) or len(rows) != 1
        or not isinstance(rows[0], Mapping)
    ):
        raise StandardReleaseDenied("1.4.0 kræver et eksakt standardkatalog med én release")
    release = rows[0]
    required = {
        "release_id": BASELINE_ID, "revision": BASELINE_ID,
        "version": BASELINE_VERSION, "client_version": BASELINE_VERSION,
        "release_sequence": BASELINE_SEQUENCE, "status": "stable",
        "artifact_type": "runtime_release", "install_modes": ["fresh_install", "in_place_update"],
        "min_current_version": "1.3.47", "max_current_version": "1.3.47",
    }
    if any(release.get(key) != value for key, value in required.items()):
        raise StandardReleaseDenied("1.4.0 releaseidentitet eller kompatibilitet matcher ikke baseline")
    for field, required_value in (
        ("installable", True), ("update_allowed", True), ("requires_reboot", True),
        ("rollback_allowed", False), ("requires_explicit_downgrade", False),
    ):
        if release.get(field) is not required_value:
            raise StandardReleaseDenied("1.4.0 installations- eller rollbackpolitik er ugyldig")
    ubuntu = release.get("ubuntu_compatibility")
    if not isinstance(ubuntu, Mapping) or (
        ubuntu.get("policy") != "ubuntu-desktop-lts-minimum"
        or ubuntu.get("minimum_lts_version") != "26.04"
        or ubuntu.get("maximum_certified_version") != "26.04"
        or ubuntu.get("certified_versions") != ["26.04"]
        or ubuntu.get("architecture") != "amd64"
        or ubuntu.get("desktop") != "gnome"
        or ubuntu.get("display_stack") != "wayland"
        or ubuntu.get("requires_platform_preflight") is not True
    ):
        raise StandardReleaseDenied("1.4.0 kræver godkendt Ubuntu-platformspolitik")
    return release


def require_cutover_authority(
    *, catalog: Mapping[str, Any], control: Mapping[str, Any],
    artifact: Mapping[str, Any], acceptance: Mapping[str, Any] | None,
    expected_revision: int, expected_release_id: str, expected_bundle_sha256: str,
    now: datetime,
) -> None:
    """Check locked DB facts against an independently verified published artifact.

    The caller must additionally prove successful physical deployment of these
    bytes, lock all selected clients and enforce canonical runtime presence.
    """
    validate_baseline_catalog(catalog)
    if (
        type(expected_revision) is not int or expected_revision < 1
        or control.get("revision") != expected_revision
        or expected_release_id != BASELINE_ID
        or control.get("stable_release_id") != BASELINE_ID
        or control.get("cutover_enabled") is not True
        or control.get("fleet_open") is not True
    ):
        raise StandardReleaseDenied("Release-cutover eller udrulning er ikke godkendt")
    if (
        not isinstance(expected_bundle_sha256, str) or _SHA.fullmatch(expected_bundle_sha256) is None
        or control.get("stable_bundle_sha256") != expected_bundle_sha256
        or artifact.get("target_release_id") != BASELINE_ID
        or artifact.get("bundle_sha256") != expected_bundle_sha256
        or type(artifact.get("bundle_size")) is not int or artifact["bundle_size"] <= 0
        or not isinstance(artifact.get("release_approval_reference"), str)
        or not artifact["release_approval_reference"].strip()
        or _SHA.fullmatch(str(artifact.get("release_candidate_sha256") or "")) is None
        or _COMMIT.fullmatch(str(artifact.get("source_commit") or "")) is None
    ):
        raise StandardReleaseDenied("Releasepakken matcher ikke godkendt SHA256 og proveniens")
    try:
        require_approved_physical_evidence(
            acceptance=acceptance, release_id=BASELINE_ID,
            bundle_sha256=expected_bundle_sha256, now=now,
        )
    except GovernanceDenied as exc:
        raise StandardReleaseDenied("Fysisk pilot- eller recoveryaccept mangler") from exc
    if acceptance["evidence"].get("observed_version") != BASELINE_VERSION:
        raise StandardReleaseDenied("Fysisk pilot har ikke rapporteret den godkendte baseline")


def validate_selection(targets: list[tuple[int, str]]) -> list[tuple[int, str]]:
    if not 1 <= len(targets) <= MAX_REQUEST_CLIENTS:
        raise StandardReleaseDenied("Vælg 1–25 klienter pr. bestilling")
    ids = set()
    for client_id, version in targets:
        if type(client_id) is not int or client_id <= 0 or client_id in ids:
            raise StandardReleaseDenied("Klientvalget indeholder ugyldige eller dublerede ID'er")
        if not isinstance(version, str) or not _VERSION.fullmatch(version) or version != "1.3.47":
            raise StandardReleaseDenied("Baseline 1.4.0 kræver den godkendte 1.3.47-kildeversion")
        ids.add(client_id)
    return sorted(targets)
