"""Independent SQLite integration tests of the 1244 identity retirement operation.

No production DB, no network, and no actual credentials are used.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from service1 import clientflow_1244_identity_decommission as reset  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as c:
        c.execute(text("""CREATE TABLE client (
            id INTEGER PRIMARY KEY,name TEXT,status TEXT,deleted_at DATETIME,
            deleted_reason TEXT,organization_id INTEGER,client_token_version INTEGER,
            deleted_previous_status TEXT,restored_at DATETIME,restored_by_user_id INTEGER,
            client_secret_hash TEXT,client_secret_revoked_at DATETIME,
            pending_chrome_action TEXT,pending_chrome_action_source TEXT
        )"""))
        c.execute(text("""CREATE TABLE enrollmenttoken(
            id INTEGER PRIMARY KEY,used_at DATETIME,revoked_at DATETIME,
            expires_at DATETIME
        )"""))
        c.execute(text("""CREATE TABLE clientflow_deployment(
            id INTEGER PRIMARY KEY,completed_at DATETIME
        )"""))
        for table in ("client_domain_credential", "livestream_v2_credential",
                      "terminal_credential", "remote_desktop_credential"):
            c.execute(text(f"""CREATE TABLE {table}(
                id INTEGER PRIMARY KEY,client_id INTEGER,revoked_at DATETIME,
                token_version INTEGER NOT NULL DEFAULT 0
            )"""))
        for table in ("clientflow_update_credential", "client_system_encryption_key"):
            c.execute(text(f"CREATE TABLE {table}(id INTEGER PRIMARY KEY,client_id INTEGER,revoked_at DATETIME)"))
        c.execute(text("CREATE TABLE clientflow_update_provisioning_token(id INTEGER PRIMARY KEY,client_id INTEGER,revoked_at DATETIME,used_at DATETIME)"))
        c.execute(text("CREATE TABLE client_enrollment_receipt(id INTEGER PRIMARY KEY,client_id INTEGER,expires_at DATETIME,completed_at DATETIME)"))
        for table in ("terminal_client", "remote_desktop_client"):
            c.execute(text(f"CREATE TABLE {table}(id INTEGER PRIMARY KEY,status TEXT)"))
        c.execute(text("CREATE TABLE root_terminal_grant(id INTEGER PRIMARY KEY,client_id INTEGER,revoked_at DATETIME)"))
        c.execute(text("CREATE TABLE clientflow_rollback_permit(id INTEGER PRIMARY KEY,client_id INTEGER,state TEXT,revoked_at DATETIME)"))
        for table in ("terminal_session", "remote_desktop_session"):
            extra = "close_reason TEXT," if table == "remote_desktop_session" else ""
            c.execute(text(f"CREATE TABLE {table}(id TEXT PRIMARY KEY,client_id INTEGER,status TEXT,disconnected_at DATETIME,last_activity_at DATETIME,{extra}created_at DATETIME)"))
        for table, field in (("terminal_session_event", "terminal_session_id"),
                             ("remote_desktop_session_event", "remote_desktop_session_id")):
            c.execute(text(f"CREATE TABLE {table}(id TEXT PRIMARY KEY,{field} TEXT,event_type TEXT,actor_user_id INTEGER,credential_id TEXT,created_at DATETIME,details TEXT)"))
        c.execute(text("CREATE TABLE client_command(id INTEGER PRIMARY KEY,client_id INTEGER,status TEXT,completed_at DATETIME,end_reason TEXT)"))
        c.execute(text("CREATE TABLE livestream_v2_command(id INTEGER PRIMARY KEY,client_id INTEGER,state TEXT,completed_at DATETIME,updated_at DATETIME)"))
        c.execute(text("CREATE TABLE livestream_v2_generation(id INTEGER PRIMARY KEY,client_id INTEGER,state TEXT,stopped_at DATETIME)"))
        c.execute(text("CREATE TABLE livestream_v2_viewer(id INTEGER PRIMARY KEY,client_id INTEGER,ended_at DATETIME,end_reason TEXT)"))
        c.execute(text("""CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY,created_at DATETIME,action TEXT,status TEXT,
            actor_username TEXT,actor_role TEXT,entity_type TEXT,entity_id INTEGER,
            entity_label TEXT,target_organization_id INTEGER,severity TEXT,
            is_critical BOOLEAN,details TEXT
        )"""))
        for id_, name in ((1,"Heidi1"),(2,"Viborg2"),(3,"Other")):
            c.execute(text("""INSERT INTO client (id,name,status,organization_id,client_token_version,client_secret_hash)
                              VALUES (:id,:name,'approved',7,2,'old-secret-hash')"""),{"id":id_,"name":name})
            c.execute(text("INSERT INTO terminal_client (id,status) VALUES (:id,'approved')"),{"id":id_})
            c.execute(text("INSERT INTO remote_desktop_client (id,status) VALUES (:id,'approved')"),{"id":id_})
            for table in ("client_domain_credential","livestream_v2_credential","terminal_credential","remote_desktop_credential"):
                c.execute(text(f"INSERT INTO {table} (id,client_id,token_version) VALUES (:id,:id,3)"),{"id":id_})
            for table in ("clientflow_update_credential","client_system_encryption_key"):
                c.execute(text(f"INSERT INTO {table} (id,client_id) VALUES (:id,:id)"),{"id":id_})
            c.execute(text("INSERT INTO clientflow_update_provisioning_token (id,client_id) VALUES (:id,:id)"),{"id":id_})
            c.execute(text("INSERT INTO root_terminal_grant (id,client_id) VALUES (:id,:id)"),{"id":id_})
            c.execute(text("INSERT INTO clientflow_rollback_permit (id,client_id,state) VALUES (:id,:id,'issued')"),{"id":id_})
            c.execute(text("INSERT INTO client_enrollment_receipt (id,client_id,expires_at) VALUES (:id,:id,'2099-01-01 00:00:00')"),{"id":id_})
            for table in ("terminal_session", "remote_desktop_session"):
                c.execute(text(f"INSERT INTO {table} (id,client_id,status) VALUES (:id,:client_id,'connected')"),{"id":f"session-{table}-{id_}","client_id":id_})
            c.execute(text("INSERT INTO client_command(id,client_id,status) VALUES (:id,:id,'queued')"),{"id":id_})
            c.execute(text("INSERT INTO livestream_v2_command(id,client_id,state) VALUES (:id,:id,'queued')"),{"id":id_})
            c.execute(text("INSERT INTO livestream_v2_generation(id,client_id,state) VALUES (:id,:id,'running')"),{"id":id_})
            c.execute(text("INSERT INTO livestream_v2_viewer(id,client_id) VALUES (:id,:id)"),{"id":id_})
    yield engine
    engine.dispose()


def get(conn, query):
    return conn.execute(text(query)).scalar_one()


def test_one_transaction_decommissions_only_pinned_old_identities(db):
    with db.connect() as c:
        preflight = reset.snapshot(c)
        assert preflight["client_ids"] == [1,2]
        assert preflight["active_before_or_remaining"]["client_domain_credential"] == 2
        assert get(c,"SELECT COUNT(*) FROM audit_logs") == 0
    with db.begin() as c:
        result = reset.decommission(c)
        assert result["revoked_terminal_sessions"] == 2
        assert result["revoked_remote_desktop_sessions"] == 2
    with db.connect() as c:
        after = reset.snapshot(c)
        assert after["already_decommissioned"]
        assert all(count == 0 for count in after["active_before_or_remaining"].values())
        assert get(c,"SELECT COUNT(*) FROM client WHERE deleted_reason='clientflow_1244_identity_decommissioned'") == 2
        assert get(c,"SELECT COUNT(*) FROM client WHERE id=3 AND status='approved'") == 1
        assert get(c,"SELECT client_token_version FROM client WHERE id=1") == 3
        assert get(c,"SELECT client_token_version FROM client WHERE id=3") == 2
        assert get(c,"SELECT COUNT(*) FROM audit_logs WHERE is_critical=1") == 2
        assert get(c,"SELECT COUNT(*) FROM terminal_session_event") == 2
        assert get(c,"SELECT COUNT(*) FROM remote_desktop_session_event") == 2
        assert get(c,"SELECT COUNT(*) FROM clientflow_update_provisioning_token WHERE client_id IN (1,2) AND revoked_at IS NULL") == 0
        assert get(c,"SELECT COUNT(*) FROM root_terminal_grant WHERE client_id IN (1,2) AND revoked_at IS NULL") == 0
        assert get(c,"SELECT COUNT(*) FROM clientflow_rollback_permit WHERE client_id IN (1,2) AND state='issued'") == 0
        assert get(c,"SELECT COUNT(*) FROM client WHERE id IN (1,2)") == 2
        assert get(c,"SELECT COUNT(*) FROM terminal_session WHERE client_id IN (1,2) AND status='revoked'") == 2
        assert get(c,"SELECT COUNT(*) FROM remote_desktop_session WHERE client_id IN (1,2) AND status='revoked'") == 2


def test_idempotent_no_extra_events_or_token_versions(db):
    with db.begin() as c:
        reset.decommission(c)
    with db.begin() as c:
        again = reset.decommission(c)
        assert again["already_decommissioned"]
        assert not again["modified"]
    with db.connect() as c:
        assert get(c,"SELECT COUNT(*) FROM audit_logs") == 2
        assert get(c,"SELECT client_token_version FROM client WHERE id=1") == 3


@pytest.mark.parametrize("bad_name,bad_status",[("Wrong",None),(None,"deleted")])
def test_wrong_identity_or_pre_deleted_fails_without_mutation(db,bad_name,bad_status):
    with db.begin() as c:
        if bad_name:
            c.execute(text("UPDATE client SET name=:name WHERE id=2"),{"name":bad_name})
        if bad_status:
            c.execute(text("UPDATE client SET status=:status WHERE id=2"),{"status":bad_status})
    with pytest.raises(reset.IdentityResetDenied):
        with db.begin() as c:
            reset.decommission(c)
    with db.connect() as c:
        assert get(c,"SELECT COUNT(*) FROM audit_logs") == 0
        assert get(c,"SELECT COUNT(*) FROM client_domain_credential WHERE revoked_at IS NOT NULL") == 0


def test_open_enrollment_or_deployment_blocks_operation(db):
    with db.begin() as c:
        c.execute(text("INSERT INTO enrollmenttoken(id,expires_at) VALUES (10,'2099-01-01 00:00:00')"))
    with pytest.raises(reset.IdentityResetDenied):
        with db.begin() as c:reset.decommission(c)
    with db.begin() as c:
        c.execute(text("DELETE FROM enrollmenttoken WHERE id=10"))
        c.execute(text("INSERT INTO clientflow_deployment(id) VALUES (10)"))
    with pytest.raises(reset.IdentityResetDenied):
        with db.begin() as c:reset.decommission(c)
    with db.connect() as c:assert get(c,"SELECT COUNT(*) FROM audit_logs") == 0


def test_transaction_rollback_on_missing_audit_table(db):
    with db.begin() as c:
        c.execute(text("DROP TABLE audit_logs"))
    with pytest.raises(Exception):
        with db.begin() as c:reset.decommission(c)
    with db.connect() as c:
        assert get(c,"SELECT COUNT(*) FROM client_domain_credential WHERE revoked_at IS NOT NULL") == 0
        assert get(c,"SELECT COUNT(*) FROM client WHERE deleted_at IS NOT NULL") == 0


def test_quiesce_and_catalog_guards(tmp_path,monkeypatch):
    catalog = json.loads((ROOT / "backend/service1/clientflow_release_catalog.json").read_text())
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps(catalog))
    monkeypatch.delenv('CLIENTFLOW_FRESH_INSTALL_SUSPENDED',raising=False)
    with pytest.raises(reset.IdentityResetDenied,match='suspension'):
        reset.require_1244_paused(path)
    monkeypatch.setenv('CLIENTFLOW_FRESH_INSTALL_SUSPENDED','1')
    reset.require_1244_paused(path)
    monkeypatch.setenv('CLIENTFLOW_1243_PILOT_CLIENT_ID','2')
    with pytest.raises(reset.IdentityResetDenied,match='pilot'):
        reset.require_1244_paused(path)
    monkeypatch.delenv('CLIENTFLOW_1243_PILOT_CLIENT_ID')
    catalog['latest_stable'] = '1.3.38'
    path.write_text(json.dumps(catalog))
    with pytest.raises(reset.IdentityResetDenied,match='catalog'):
        reset.require_1244_paused(path)


def test_client_restore_and_purge_are_not_escape_hatches():
    source = (ROOT/'backend/service1/routers/clients.py').read_text()
    assert 'if client.deleted_reason == TOMBSTONE_REASON:' in source
    assert 'Nedlagt ClientFlow-identitet kan ikke gendannes' in source
    assert 'Nedlagt ClientFlow-identitet og historiske data må ikke slettes' in source
    assert 'Nedlagt ClientFlow-identitet er skrivebeskyttet' in source


def test_partial_tombstone_or_resurrected_old_auth_fails_closed(db):
    with db.begin() as conn:
        reset.decommission(conn)
    with db.begin() as conn:
        conn.execute(text("UPDATE client_domain_credential SET revoked_at=NULL WHERE client_id=1"))
    with pytest.raises(reset.IdentityResetDenied, match="active authority"):
        with db.begin() as conn:
            reset.decommission(conn)
    with db.begin() as conn:
        conn.execute(text("UPDATE client_domain_credential SET revoked_at=CURRENT_TIMESTAMP WHERE client_id=1"))
        conn.execute(text("UPDATE client SET deleted_reason='other' WHERE id=2"))
    with pytest.raises(reset.IdentityResetDenied, match="Partial or unexpected"):
        with db.begin() as conn:
            reset.decommission(conn)


def test_fresh_install_release_verify_rejects_extra_and_symlink(tmp_path, monkeypatch):
    from scripts import decommission_clientflow_1244_old_identities as operator
    # No 220-MB files are needed: injectable proof constants only in test.
    good = tmp_path / f"{reset.RELEASE_ID}.tar"
    good.write_bytes(b"test approved bytes")
    monkeypatch.setattr(operator, "RELEASE_SHA256", __import__('hashlib').sha256(good.read_bytes()).hexdigest())
    monkeypatch.setattr(operator, "RELEASE_SIZE", len(good.read_bytes()))
    operator.verify_only_1244_artifact(tmp_path)
    extra = tmp_path / "clientflow-1.3.42-seq-1243.tar"
    extra.write_bytes(b"legacy")
    with pytest.raises(reset.IdentityResetDenied, match="one-release"):
        operator.verify_only_1244_artifact(tmp_path)
    extra.unlink()
    good.unlink()
    good.symlink_to(tmp_path / "nothing")
    with pytest.raises((reset.IdentityResetDenied, OSError)):
        operator.verify_only_1244_artifact(tmp_path)
