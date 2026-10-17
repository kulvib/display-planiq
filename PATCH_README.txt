PlanIQ Display — Heidi1 acceptance follow-up (2026-10-17)
Source of truth: user-provided display-planiq-main(20261017-112100).zip
Suggested branch: fix/clientflow-heidi1-gtk4-clipboard-consent-flash

Change-only ZIP; extract at repository root on that branch.
CHANGED FILES:
- client/libexec/local-gui
- client/runtime/clientflow_runtime/browser_guard.py
- backend/tests/test_clientflow_1239_calendar_gui_acceptance.py
- scripts/tests/test_clientflow_browser_guard_consent_no_flash.py (new)
- scripts/tests/test_clientflow_physical_failure_fixes_1221.py
- scripts/tests/test_clientflow_local_ux_legacy119.py

CHANGESET:
1. GTK4 PyGObject clipboard API fix: set(value), not unavailable set_text().
   Preserve clipboard read-back and gracefully report any binding errors.
2. Prevent Browser Guard from deliberately exposing cookie consent overlays
   on timed page reloads: do not remove guard CSS, force CSS-visible, or
   scroll accept buttons into view while attempting the existing accept flow.
   Existing fallback hide behavior remains. This does NOT prove unknown
   third-party consent implementation works: test on Heidi1 with exact site.
3. Harden execution and legacy source contracts to require the actual GTK4 API.
   Do not weaken unrelated parity/security gates.

LOCAL VALIDATION:
- Targeted suites run; full GitHub CI remains final gate.
- Browser cookie flash must be retested physically on Heidi1.

RELEASE SAFETY:
- Do not modify already approved/signed clientflow-1.3.38-seq-1239.tar.
- Source change requires normal validated and approved release/update transport.
- No change to Render/Neon database, no user secrets, no installer modification.
