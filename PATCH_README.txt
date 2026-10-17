PlanIQ Display — Heidi1 CI corrections (2026-10-17)
SOURCE: original user-provided display-planiq-main(20261017-112100).zip
OVERLAY: previously delivered PlanIQ-Display-Heidi1-clipboard-cookie-no-flash-CHANGED-ONLY.zip

Apply this small follow-up to the existing branch where the previous changed-only ZIP was already applied. Extract at repository root, replacing exactly these two files:
- SHA256SUMS.txt
- frontend/tests/displaySleepCountdownNonstale.test.mjs

CI fix 1: source checksum manifest records the exact bytes of all altered files from previous patch (plus this contract fix), and enrolls the new browser-guard test file. No test skip, no weakening of integrity checker.
CI fix 2: frontend GTK clipboard source-contract test now requires PyGObject GTK4's clipboard.set(value) and rejects clipboard.set_text(value), matching actual GTK4/Wayland runtime. It still requires icon, async read-back, and verification.

No runtime changes beyond the earlier patch. No modifications to frozen clientflow-1.3.38 bundle.
GitHub CI remains final gate.

If any source files changed on your branch after applying the previous patch, recompute SHA256SUMS from actual source rather than blindly overwriting with this file.
