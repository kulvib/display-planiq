from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from service1.calendar_daily_reboot import daily_reboot_projection

COPENHAGEN = ZoneInfo("Europe/Copenhagen")
CURRENT = datetime(2026, 10, 15, 9, 0, tzinfo=COPENHAGEN)
PREVIOUS = CURRENT - timedelta(hours=2)
REQUESTED = CURRENT - timedelta(minutes=8)


def status(*, scheduled=True, requested=True):
    return {
        "state": "running", "updated_at": CURRENT.timestamp(),
        "daily_reboot": {
            "schema_version": 1, "day": CURRENT.date().isoformat(),
            "scheduled_today": scheduled,
            "request_day": CURRENT.date().isoformat() if requested else "",
            "requested_at": REQUESTED.timestamp() if requested else 0,
            "request_boot_id": "old" if requested else "",
        }
    }


def view(data, boot="new", observed=None, online=True):
    return daily_reboot_projection(data, boot_id=boot, boot_observed_at=observed,
                                   online=online, now=CURRENT)


def test_calendar_reboot_is_verified_only_after_new_boot_id_after_request():
    ok = view(status(), observed=REQUESTED + timedelta(minutes=2))
    assert (ok["state"], ok["source"]) == ("completed", "calendar")
    assert ok["verified_at"]
    wrong_boot = view(status(), boot="old", observed=REQUESTED + timedelta(minutes=2))
    assert wrong_boot["state"] != "completed"
    stale_boot = view(status(), observed=PREVIOUS)
    assert stale_boot["state"] == "completed" and stale_boot["source"] == "other"


def test_a_noncalendar_boot_today_counts_as_boot_not_as_calendar_proof():
    data = view(status(requested=False), observed=CURRENT - timedelta(minutes=25))
    assert data["state"] == "completed" and data["source"] == "other"


def test_offline_stale_missing_and_nonscheduled_statuses_fail_closed():
    assert view(status(), observed=None, online=False)["state"] == "unknown"
    assert view(None, observed=None)["state"] == "unknown"
    stale = status()
    stale["updated_at"] = (CURRENT - timedelta(hours=1)).timestamp()
    assert view(stale)["state"] == "unknown"
    assert view(status(scheduled=False))["state"] == "not_scheduled"
    assert view(status(requested=False))["state"] == "pending"


def test_unverified_request_becomes_error_after_three_minutes():
    pending = view(status(), boot="old", observed=PREVIOUS)
    assert pending["state"] == "error"
    assert pending["error"] == "reboot_not_observed"
