# PlanIQ Display · 63D-2 · Branch-upload

**Branchnavn:** `feature/display-63d2-transactional-wave-authorization-20261118`

**Kanonisk base:** `main` fra `display-planiq-main(20261118-101520).zip`, GitHub commit `f51d06de8f81244ec1c677b9412573c26066822d`.

## Upload

Opret ny branch fra det angivne `main`-commit og upload denne pakkes filer med alle stier bevaret. Ingen filer må slettes. Se samlet scope og STOP-gates i `docs/PLANIQ_DISPLAY_63D2_TRANSACTIONAL_RELEASE_AUTHORIZATION_20261118.md`.

Ny backendmotor og PostgreSQL-racetest til fremtidig databaseautorisation. Produktionsdeployment-router og administration er **ikke** tilsluttet motoren, så CI/merge/redeploy åbner ikke releaseautorisering. Ingen Render-environmentændringer, database-cutover, signering, release-build eller Viborg1-update.

## Lokalt gennemført

- 49 dependency-free, målrettede Python-tests bestået; 2 nye SQLModel-/PostgreSQL-testmoduler blev sprunget over lokalt, fordi `sqlmodel` ikke er installeret i dette analyse-miljø. De kører i det officielle GitHub CI-miljø.
- 5 Releaseadministration-frontendtests bestået.
- Python `compileall`, ZIP-integritet og fuldt kilde-SHA-manifest kontrolleret.
- Full backend CI og PostgreSQL-racetest skal afgøres på GitHub; status her er ikke en CI-godkendelse.

## GitHub-gate

- Samtlige CI-checks skal være grønne, særligt **Backend, migrations and contracts**, hvor nye SQLModel-/PostgreSQL-tests kører mod disposable lokal database.
- Verify source-only release-gate og `SHA256SUMS.txt`-integritet.
- Kontrollér, at `1.3.44/1245` fortsat er katalogets eneste stable, `1.3.45/1246` fortsat er en usigneret kildekandidat, og alle DBAutorisationsflags stadig er lukket.
- Ved fejl **ingen merge**; ved succes merge og normal Render-deploy (kun inaktiv kode).

Denne fase fuldender endnu ikke hele ClientFlow Releases. Live DB-wave-autorisation og fysisk releaseaccept kræver separat godkendelse og dokumenteret fysisk pilot.
