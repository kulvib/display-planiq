PLANIQ DISPLAY - FASE 62D - EN SAMLET KODEPAKKE (17 NOV 2026)

Kilde: frisk main ZIP display-planiq-main(20261117-125020).zip
Kontrolleret main commit: 24ec1b602a569ced88e064870607068847be9e9e

Anbefalet branch (opret fra ovenstaende main):
feature/display-62d-recovery-coverage-deploy-evidence-20261117

Upload disse 5 repo-filer uforandret, med mappestruktur:
- scripts/display_62d_recovery_coverage.py
- scripts/display_62d_deploy_gap_report.py
- scripts/tests/test_display_62d_recovery_and_deploy_evidence.py
- docs/PLANIQ_DISPLAY_62D_RECOVERY_COVERAGE_DEPLOY_GAPS_20261117.md
- SHA256SUMS.txt

De nye scripts er KUN off-line, skrivebeskyttede operatoervaerktoejer.
Det er IKKE en live databasebackup, ikke et gennemfoert produktionsrestore,
og ikke en migrations-, installations- eller rollback-godkendelse.

Skal kontrolleres i GitHub:
- Fuld CI uden svækkede sikkerheds- og testgates
- Display single-node PostgreSQL smoke (kør manuelt hvis nødvendigt)
- SHA256SUMS.txt: 656/656
- Kontroller at /health HEAD fortsatt 200 og ikke auto-logout-race i browser

62C-produktion: Ja, main og Render live. Den afsluttende frontend-smoke
(login/inaktivitet/flere faner/kalender efter 15 minutter) afventes endnu.
MERGE/REDEPLOY 62D først efter dette er grønt og ny GitHub-CI er grøn.
Undgaa ekstra manuel Render-redeploy af samme commit: backend har auto-deploy,
og disken medfoerer nedetid for hvert deploy.

OBS! Rigtige produktionsdumps, signerede TAR-releases og private raw logs maa
ikke vedhaeftes ChatGPT, GitHub, almindelige delingslinks eller CI.
Rigtig migration eller offsite backup kraever en saerskilt operatorgodkendelse.
