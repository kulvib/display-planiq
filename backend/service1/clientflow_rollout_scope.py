"""Reusable, strict organization scope for explicit forward-update orders.

Selection is not authority. Always check actual organization on the locked
client row, alongside the normal release, identity and compatibility gates.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RolloutScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["all", "organization", "unassigned"]
    organization_id: int | None = Field(default=None, strict=True, gt=0)

    @model_validator(mode="after")
    def validate_binding(self):
        if (self.kind == "organization") != (self.organization_id is not None):
            raise ValueError("Organisation og scope matcher ikke")
        return self


def require_organization_binding(scope, target, client):
    # Legacy single-client and historic orders omit scope entirely. A scoped
    # order must bind every selected client, even when scope is 'all'.
    if scope is None:
        if "expected_organization_id" in target.model_fields_set:
            raise ValueError("Organisation kræver eksplicit scope")
        return
    if "expected_organization_id" not in target.model_fields_set:
        raise ValueError("Klientens organisation mangler")
    actual = client.organization_id
    if actual != target.expected_organization_id:
        raise ValueError("Klientens organisation er ændret")
    if scope.kind == "organization" and actual != scope.organization_id:
        raise ValueError("Klienten tilhører ikke den valgte organisation")
    if scope.kind == "unassigned" and actual is not None:
        raise ValueError("Klienten tilhører en organisation")
