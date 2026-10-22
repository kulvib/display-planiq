"""Historical 1.3.39/1240 is permanently revoked, even with the old flag."""
from __future__ import annotations

import pytest
from service1.clientflow_pilot_1240 import ClientFlowPilotDenied, require_pilot_1240
from service1.clientflow_releases import ClientFlowCatalogError, load_catalog, resolve_release


@pytest.mark.parametrize("flag", [None, "", "0", "1", "2", "*", "01"])
def test_retired_1240_pilot_denies_every_legacy_flag(monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv("CLIENTFLOW_1240_PILOT_CLIENT_ID", raising=False)
    else:
        monkeypatch.setenv("CLIENTFLOW_1240_PILOT_CLIENT_ID", flag)
    with pytest.raises(ClientFlowPilotDenied, match="permanent lukket"):
        require_pilot_1240(
            client_id=1, current_version="1.3.38",
            release={"version": "1.3.39", "release_id": "clientflow-1.3.39-seq-1240"},
            reason="historical regression", pre_first_activation_repair=False,
            confirm_downgrade=False,
        )


def test_retired_1240_is_not_a_catalog_deployment_target():
    load_catalog.cache_clear()
    with pytest.raises(ClientFlowCatalogError, match="findes ikke"):
        resolve_release("1.3.39")


def test_retired_1240_cannot_be_reintroduced_via_old_router_flag():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[2] / "backend/service1/routers/clientflow_deployments.py").read_text()
    assert "require_pilot_1240(" not in source
    assert "clientflow_pilot_1241" in source
