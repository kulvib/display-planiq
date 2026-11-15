"""Fail-closed maintenance interlock for a bounded test-only release-store rotation.

The flag is a separate operational hold, not a release approval. The maintenance flag remains independent from the reviewed
1245 physical-pilot acceptance gate; neither bypasses the other. Existing client update/status traffic is not affected.
"""
from __future__ import annotations

import os
from fastapi import HTTPException

FRESH_INSTALL_SUSPENDED_FLAG = "CLIENTFLOW_FRESH_INSTALL_SUSPENDED"


def require_fresh_install_not_suspended() -> None:
    # Only absent or explicit '0' means the installer is open. Fail closed on
    # malformed values (e.g. 'false', 'True', or a mistyped maintenance flag).
    if os.environ.get(FRESH_INSTALL_SUSPENDED_FLAG, "0") != "0":
        raise HTTPException(
            status_code=503,
            detail="ClientFlow fresh-install er midlertidigt suspenderet under kontrolleret release-overgang",
        )

    # Even if the maintenance flag was accidentally unset, the new 1245
    # stable default cannot be used for a fresh installation until the
    # separately reviewed physical-pilot acceptance record has been signed.
    from .clientflow_releases import ClientFlowCatalogError, load_catalog
    from .clientflow_stable_rollout import (
        ClientFlowStableRolloutDenied, require_1245_physical_acceptance,
    )
    try:
        catalog = load_catalog()
        if catalog.get("default_install_version") == "1.3.44":
            require_1245_physical_acceptance()
    except (ClientFlowCatalogError, ClientFlowStableRolloutDenied) as exc:
        raise HTTPException(
            status_code=503,
            detail="ClientFlow 1245 nyinstallation afventer særskilt fysisk pilotaccept",
        ) from exc
