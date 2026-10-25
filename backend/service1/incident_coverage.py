"""Data-minimal snapshot coverage of approved clients' canonical reports.

This is not proof that the background reconciliation loop is running. It is
read-only and does not expose credentials, raw reports or individual clients.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

DOMAINS = ("status", "display", "system")
FRESH_SECONDS = 180


def coverage_summary(approved: int, reports: Iterable[tuple[str, datetime]], *, now: datetime) -> dict:
    """Count presence of fresh, stale and missing durable reports by domain.

    Caller supplies unique (client,domain) rows for *approved, undeleted*
    clients only. Data has already been projected down to domain/timestamp;
    freeform reports are never read here.
    """
    if approved < 0:
        raise ValueError("Approved client count cannot be negative")
    reference = now.replace(tzinfo=None) if now.tzinfo is not None else now
    cutoff = reference - timedelta(seconds=FRESH_SECONDS)
    latest_allowed = reference + timedelta(seconds=5)
    counts = {domain: {"reported": 0, "fresh": 0} for domain in DOMAINS}
    for domain, reported_at in reports:
        if domain not in counts:
            continue
        counters = counts[domain]
        counters["reported"] += 1
        if isinstance(reported_at, datetime):
            stamp = reported_at.replace(tzinfo=None) if reported_at.tzinfo is not None else reported_at
            if cutoff <= stamp <= latest_allowed:
                counters["fresh"] += 1
    result = []
    for domain, count in counts.items():
        if count["reported"] > approved:
            raise ValueError("Canonical reports exceed approved client count")
        result.append({
            "domain": domain,
            "fresh": count["fresh"],
            "stale": count["reported"] - count["fresh"],
            "missing": approved - count["reported"],
        })
    return {
        "approved_clients": approved,
        "freshness_seconds": FRESH_SECONDS,
        "as_of": now.isoformat(),
        "domains": result,
    }
