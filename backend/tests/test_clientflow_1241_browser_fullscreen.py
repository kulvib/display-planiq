"""Verify stale-safe fullscreen Display projection in the canonical API."""
from datetime import datetime, timezone
from types import SimpleNamespace
import time
import pytest

from service1.display_control import _browser_fullscreen_projection, _display_read_projection_from_rows

@pytest.mark.parametrize("state", ["fullscreen", "windowed"])
def test_recent_verified_measurement_projects_correctly(state):
    runtime = {
        "state": "running", "browser_pid": 123,
        "browser_fullscreen": state,
        "browser_fullscreen_updated_at": time.time(),
    }
    assert _browser_fullscreen_projection(runtime) == state
    row = SimpleNamespace(
        status_payload={"runtime": runtime},
        reported_at=datetime.now(timezone.utc).replace(tzinfo=None),
        agent_version="1.3.40",
    )
    assert _display_read_projection_from_rows(None, row, None)["browser_fullscreen"] == state


@pytest.mark.parametrize("mutation", [
    {"state": "stopped"},
    {"state": "countdown"},
    {"browser_pid": None},
    {"browser_fullscreen": "invalid"},
    {"browser_fullscreen_updated_at": 1.0},
    {"browser_fullscreen_updated_at": None},
    {"browser_fullscreen_updated_at": time.time() + 120},
])
def test_stopped_unmeasured_or_expired_status_fails_closed(mutation):
    runtime = {
        "state": "running", "browser_pid": 123,
        "browser_fullscreen": "fullscreen", "browser_fullscreen_updated_at": time.time(),
        **mutation,
    }
    assert _browser_fullscreen_projection(runtime) == "unknown"


def test_calendar_power_off_must_not_claim_fullscreen():
    row = SimpleNamespace(
        status_payload={
            "runtime": {
                "state": "running", "browser_pid": 123,
                "browser_fullscreen": "fullscreen", "browser_fullscreen_updated_at": time.time(),
            },
            "display_power": {"state": "off", "updated_at": time.time()},
        },
        reported_at=datetime.now(timezone.utc).replace(tzinfo=None),
        agent_version="1.3.40",
    )
    assert _display_read_projection_from_rows(None, row, None)["browser_fullscreen"] == "unknown"
