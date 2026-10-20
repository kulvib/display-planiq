"""Control Room atomic order contract: no silent partial writes or role bypass."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request
from sqlmodel import SQLModel, Session, create_engine, select

from service1.models import Client
from service1.routers import clients as router
from service1.ui_realtime import current_generation


def _fixture():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        for name, status, order, org in [
            ("A", "approved", 1, 10),
            ("B", "approved", 2, 20),
            ("C", "approved", 3, 10),
            ("P", "pending", 4, 10),
        ]:
            session.add(Client(name=name, status=status, sort_order=order, organization_id=org))
        session.commit()
        ids = {item.name: item.id for item in session.exec(select(Client)).all()}
    return engine, ids


def _read(session, names):
    return {c.name: c.sort_order for c in session.exec(select(Client)).all() if c.name in names}


def test_atomic_cross_organization_reorder_with_one_commit_and_realtime_wake():
    engine, ids = _fixture()
    with Session(engine) as session:
        actor = SimpleNamespace(id=123, username="admin", role="superadmin", is_superadmin=True, organization_id=None)
        expected = [ids["A"], ids["B"], ids["C"]]
        ordered = [ids["C"], ids["A"], ids["B"]]
        before = current_generation(global_scope=True, organization_id=None)
        before_org10 = current_generation(global_scope=False, organization_id=10)
        before_org20 = current_generation(global_scope=False, organization_id=20)
        response = router.update_control_room_order(
            body=router.ClientControlRoomOrderUpdate(expected_ids=expected, ordered_ids=ordered),
            request=Request({"type": "http", "headers": []}), session=session, user=actor,
        )
        assert response == {"ok": True, "ordered_ids": ordered}
        assert _read(session, {"A", "B", "C", "P"}) == {"A": 2, "B": 3, "C": 1, "P": 4}
        assert current_generation(global_scope=True, organization_id=None) == before + 1
        assert current_generation(global_scope=False, organization_id=10) == before_org10 + 1
        assert current_generation(global_scope=False, organization_id=20) == before_org20 + 1
    with Session(engine) as session:
        assert _read(session, {"A", "B", "C"}) == {"A": 2, "B": 3, "C": 1}


@pytest.mark.parametrize("bad", ["duplicate", "partial", "pending", "stale"])
def test_bad_or_stale_reorders_never_change_any_rows(bad):
    engine, ids = _fixture()
    expected = [ids["A"], ids["B"], ids["C"]]
    ordered = [ids["C"], ids["A"], ids["B"]]
    if bad == "duplicate":
        ordered = [ids["C"], ids["A"], ids["A"]]
    if bad == "partial":
        ordered = [ids["C"], ids["A"]]
    if bad == "pending":
        ordered = [ids["C"], ids["A"], ids["P"]]
    if bad == "stale":
        expected = [ids["B"], ids["A"], ids["C"]]
    with Session(engine) as session:
        with pytest.raises(HTTPException) as error:
            router._persist_control_room_order(session, expected_ids=expected, ordered_ids=ordered)
        assert error.value.status_code in (409, 422)
        session.rollback()
        assert _read(session, {"A", "B", "C", "P"}) == {"A": 1, "B": 2, "C": 3, "P": 4}


@pytest.mark.parametrize("role", ["admin", "viewer", "bruger"])
def test_role_cannot_reorder_even_when_function_called_directly(role):
    engine, ids = _fixture()
    with Session(engine) as session:
        actor = SimpleNamespace(id=8, role=role, is_superadmin=False, organization_id=10)
        with pytest.raises(HTTPException) as error:
            router.update_control_room_order(
                body=router.ClientControlRoomOrderUpdate(
                    expected_ids=[ids["A"], ids["B"], ids["C"]],
                    ordered_ids=[ids["B"], ids["A"], ids["C"]],
                ),
                request=Request({"type": "http", "headers": []}), session=session, user=actor,
            )
        assert error.value.status_code == 403
        assert _read(session, {"A", "B", "C"}) == {"A": 1, "B": 2, "C": 3}


def test_legacy_single_client_sort_write_is_blocked_by_canonical_batch_endpoint():
    source = __import__("inspect").getsource(router.update_client)
    assert 'if "sort_order" in fields:' in source
    assert 'status_code=410' in source
    assert 'client.sort_order = client_update.sort_order' not in source
