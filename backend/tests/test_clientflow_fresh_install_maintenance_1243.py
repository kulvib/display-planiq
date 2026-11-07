"""Fresh-install hold blocks old issued tokens while preserving update traffic."""
from __future__ import annotations

from pathlib import Path
import ast
import pytest
from fastapi import HTTPException

from service1.clientflow_fresh_install_maintenance import (
    FRESH_INSTALL_SUSPENDED_FLAG, require_fresh_install_not_suspended,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("flag", [None, "0"])
def test_normal_operation_unaffected(monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv(FRESH_INSTALL_SUSPENDED_FLAG, raising=False)
    else:
        monkeypatch.setenv(FRESH_INSTALL_SUSPENDED_FLAG, flag)
    assert require_fresh_install_not_suspended() is None


@pytest.mark.parametrize("flag", ["1", "true", "False", "FALSE", "", "00", " 0", "0 ", "invalid"])
def test_maintenance_holds_fail_closed(monkeypatch, flag):
    monkeypatch.setenv(FRESH_INSTALL_SUSPENDED_FLAG, flag)
    with pytest.raises(HTTPException) as exc:
        require_fresh_install_not_suspended()
    assert exc.value.status_code == 503


def test_every_fresh_install_entrypoint_checks_hold_before_any_other_operation():
    tree = ast.parse((ROOT / "backend/service1/routers/enrollment.py").read_text())
    required = {
        "create_enrollment_token", "fresh_install_bootstrap", "download_fresh_install_artifact",
        "claim_enrollment_token", "complete_enrollment",
    }
    found = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in required}
    assert set(found) == required
    for name, node in found.items():
        assert node.body and isinstance(node.body[0], ast.Expr), name
        expr = node.body[0].value
        assert isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name)
        assert expr.func.id == "require_fresh_install_not_suspended", name


def test_hold_cannot_be_activated_from_catalog_or_client_parameters():
    source = (ROOT / "backend/service1/clientflow_fresh_install_maintenance.py").read_text()
    assert 'os.environ.get(FRESH_INSTALL_SUSPENDED_FLAG, "0") != "0"' in source
    assert "CLIENTFLOW_FRESH_INSTALL_SUSPENDED" in source
