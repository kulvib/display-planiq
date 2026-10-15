"""Read-only calendar restart evidence for Control Room, without extra DB queries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

LOCAL_TIMEZONE = ZoneInfo("Europe/Copenhagen")


def _utc(value: datetime | None) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def daily_reboot_projection(
    calendar: dict[str, Any] | None,
    *,
    boot_id: str | None,
    boot_observed_at: datetime | None,
    online: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Require a new Status boot ID before confirming a calendar-requested reboot."""
    current = _utc(now) or datetime.now(timezone.utc)
    boot_seen = _utc(boot_observed_at)
    last_boot = boot_seen.isoformat() if boot_seen is not None else None
    result: dict[str, Any] = {
        "state": "unknown",
        "source": None,
        "last_boot_at": last_boot,
        "verified_at": None,
        "error": None,
    }
    if not online or not isinstance(calendar, dict):
        return result
    try:
        updated = datetime.fromtimestamp(float(calendar["updated_at"]), timezone.utc)
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return result
    if updated < current - timedelta(minutes=3) or updated > current + timedelta(minutes=1):
        return result
    daily = calendar.get("daily_reboot")
    if not isinstance(daily, dict) or daily.get("schema_version") != 1:
        return result
    today = current.astimezone(LOCAL_TIMEZONE).date().isoformat()
    if daily.get("day") != today:
        return result

    boot_today = bool(
        boot_id
        and boot_seen
        and boot_seen.astimezone(LOCAL_TIMEZONE).date().isoformat() == today
    )
    try:
        requested_epoch = float(daily.get("requested_at") or 0)
        requested = (
            datetime.fromtimestamp(requested_epoch, timezone.utc)
            if requested_epoch > 0
            else None
        )
    except (ValueError, TypeError, OverflowError, OSError):
        requested = None

    request_today = daily.get("request_day") == today
    earlier_boot = str(daily.get("request_boot_id") or "")
    verified_calendar = bool(
        request_today
        and requested
        and earlier_boot
        and boot_id
        and earlier_boot != boot_id
        and boot_seen
        and boot_seen >= requested
    )
    if verified_calendar:
        result.update(state="completed", source="calendar", verified_at=last_boot)
    elif boot_today and not (request_today and earlier_boot and boot_id == earlier_boot):
        result.update(state="completed", source="other", verified_at=last_boot)
    elif daily.get("scheduled_today") is False:
        result["state"] = "not_scheduled"
    elif daily.get("scheduled_today") is True:
        if request_today and requested and current - requested > timedelta(minutes=3):
            result.update(state="error", error=daily.get("error") or "reboot_not_observed")
        else:
            result["state"] = "pending"
    return result
