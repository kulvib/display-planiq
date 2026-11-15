# PlanIQ Display – 61B-1, inaktiv releaseplanlægning

**Base:** `display-planiq-main(20261115-165311).zip` – 61A i produktion.
**Formål:** Én samlet kodeændring til separat branch. **Ingen produktion, installering, pilot, cutover eller release 1245 ændres af pakken.**

## Faktisk ændret

- `backend/service1/routers/clientflow_release_administration.py`: superadmin kan gennemgå, pause, genoptage eller annullere udrulnings**planer**, altid med password-genbekræftelse, rate-limit, pessimistic row locks, revisionskontrol og auditlog. Gennemgang betyder **ikke releasegodkendelse**. Wave og target forbliver `draft`; pause sætter udelukkende wave til `paused`; annullering tilbagekalder de stadig inaktive targets.
- Kandidatklienter vælges blandt aktive, godkendte klienter, og kildeversion er en eksplicit planoplysning. Intet pilot-ID hardkodes i den nye planlægningsfunktion. Et klient-ID eller en version i en plan er **ikke** fysisk verificeret.
- `frontend/src/pages/adminpages/ClientFlowReleaseAdministration.jsx`: synlig adskillelse mellem gennemgået plan og en faktisk godkendt deployment. Alle tre databasegates er verificeret `false` før adminhandlinger kan vises. Ingen ny miljøvariabel.
- `backend/tests/test_clientflow_release_admin_61a_http.py` og `backend/tests/test_clientflow_release_admin_61b_source.py`: regression og negative tests for authentication, drift, stale revisions, expired plan, korrupt target, fejlagtig pilotaccept og uændrede runtime-gates.
- `SHA256SUMS.txt` ajourføres for ændrede filer; eksisterende historiske kilde- og releasesignaturer ændres ikke.

## Ufravigelige sikkerhedsgrænser

1. `cutover_enabled=false`, `fresh_install_open=false`, `fleet_open=false` er stadig påkrævet.
2. `authorization_active=false` og `physical_pilot_accepted=false` i admin-kontrakten; ingen godkendelse eller forbrug af target og ingen deployment-creation.
3. Wave-review registreres i eksisterende `approved_at`/`approved_by_user_id` felter alene som **plangennemgang**; `state` holdes `draft` og targets `draft`. De felter må **aldrig alene** tolkes som deployment-autorisation ved senere cutover.
4. Tidligere 59A/60A/61A migrationer og deres SHA-pins er uændrede; ingen DDL eller datamigration i 61B-1.
5. Ingen ændringer til kryptografisk releasegodkendelse, fysisk pilotaccept, klient-runtime, OS/firmware-opdaterere, kiosk eller Render-miljø.

## Teststatus og releasegate

Indholdet skal igennem fuld GitHub CI (herunder PostgreSQL-migrationer, HTTP-integrationstests, SHA256-manifest, frontend-build og release-security). Eventuelle tests, som ikke kan køres lokalt, skal forblive **uverificerede** indtil CI har bekræftet dem. **Ingen merge eller Render-deployment, hvis en eneste gate fejler.** Efter grøn CI: separat smoke-/produktionskontrol og først derefter 61B-2-klientdesign/udrulningsgate.

## Installation via GitHub

Opret separat branch fra præcis den vedhæftede `main`-base, fx `feature/display-61b1-inert-release-planning-20261115`, og læg alle ZIP'ens stifiler over i samme sti. Brug ikke ZIP'en som et komplet repo. Bevar alle øvrige filer fra `main`, og merge ikke uden grøn CI.
