PlanIQ Display · 61B-2A · CI-rettelse af GUI-kontrakttest · 16. november 2026

Brug denne ZIP som en supplerende rettelse oven på den allerede uploadede
61B-2A-branch: feature/display-61b2a-update-maintenance-20261116.

ÆNDRET:
- scripts/tests/test_clientflow_physical_failure_fixes_1221.py
  Testen forventer nu den godkendte 61B-2A-udvidelse af SYSTEM_FIELDS med
  ("Vedligeholdelse", "maintenance") umiddelbart efter Ubuntu update.
  Den kontrollerer fortsat alle oprindelige felter og deres rækkefølge eksakt.
- SHA256SUMS.txt
  Opdateret SHA256 for ovenstående testfil. Alle 588 poster passer.

INGEN ÆNDRINGER I:
- ClientFlow binær release eller signering
- Local GUI produktionskode, backend, frontend, database/migrationer
- Kiosk- eller systemopdateringsautorisation
- Fleet-, pilot-, fresh-install- og cutover-gates

LOKALE KONTROLLER PÅ SAMLET BASELINE (main fra 20261116-082716
+ den tidligere 61B-2A-patch + denne CI-rettelse):
- python -m pytest -q scripts/tests/test_clientflow_physical_failure_fixes_1221.py
  PASS 9/9
- python -m pytest -q backend/tests/test_clientflow_61b2_update_maintenance.py scripts/tests/test_clientflow_physical_failure_fixes_1221.py
  PASS 17/17
- sha256sum -c SHA256SUMS.txt
  PASS 588/588

Upload kun de to ændrede filer i deres respektive mapper til den allerede
oprettede 61B-2A-branch. Kør GitHub CI igen. Intet merge/deploy inden grøn CI.
