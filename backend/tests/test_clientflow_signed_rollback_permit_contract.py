"""Offline signed one-shot rollback proof against root transaction (synthetic only)."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

ROOT = Path(__file__).resolve().parents[2]
for folder in (ROOT / "client/release/lib", ROOT / "backend", ROOT / "backend/tests"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from clientflow_release import transaction
from clientflow_release_format.rollback_permit import (
    PURPOSE, RollbackPermitError, b64_encode, canonical_bytes, reason_hash, strict_load,
)
from service1.clientflow_rollback_signing import sign_permit
from test_clientflow_manual_rollback_1241 import CURRENT, PREVIOUS, APPROVAL, prepare

REASON = "Approved pilot rollback for security-contract test"
SHA = "a" * 64


def setup(tmp_path, monkeypatch):
    layout, calls = prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(transaction, "_canonical_activation_approval",
                        lambda _layout, state, target, *, expected_approval_reference: APPROVAL)
    source = layout.releases / CURRENT / "release"
    source.mkdir()
    private = Ed25519PrivateKey.generate()
    pub = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    der = private.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    key_id = hashlib.sha256(der).hexdigest()[:32]
    (source / "rollback-trust.json").write_text(json.dumps({
        "schema_version": 1, "enabled": True,
        "keys": [{"key_id": key_id, "public_key_b64": b64_encode(pub),
                  "min_policy_revision": 1, "minimum_safe_release_sequence": 1239}],
    }))
    identity = layout.path("/etc/clientflow/update/credential.json")
    identity.parent.mkdir(parents=True)
    credential_id = str(uuid.uuid4())
    identity.write_text(json.dumps({"client_id": 1, "credential_id": credential_id}))
    identity.chmod(0o600)
    state = transaction.load_state(layout)
    state["installed"][PREVIOUS]["bundle_sha256"] = SHA
    state["installed"][CURRENT]["bundle_sha256"] = "b" * 64
    transaction.save_state(layout, state)
    private_pem = private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    monkeypatch.setenv("CLIENTFLOW_SIGNED_ROLLBACK_ENABLED", "true")
    monkeypatch.setenv("CLIENTFLOW_ROLLBACK_SIGNING_KEY_PEM_B64", base64.b64encode(private_pem).decode("ascii"))
    now = int(time.time())
    payload = {
        "schema_version": 1, "purpose": PURPOSE, "algorithm": "Ed25519", "issuer_key_id": key_id,
        "permit_id": str(uuid.uuid4()), "client_id": 1, "update_credential_id": credential_id,
        "from_release_id": CURRENT, "from_sequence": 1241,
        "to_release_id": PREVIOUS, "to_sequence": 1239,
        "release_approval_reference": APPROVAL, "bundle_sha256": SHA,
        "reason_sha256": reason_hash(REASON), "policy_revision": 1,
        "minimum_safe_release_sequence": 1239,
        "issued_at": now, "not_before": now, "expires_at": now + 180,
    }
    token = layout.path("/var/lib/clientflow/release/approved-permit.json")
    def sign(fields=None):
        signed, actual_kid = sign_permit(payload if fields is None else fields)
        assert actual_kid == key_id
        token.write_text(signed)
        token.chmod(0o600)
        return token
    return layout, calls, payload, sign


def test_signature_and_once_only_flow(tmp_path, monkeypatch):
    layout, calls, payload, sign = setup(tmp_path, monkeypatch)
    token = sign()
    result = transaction.rollback_release(release_id=PREVIOUS, expected_release_approval_reference=APPROVAL,
                                          reason=REASON, permit_file=token, layout=layout)
    assert result["rollback_permit_id"] == payload["permit_id"]
    state = transaction.load_state(layout)
    assert state["used_rollback_permits"] == {payload["permit_id"]: PREVIOUS}
    assert state["activation_intent"] is None
    assert state["history"][-1]["permit_id"] == payload["permit_id"]
    assert calls.index("health:" + PREVIOUS) < calls.index("_enable_target")
    # Simulate a later valid forward reactivation: old permit cannot repeat.
    state["active_release_id"] = CURRENT
    state["previous_release_id"] = PREVIOUS
    transaction.save_state(layout, state)
    layout.active.unlink()
    layout.active.symlink_to("releases/" + CURRENT)
    with pytest.raises(transaction.TransactionError, match="brugt"):
        transaction.rollback_release(release_id=PREVIOUS, expected_release_approval_reference=APPROVAL,
                                     reason=REASON, permit_file=token, layout=layout)


@pytest.mark.parametrize("change", [
    "none", "wrong_client", "wrong_credential", "wrong_source", "wrong_target", "wrong_hash",
    "wrong_reason", "policy_floor", "policy_revision", "expired", "not_before", "bad_signature", "unknown_kid",
])
def test_invalid_permit_rejected_before_mutation(tmp_path, monkeypatch, change):
    layout, calls, original, sign = setup(tmp_path, monkeypatch)
    token = None
    if change == "none":
        pass
    elif change == "bad_signature":
        token = sign()
        obj = json.loads(token.read_text())
        obj["signature_b64"] = b64_encode(b"A" * 64)
        token.write_bytes(canonical_bytes(obj))
    elif change == "unknown_kid":
        token = sign()
        # Instead change the trusted key list, preserving signed token.
        trust = layout.releases / CURRENT / "release/rollback-trust.json"
        obj = json.loads(trust.read_text())
        obj["keys"][0]["key_id"] = "0" * 32
        trust.write_text(json.dumps(obj))
    elif change in {"policy_floor", "policy_revision"}:
        token = sign()
        trust = layout.releases / CURRENT / "release/rollback-trust.json"
        obj = json.loads(trust.read_text())
        obj["keys"][0]["minimum_safe_release_sequence" if change == "policy_floor" else "min_policy_revision"] = 1240 if change == "policy_floor" else 2
        trust.write_text(json.dumps(obj))
    else:
        changed = dict(original)
        if change == "wrong_client": changed["client_id"] = 999
        if change == "wrong_credential": changed["update_credential_id"] = str(uuid.uuid4())
        if change == "wrong_source": changed["from_release_id"] = "clientflow-1.3.39-seq-1241"
        if change == "wrong_target": changed["to_release_id"] = "clientflow-1.3.37-seq-1239"
        if change == "wrong_hash": changed["bundle_sha256"] = "b" * 64
        if change == "wrong_reason": changed["reason_sha256"] = "c" * 64
        if change == "expired":
            changed["issued_at"] = original["issued_at"] - 400
            changed["not_before"] = changed["issued_at"]
            changed["expires_at"] = changed["issued_at"] + 180
        if change == "not_before":
            changed["issued_at"] = original["issued_at"] + 10
            changed["not_before"] = changed["issued_at"]
            changed["expires_at"] = changed["issued_at"] + 180
        token = sign(changed)
    with pytest.raises((transaction.TransactionError, RollbackPermitError, ValueError)):
        transaction.rollback_release(release_id=PREVIOUS, expected_release_approval_reference=APPROVAL,
                                     reason=REASON, permit_file=token, layout=layout)
    assert calls == []
    assert transaction.load_state(layout)["active_release_id"] == CURRENT
    assert transaction.load_state(layout)["history"] == []


def test_resume_existing_committed_signed_intent_when_expired(tmp_path, monkeypatch):
    layout, calls, payload, sign = setup(tmp_path, monkeypatch)
    token = sign()
    state = transaction.load_state(layout)
    state["used_rollback_permits"] = {payload["permit_id"]: PREVIOUS}
    state["activation_intent"] = {
        "release_id": PREVIOUS, "previous_release_id": CURRENT,
        "release_approval_reference": APPROVAL,
        "manual_rollback_permit_id": payload["permit_id"],
    }
    state["history"] = [
        {"event": "manual_rollback_requested", "from_release_id": CURRENT, "to_release_id": PREVIOUS,
         "release_approval_reference": APPROVAL, "reason": REASON, "permit_id": payload["permit_id"]},
        {"event": "activation_intent_committed", "release_id": PREVIOUS,
         "previous_release_id": CURRENT, "release_approval_reference": APPROVAL},
    ]
    transaction.save_state(layout, state)
    from clientflow_release import rollback_verifier
    monkeypatch.setattr(rollback_verifier, "_time_verified", lambda _: (_ for _ in ()).throw(AssertionError("resume should not re-read clock")))
    result = transaction.rollback_release(release_id=PREVIOUS, expected_release_approval_reference=APPROVAL,
                                          reason=REASON, permit_file=token, layout=layout)
    assert result["rollback_permit_id"] == payload["permit_id"]
    assert transaction.load_state(layout)["activation_intent"] is None


def test_strict_json_rejects_duplicate_and_noncanonical():
    with pytest.raises(RollbackPermitError): strict_load(b'{"a":1,"a":2}')
    with pytest.raises(RollbackPermitError): strict_load(b'{"a": 1}')
    with pytest.raises(RollbackPermitError): strict_load(b'{"x":NaN}')


def test_signed_resume_after_symlink_switch_uses_pinned_source_trust(tmp_path, monkeypatch):
    layout, calls, payload, sign = setup(tmp_path, monkeypatch)
    token = sign()
    state = transaction.load_state(layout)
    state["used_rollback_permits"] = {payload["permit_id"]: PREVIOUS}
    state["activation_intent"] = {
        "release_id": PREVIOUS, "previous_release_id": CURRENT,
        "release_approval_reference": APPROVAL, "manual_rollback_permit_id": payload["permit_id"],
    }
    state["history"] = [
        {"event": "manual_rollback_requested", "from_release_id": CURRENT, "to_release_id": PREVIOUS,
         "release_approval_reference": APPROVAL, "reason": REASON, "permit_id": payload["permit_id"]},
        {"event": "activation_intent_committed", "release_id": PREVIOUS,
         "previous_release_id": CURRENT, "release_approval_reference": APPROVAL},
    ]
    transaction.save_state(layout, state)
    layout.active.unlink()
    layout.active.symlink_to("releases/" + PREVIOUS)
    result = transaction.rollback_release(
        release_id=PREVIOUS, expected_release_approval_reference=APPROVAL,
        reason=REASON, permit_file=token, layout=layout,
    )
    assert result["rollback_permit_id"] == payload["permit_id"]
    assert transaction.load_state(layout)["active_release_id"] == PREVIOUS


def test_uncommitted_signed_request_resumes_without_double_audit(tmp_path, monkeypatch):
    layout, calls, payload, sign = setup(tmp_path, monkeypatch)
    token = sign()
    state = transaction.load_state(layout)
    state["used_rollback_permits"] = {payload["permit_id"]: PREVIOUS}
    state["history"] = [{
        "event": "manual_rollback_requested", "permit_id": payload["permit_id"],
        "from_release_id": CURRENT, "to_release_id": PREVIOUS,
        "release_approval_reference": APPROVAL, "reason": REASON,
    }]
    transaction.save_state(layout, state)
    result = transaction.rollback_release(
        release_id=PREVIOUS, expected_release_approval_reference=APPROVAL,
        reason=REASON, permit_file=token, layout=layout,
    )
    assert result["rollback_permit_id"] == payload["permit_id"]
    requests = [v for v in transaction.load_state(layout)["history"]
                if v.get("event") == "manual_rollback_requested"]
    assert len(requests) == 1


def test_missing_or_disabled_trust_preserves_legacy_release_behavior(tmp_path, monkeypatch):
    layout, calls = prepare(tmp_path, monkeypatch)
    result = transaction.rollback_release(
        release_id=PREVIOUS, expected_release_approval_reference=APPROVAL,
        reason=REASON, layout=layout,
    )
    assert result["status"] == "active"
    assert "rollback_permit_id" not in result


def test_completed_rollback_can_be_reported_with_same_deterministic_event(tmp_path, monkeypatch):
    layout, _, payload, sign = setup(tmp_path, monkeypatch)
    from clientflow_release.rollback_reporter import report_completed_rollback
    transaction.rollback_release(
        release_id=PREVIOUS, expected_release_approval_reference=APPROVAL,
        reason=REASON, permit_file=sign(), layout=layout,
    )
    observed = []
    class Transport:
        def issue_access_token(self):
            return "synthetic-authenticated-token"
        def _json_request(self, **kwargs):
            observed.append(kwargs)
            return {"status": "succeeded", "replayed": len(observed) > 1}
    transport = Transport()
    report_completed_rollback(payload["permit_id"], layout=layout, transport=transport)
    report_completed_rollback(payload["permit_id"], layout=layout, transport=transport)
    assert len(observed) == 2
    assert observed[0]["payload"]["event_id"] == observed[1]["payload"]["event_id"]
    assert observed[0]["path"].endswith(payload["permit_id"] + "/events")
    assert observed[0]["payload"]["outcome"] == "succeeded"


def test_unfinished_rollback_cannot_report_success(tmp_path, monkeypatch):
    layout, _, payload, sign = setup(tmp_path, monkeypatch)
    from clientflow_release.rollback_reporter import report_completed_rollback
    with pytest.raises(transaction.TransactionError, match="afsluttet"):
        report_completed_rollback(payload["permit_id"], layout=layout, transport=object())


@pytest.mark.parametrize("trust_mode", ["missing", "disabled"])
def test_new_source_never_falls_back_to_unsigned_rollback(tmp_path, monkeypatch, trust_mode):
    """A 1242+ source must not silently take the historical unsigned path."""
    from clientflow_release import rollback_verifier
    from clientflow_release_format.rollback_permit import SIGNED_ROLLBACK_MIN_SOURCE_SEQUENCE

    layout, calls = prepare(tmp_path, monkeypatch)
    future = f"clientflow-1.3.41-seq-{SIGNED_ROLLBACK_MIN_SOURCE_SEQUENCE}"
    old_source = layout.releases / CURRENT
    new_source = layout.releases / future
    old_source.rename(new_source)
    manifest = new_source / "release-manifest.json"
    document = json.loads(manifest.read_text())
    document["release_id"] = future
    manifest.write_text(json.dumps(document))
    trust = new_source / "release/rollback-trust.json"
    if trust_mode == "disabled":
        trust.parent.mkdir()
        trust.write_text(json.dumps({"schema_version": 1, "enabled": False, "keys": []}))

    state = transaction.load_state(layout)
    state["installed"][future] = state["installed"].pop(CURRENT)
    state["installed"][future]["release_sequence"] = SIGNED_ROLLBACK_MIN_SOURCE_SEQUENCE
    state["active_release_id"] = future
    state["highest_release_sequence"] = SIGNED_ROLLBACK_MIN_SOURCE_SEQUENCE
    transaction.save_state(layout, state)
    layout.active.unlink()
    layout.active.symlink_to("releases/" + future)

    with pytest.raises(transaction.TransactionError, match="gyldig central tilladelse"):
        transaction.rollback_release(
            release_id=PREVIOUS, expected_release_approval_reference=APPROVAL,
            reason=REASON, layout=layout,
        )
    assert calls == []
    assert transaction.load_state(layout)["active_release_id"] == future
    with pytest.raises(RollbackPermitError, match="rollback-trust"):
        rollback_verifier._trust(layout, future)


def test_historical_source_preserves_unsigned_rollback_contract(tmp_path, monkeypatch):
    layout, calls = prepare(tmp_path, monkeypatch)
    result = transaction.rollback_release(
        release_id=PREVIOUS, expected_release_approval_reference=APPROVAL,
        reason=REASON, layout=layout,
    )
    assert result["status"] == "active"
    assert "rollback_permit_id" not in result
    assert calls
