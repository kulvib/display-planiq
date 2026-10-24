"""Allowlisted, credential-free operational fault evidence from canonical domains.

Only statuses actually reported by an authenticated Status/Display/System agent
are considered. Missing fields, unknown states and ordinary offline operation
must never be interpreted as either a fault or proof of recovery.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IncidentSignal:
    code: str
    title: str
    severity: str = "error"


# Never persist freeform agent error/message fields: they may contain passwords,
# network names, URLs, terminal output or otherwise sensitive diagnostics.
SERVICE_UNITS = {
    "clientflow-status-agent.service": "Status-agent",
    "clientflow-calendar.service": "Kalender",
    "clientflow-browser-guard.service": "Browser Guard",
    "clientflow-terminal-agent.service": "Terminal",
    "clientflow-root-terminal-broker.socket": "Administrator-terminal",
    "clientflow-remote-desktop-agent.service": "Remote Desktop",
    "clientflow-livestream-producer.service": "Livestream",
    "clientflow-updater.timer": "Opdateringskontrol",
    "clientflow-system-broker.socket": "System-broker",
}
_BAD_STATES = {"error", "failed", "missing", "not-found", "fejl"}


def signals_for_report(domain: str, observed_state: str, payload: Any) -> dict[str, IncidentSignal] | None:
    """Return fault state when evidence is complete; None when untrustworthy.

    An empty result is strong *domain-specific* recovery evidence, but only for
    reports where the relevant subsystem is observable. A partial heartbeat
    cannot clear unrelated active incidents.
    """
    if domain not in {"status", "display", "system"} or not isinstance(payload, dict):
        return None
    issues: dict[str, IncidentSignal] = {}

    if str(observed_state).lower() in _BAD_STATES:
        issues[f"{domain}_agent_failed"] = IncidentSignal(
            f"{domain}_agent_failed", f"{domain.capitalize()}-agent rapporterer fejl"
        )

    if domain == "status":
        services = payload.get("services")
        if not isinstance(services, dict) and not any(isinstance(payload.get(key), bool) for key in ("ntp_enabled", "ntp_synchronized")):
            return issues or None
        if isinstance(services, dict):
            for unit, title in SERVICE_UNITS.items():
                if str(services.get(unit) or "").strip().lower() in _BAD_STATES:
                    code = "service_" + unit.replace(".", "_").replace("-", "_")
                    issues[code] = IncidentSignal(code, f"{title}-service fejlede")
        if payload.get("ntp_enabled") is False or payload.get("ntp_synchronized") is False:
            issues["ntp_not_synchronized"] = IncidentSignal(
                "ntp_not_synchronized", "NTP eller tidssynkronisering fejlede", "critical"
            )
        return issues

    if domain == "display":
        runtime = payload.get("runtime")
        lockdown = payload.get("kiosk_lockdown")
        if not isinstance(runtime, dict) and not isinstance(lockdown, dict):
            return issues or None
        if isinstance(runtime, dict) and str(runtime.get("state") or "").strip().lower() in _BAD_STATES:
            issues["browser_runtime_failed"] = IncidentSignal(
                "browser_runtime_failed", "Kioskbrowser rapporterer fejl"
            )
        if isinstance(lockdown, dict) and str(lockdown.get("status") or "").strip().lower() in {"error", "failed", "rollback", "fejl"}:
            issues["kiosk_lockdown_failed"] = IncidentSignal(
                "kiosk_lockdown_failed", "Kiosk-lockdown fejlede", "critical"
            )
        # waiting_internet is intentional fail-closed operation, never a fault.
        return issues

    if domain == "system":
        if not isinstance(payload.get("broker_socket"), bool) and not isinstance(payload.get("firmware"), dict):
            return issues or None
        if payload.get("broker_socket") is False:
            issues["system_broker_unavailable"] = IncidentSignal(
                "system_broker_unavailable", "System-broker er ikke tilgængelig", "critical"
            )
        firmware = payload.get("firmware")
        if isinstance(firmware, dict) and str(firmware.get("status") or "").lower() in _BAD_STATES:
            issues["firmware_update_failed"] = IncidentSignal(
                "firmware_update_failed", "Firmware-opdatering fejlede"
            )
        return issues
    return None


def observed_codes_for_report(domain: str, payload: Any) -> set[str]:
    """Codes for which this report contains *positive or negative* evidence.

    Never infer a recovery from a missing service, missing field, empty systemctl
    output or an incomplete display/system snapshot. A report may still open
    faults supported by the evidence it does carry.
    """
    if domain not in {"status", "display", "system"} or not isinstance(payload, dict):
        return set()
    codes = {f"{domain}_agent_failed"}
    if domain == "status":
        services = payload.get("services")
        if isinstance(services, dict):
            for unit in SERVICE_UNITS:
                state = services.get(unit)
                if isinstance(state, str) and state.strip().lower() not in {"", "unknown", "not-found"}:
                    codes.add("service_" + unit.replace(".", "_").replace("-", "_"))
        if isinstance(payload.get("ntp_enabled"), bool) and isinstance(payload.get("ntp_synchronized"), bool):
            codes.add("ntp_not_synchronized")
    elif domain == "display":
        runtime = payload.get("runtime")
        if isinstance(runtime, dict) and isinstance(runtime.get("state"), str) and runtime["state"].strip().lower() not in {"", "unknown"}:
            codes.add("browser_runtime_failed")
        lockdown = payload.get("kiosk_lockdown")
        if isinstance(lockdown, dict) and isinstance(lockdown.get("status"), str) and lockdown["status"].strip().lower() not in {"", "unknown"}:
            codes.add("kiosk_lockdown_failed")
    else:
        if isinstance(payload.get("broker_socket"), bool):
            codes.add("system_broker_unavailable")
        firmware = payload.get("firmware")
        if isinstance(firmware, dict) and isinstance(firmware.get("status"), str) and firmware["status"].strip().lower() not in {"", "unknown"}:
            codes.add("firmware_update_failed")
    return codes
