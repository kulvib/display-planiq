PlanIQ Display — 61B-2G offline release-source gate, 2026-11-16

Baseline main: b891cd68d08acc6811456043e50a5151fe15511b
Branch: feature/display-61b2g-release-source-readiness-20261116

Files in this patch:
  SHA256SUMS.txt
  scripts/clientflow_61b2g_release_source_gate.py
  backend/tests/test_clientflow_61b2g_release_source_gate.py
  docs/CLIENTFLOW_61B2G_RELEASE_SOURCE_GATE_20261116.md
  README_61B2G_RELEASE_SOURCE_GATE_20261116.txt

This does NOT bump version, build/sign/approve a release, deploy a client,
change Render or DB gates, or permit physical installation.

Run:
  python scripts/clientflow_61b2g_release_source_gate.py --repo-root . --source-only
  python scripts/clientflow_61b2g_release_source_gate.py --repo-root .

The first command should PASS current source; the second deliberately STOPs
while version and sequence remain 1.3.44 / 1245. See docs for separation of
source, independently built candidate, approval, and physical acceptance.
