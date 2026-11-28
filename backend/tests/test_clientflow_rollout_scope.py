from types import SimpleNamespace
import pytest
from pydantic import ValidationError

from service1.clientflow_rollout_scope import RolloutScope, require_organization_binding
from service1.routers.clientflow_standard_deployments import Target


def target(**kwargs):
    return Target(client_id=7, expected_source_version="1.4.1", **kwargs)


@pytest.mark.parametrize("kind,scope_id,actual", [
    ("all", None, 9), ("all", None, None), ("organization", 9, 9), ("unassigned", None, None),
])
def test_valid_scope_binds_any_client(kind, scope_id, actual):
    scope = RolloutScope(kind=kind, organization_id=scope_id)
    require_organization_binding(scope, target(expected_organization_id=actual),
                                 SimpleNamespace(id=7, organization_id=actual))


@pytest.mark.parametrize("kind,scope_id,actual,expected", [
    ("organization", 9, 10, 10), ("all", None, 10, 9),
    ("unassigned", None, 10, 10), ("organization", 9, None, None),
])
def test_scope_and_stale_membership_rejected(kind, scope_id, actual, expected):
    with pytest.raises(ValueError):
        require_organization_binding(RolloutScope(kind=kind, organization_id=scope_id),
                                     target(expected_organization_id=expected),
                                     SimpleNamespace(organization_id=actual))


def test_explicit_scope_requires_explicit_target_binding():
    with pytest.raises(ValueError):
        require_organization_binding(RolloutScope(kind="all"), target(), SimpleNamespace(organization_id=None))
    with pytest.raises(ValueError):
        require_organization_binding(None, target(expected_organization_id=None), SimpleNamespace(organization_id=None))
    require_organization_binding(None, target(), SimpleNamespace(organization_id=None))


@pytest.mark.parametrize("value", [
    {"kind":"organization"}, {"kind":"all","organization_id":9},
    {"kind":"unassigned","organization_id":9}, {"kind":"organization","organization_id":True},
    {"kind":"organization","organization_id":"9"}, {"kind":"unknown"}, {"kind":"all","extra":True},
])
def test_scope_schema_rejects_aliases(value):
    with pytest.raises(ValidationError):
        RolloutScope.model_validate(value)
