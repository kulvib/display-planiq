PlanIQ Display 61B-2F — sikkerhed, manuel rollback, fysisk preflight (kun kildekode)

Canonical baseline: display-planiq-main(20261116-161745).zip
Main at baseline: dc5a8cb6c1c2070c8ab5a5abdb1b55f0c3d0f9d4
Branch: feature/display-61b2f-manual-rollback-pilot-preflight-20261116

Kopier alle filer i denne ZIP til samme relative sti i en ny branch fra main.
SLET IKKE eksisterende filer. Ingen production deploy, ingen ny signerede
releases, ingen klientinstallationer eller ændrede release-/DB-gates.

Indhold:
- client/release/lib/clientflow_release/transaction.py
- scripts/clientflow_61b2f_pilot_preflight_readonly.py
- backend/tests/test_clientflow_61b2f_manual_rollback_install_lock.py
- backend/tests/test_clientflow_61b2f_readonly_pilot_preflight.py
- docs/CLIENTFLOW_61B2F_MANUAL_ROLLBACK_PILOT_PREFLIGHT_20261116.md
- SHA256SUMS.txt (fuld ny manifest)

CI er sidste gate. Dokumentationen beskriver konkrete fysiske STOP-gates.
