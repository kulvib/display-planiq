"""Fail-closed 1.3.35/1236 source-stage contract for the physical guard fix.

This is not an approval, publication, or in-place update authorization.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_1236_historical_evidence_is_retained_after_1239_promotion() -> None:
    assert read("client/VERSION").strip() == "1.3.39"
    release = json.loads(read("client/release/release-input.json"))
    assert release["release_sequence"] == 1240
    assert release["runtime_python"] == "3.13.14"
    assert release["minimum_ubuntu_lts"] == "26.04"
    assert release["architecture"] == "amd64"

    catalog = json.loads(read("backend/service1/clientflow_release_catalog.json"))
    assert catalog["catalog_sequence"] == 1239
    assert catalog["latest_stable"] == "1.3.38"
    assert catalog["default_install_version"] == "1.3.38"
    assert len(catalog["releases"]) == 1
    published = catalog["releases"][0]
    assert published["release_id"] == "clientflow-1.3.38-seq-1239"
    historical = read("CLIENTFLOW_1.3.35_1236_FRESH_INSTALL_CATALOG_PROMOTION.md")
    assert "94abdce02578a09d067397e7a2d9a9d86a0c20e696eb734a79ade8a483c713d4" in historical
    assert published["install_modes"] == ["fresh_install"]
    assert published["update_allowed"] is False
    assert published["rollback_allowed"] is False
    assert published["installable"] is True
    assert all(item["release_sequence"] != 1235 for item in catalog["releases"])
    assert all(item["version"] != "1.3.34" for item in catalog["releases"])


def test_guard_fix_is_in_staged_runtime_but_periodic_policy_is_unchanged() -> None:
    guard = read("client/runtime/clientflow_runtime/kiosk_quicksettings_guard.py")
    session = read("client/runtime/clientflow_runtime/kiosk_session_policy.py")
    quick_unit = read("client/systemd/clientflow-kiosk-quicksettings-guard.service")
    recurring_unit = read("client/systemd/clientflow-kiosk-session-policy.service")
    assert "enforce(lockdown_quicksettings=True, use_setpriv=True)" in guard
    assert 'SETPRIV = Path("/usr/bin/setpriv")' in session
    assert '"--inh-caps=-all"' in session
    assert '"--bounding-set=-all"' in session
    assert '"--no-new-privs"' in session
    assert '"--init-groups"' in session
    assert 'enforce()' in session
    assert "NoNewPrivileges=yes" in quick_unit
    assert "ProtectSystem=strict" in quick_unit
    assert "ProtectHome=read-only" in quick_unit
    assert "NoNewPrivileges=no" in recurring_unit


def test_unpublished_candidate_is_not_misrepresented_as_approved_or_auto_update() -> None:
    doc = read("CLIENTFLOW_1.3.35_1236_QUICKSETTINGS_GUARD_RELEASE_STAGE.md")
    assert "NOT approved" in doc
    assert "NOT published" in doc
    assert "NOT catalog-promoted" in doc
    assert "No in-place update" in doc
    assert "physical Ubuntu 26.04 verification" in doc
