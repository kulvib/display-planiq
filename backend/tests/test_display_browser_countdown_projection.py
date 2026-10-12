"""Structured seconds for the existing Display read projection; never DB-tick."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from service1 import display_control


def sample(*, seconds=10, age_seconds=0, reason="system_start"):
    return {
        "state": "countdown", "step": "countdown", "countdown_remaining": seconds,
        "countdown_reason": reason,
        "updated_at": (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).timestamp(),
    }


def test_browser_countdown_structured_time_and_reason():
    result = display_control._browser_countdown_projection(sample(seconds=8, age_seconds=2, reason="reset_browser"))
    assert result is not None
    assert result["remaining_seconds"] == 8
    assert result["reason"] == "reset_browser"
    assert result["step"] == "countdown"
    assert datetime.fromisoformat(result["ends_at"].replace("Z", "+00:00")) > datetime.now(timezone.utc)
    assert datetime.fromisoformat(result["server_now"].replace("Z", "+00:00")) <= datetime.now(timezone.utc)


def test_old_or_invalid_statuses_do_not_restart_countdown():
    assert display_control._browser_countdown_projection(sample(age_seconds=15)) is None
    assert display_control._browser_countdown_projection({**sample(), "state": "running"}) is None
    assert display_control._browser_countdown_projection({**sample(), "countdown_remaining": 0}) is None
    assert display_control._browser_countdown_projection({**sample(), "countdown_remaining": 10000}) is None
    assert display_control._browser_countdown_projection({**sample(), "updated_at": "broken"}) is None
    assert display_control._browser_countdown_projection(sample(age_seconds=-5)) is None


def test_countdown_only_projects_from_already_loaded_display_state():
    now = datetime.now(timezone.utc)
    status = SimpleNamespace(status_payload={"runtime": sample(seconds=7)}, reported_at=now, agent_version="1.3.35")
    projection = display_control._display_read_projection_from_rows(None, status, None)
    assert projection["browser_countdown"]["remaining_seconds"] == 7
    assert projection["chrome_step"] == "countdown"
    # A more recent screen power report supersedes countdown.
    status.status_payload["display_power"] = {"state": "off", "updated_at": now.timestamp() + 1}
    projection = display_control._display_read_projection_from_rows(None, status, None)
    assert projection["browser_countdown"] is None


def test_browser_read_uses_existing_projection_and_stays_null_when_inactive():
    state = {"state": "running", "updated_at": datetime.now(timezone.utc).timestamp(), "browser_pid": 1234}
    status = SimpleNamespace(status_payload={"runtime": state}, reported_at=datetime.now(timezone.utc), agent_version="1.3.35")
    projection = display_control._display_read_projection_from_rows(None, status, None)
    assert projection["browser_countdown"] is None
