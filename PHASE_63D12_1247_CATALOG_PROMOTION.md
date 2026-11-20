# PlanIQ Display · Fase 63D-12 · Kontrolleret 1247 katalogpromovering

## Verificerede forudsætninger, 19. november 2026

- Render Docker release-store: **1245/1246/1247**, alle verificeret af `audit_clientflow_release_retention.py` (`PASS`), ingen ugyldige filer; grænse **3**.
- 1247 TAR: `clientflow-1.3.46-seq-1247`, SHA-256 `3d6df5ec096a5713866943a67d9f88bba3fc6287458d0ea2f616bd41e42db150`, størrelse **223692800** bytes.
- Viborg1: **backend ID 3**, installeret **1.3.45/1246**. Docker PostgreSQL er `display` via Unix-socket `/run/display-postgres`, skema-head **61A**. Status-agenten rapporterer version 1.3.45.
- Kun Viborg1 er fysisk aktiv; tidligere Heidi1/ID 1 og Viborg2/ID 2 er allerede decommissioned, men tombstones/historiske DB-registreringer skal håndteres i separat gennemgået oprydning.
- Ekstern 1244-backup SHA/størrelse er verificeret, og Render 1244-TAR er præcist slettet via godkendt retention-gate.

## Den samlede kildeændring

1. Kopiér **de eksakte bytes** fra `clientflow_release_catalog_1247_pilot.stage.json` til aktiv `clientflow_release_catalog.json`. Ret ikke stage eller dens immutable approval-lås.
2. Udvid den ældre 63D-6 source-gate til at genkende **kun eksakt SHA-fastlåst 1247-stage med godkendt 1247 approval**. Bevar både 1245 og 1246 som historiske, særskilt sikre valgmuligheder. Ingen generisk sekvensaccept.
3. Fasthold uændret stable/default `1.3.44/1245`, `max_selectable_versions=3`, `max_installable_versions=1`, og `1247.installable=false`, `install_modes=[in_place_update]`, `rollback_allowed=false`, kildekrav **1.3.45**.
4. Opdatér alle tidsbundne kilde- og regressionsassertions, og tilføj negative tests for udvidet fresh-install, rollback, mutation af historisk release, ugyldigt katalog og ændret godkendelse.
5. Rehash `SHA256SUMS.txt` for alle ændrede filer; ingen ændring af release source-input, TAR, klient-runtime, credentials, database, miljøvariabler eller installer.

## Arbejdsgang

**PR/CI:** Upload den sammenhængende branch, gennemfør alle GitHub-gates og merge først efter grøn CI. `client/VERSION` forbliver **1.3.46**, release sequence **1247**; byg aldrig en ny godkendt 1247 TAR fra en senere GitHub-commit.

**Render:** Redeploy backend fra merged `main`, *uden* artifact-publicering eller ændrede environment-flags. Kontroller efterfølgende:

```bash
cd /opt/display
gosu display_app python3 scripts/audit_clientflow_release_retention.py
```

Kataloget skal have sekvens 1247 med 1245 stable/default, 1246 supported og 1247 supported, udelukkende update-only. `CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1` skal fortsat være sat. `clientflow_release_control` i lokal Docker-PostgreSQL skal fortsat have `cutover_enabled=false`, `fleet_open=false`, `fresh_install_open=false`.

**Pilot – separat manuel fase:** Åbn Releaseadministrationen som superadmin. Kontrollér Viborg1 ID 3, frisk Status 1.3.45, unik Update-credential, ingen uafklaret recovery, ingen tidligere 1247-deployment, og fysisk recoveryplan. Kør først derefter én eksplicit, adgangskode-genbekræftet 1246→1247-autorisation, og måle Remote Desktop/WebSocket/HTTPS/HLS. Katalogpromovering eller grønt CI er **ikke** autorisation til deployment.

**Permanent sletning af gamle ID 1/2:** Indgår ikke i denne kodeændring; decommissioned credentials skal fortsat være revoked. Særligt protected tombstone-historik kræver separat sikker, rollback-vurderet plan og testet FK-oprydning.
