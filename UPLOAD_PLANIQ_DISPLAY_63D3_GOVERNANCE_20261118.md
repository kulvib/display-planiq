# PlanIQ Display · Fase 63D-3 · Branch-upload

**Branch:** `feature/display-63d3-governance-lifecycle-20261118`

**Base:** GitHub `main` `0b80502e5dd9b9ebd90af74a97955ef94f446ad8` fra `display-planiq-main(20261118-104531).zip`.

Upload ZIP-pakkens filer til en **ny branch fra denne base** med stierne bevaret. **Ingen eksisterende filer slettes.** Se teknisk scope, cutover-gates og accepteringskrav i `docs/PLANIQ_DISPLAY_63D3_GOVERNANCE_EVIDENCE_WAVE_LIFECYCLE_20261118.md`.

Pakken indeholder isoleret release-governance til fysisk pilotaccept (to uafhængige mennesker), review-to-approval, pause, resume, stop, terminal afstemning, audit og race-/rollback-tests. Den **ændrer ikke** releasecatalog, Render-miljø, databaseflags, produktionsrouters, klientruntime eller signerede artifacts. Den er derfor ikke en releasegodkendelse.

**CI-gate:** Kræv samtlige checks grønne; backend-pakken indeholder 63D-3 SQLModel-tests, og en separat PostgreSQL-racetest må kun køre mod den disposable lokale CI-database (`GITHUB_ACTIONS=true`, `planiq_ci` på `127.0.0.1:5432`). Kør desuden eksisterende clientflow source freeze, full frontend-tests og release source readiness-gate.

**Herefter:** Bekræft merge og normal Render-deploy, men **start ikke** runtime-input transport, release signing, 1246 cutover eller fysisk opdatering som følge af dette merge alene. Den kommende live HTTP-integration kræver godkendt signeret kandidat, fysisk pilot, stærk reauth og særskilt godkendelse.
