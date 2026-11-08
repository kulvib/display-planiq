"""Fail-closed maintenance interlock for a bounded test-only release-store rotation.

The flag is a separate operational hold, not a release approval. Until the
fresh-install selector points to a published, verified release, this must
remain on. Existing client update/status traffic is not affected.
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
