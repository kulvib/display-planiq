# PlanIQ Display · 62B · Backup- og recoverybevis før arkitekturændring

**Dato:** 17. november 2026. **Grundlag:** `display-planiq-main(20261117-110932).zip`, GitHub `main` `ba14ad180142233b0c00bd4fbade2a159f86764f`.

## Hvad er leveret samlet?

1. **Sikker, manuel backup-staging:** `scripts/display_62b_backup_evidence.py` er en operatørstyret eksport af den lokale PostgreSQL 18-database (`pg_dump` custom format, Unix-socket og `display_app` peer-auth) samt alle genkendelige immutable release-TAR'er i den aktuelle `store/`. Kilden kontrolleres først med 62A's read-only SHA256/PGDATA-preflight. Destinationsmappen skal eksistere, være privat og være *uden for* kildemounten; nye filer oprettes med `0600`, mappen med `0700`. Eksporten er **ikke** aktiv i backend/Render, og udføres **aldrig automatisk**.
2. **Skrivebeskyttet kontrol af staging:** `--verify-stage` kontrollerer alle registrerede filer igen mod SHA256, størrelse, filtyper og inventory. Forkerte checksums, symlinks, ukendte release-TAR'er, forfalskede sikkerhedsgates eller manglende filer giver **STOP**. Denne kontrol validerer **bytes**, ikke at data faktisk kan gendannes.
3. **Faktisk isoleret PostgreSQL-restore i CI-fixture:** Den eksisterende `.github/workflows/single-node-smoke.yml` får et ekstra trin, der eksporterer den *disposable* lokale CI-database, genindlæser den i en **anden**, netværksisoleret PostgreSQL 18-instans og kontrollerer både historiske data (`ci_persistence_marker.proof = 42`) og migreringshoved (`alembic_version`). Anonyme restore-volumes ryddes op, og ingen dump uploades som Actions-artefakt. Workflowet skal stadig udløses og bestå i GitHub; kilde-/unit-tests alene er ikke bevis for dets gennemførsel.
4. **Offline-produktionsrestore som særskilt fremtidig operatorgate:** `scripts/display_62b_offline_restore.sh --verified-stage <sti>` starter kun efter hashverifikation, kun i en separat lokal Docker-sandkasse med `--network none` og en **ny** PostgreSQL 18. Resultatet kontrollerer den låste 1.3.44/1245-releasepolitik, alle tre lukkede DB-gates og migrationstabellen. Container og volume fjernes efter kørslen. **Må ikke køres på live Display-host.** Det er ikke blevet kørt mod produktionsdata i denne leverance.
5. Negative tests dækker manipuleret dump, manglende release, symlinks, usikker destinationsmappe, dublet i inventory, utilsigtet medtagelse af øvrige filer samt forfalsket restore-/cutoverstatus.

## Beskyttet produktion og nul automatiske ændringer

- **Render:** Aktiv backend er den ene Docker-service med lokal PostgreSQL 18 og signerede ClientFlow-TAR'er på samme persistente mount, `/var/data/clientflow-release-artifacts`. `backend/scripts/start_single_node.sh` og `render-single-node.yaml` **ændres ikke** i 62B.
- **Ingen automatisk backup eller databasekopi**, intet nyt PostgreSQL-endpoint, ingen udvidede live-skemaadgange, ingen ændringer i auth/MFA, ingen eksterne netværkskald fra backend.
- **Ingen** migrationsfiler, releasegodkendelse, fysisk pilotaccept, rollbackautorisation, nye deployment-handlinger eller ændring af releaseidentiteten. `1.3.44/1245` er stabil; `1.3.45/1246` er fortsat en usigneret kandidat.
- En backup-kvittering er **ikke** recovery-godkendelse. Scriptets manifest har derfor eksplicit `backup_offsite_verified=false`, `backup_restored_to_isolated_postgres=false`, `database_cutover_authorized=false` og `deployment_authorized=false`.
- `62B` løser **ikke** de midlertidige HTTP 502-svar under Render redeployment; den nødvendige ombygning til en stateless API + ekstern DB/release storage kræver separat arkitekturvalg, budget og sikker migration.

## Før operatøren overhovedet må tage en produktionskopi

1. Godkend omfang og sikker placering af databasekopier og signerede releases; backup indeholder brugeroplysninger, credentials og sikkerhedsfølsomt materiale. Eksport må **aldrig** vedhæftes en ChatGPT-samtale, uploades til GitHub Actions, lægges på GitHub eller i et almindeligt cloud-delingslink. Brug krypteret transport og adgangsbegrænset, krypteret destination med dokumenteret slettepolitik.
2. Kontrollér den private staging-mappe, ledig kapacitet, kapacitet til mindst release-TAR'er **plus** DB-export og krypteret off-site-copy. Opsæt separat recovery-vindue; undgå samtidig releasepromotion/backup, og bevar eksisterende services. Den logiske `pg_dump`-snapshot og de kopierede TAR'er er ikke ét atomisk snapshot på tværs af DB og filsystem. For officiel recovery skal releasekataloget derfor fryses/afstemmes og genverificeres efter kopien.
3. Godkend sikkerheds- og driftsopsætningen **før** eksplicit manuelt `--capture`; scriptet indeholder ingen tidsplan, cron eller automatisk produktionskørsel. Mappens indehold er *staging*, ikke off-site eller disaster-recovery-bevis.
4. Kopiér den beskyttede staging til en **separat, dokumenteret krypteret off-site destination**. Kontrollér SHA256 på den modtagende side. Udfør `--verify-stage` og derefter den isolerede restore på en kontrolleret offline-maskine. Kontrollér desuden releasefilernes signaturer, aktiv releasekatalog, adgangsrettigheder, nødvendige service-credentials, initialiseringsrutiner og om en klient igen kan etablere sin session efter restore. Sidstnævnte kræver godkendt, fysisk test – ikke bare PostgreSQL-restore.
5. Kvittering for gendannelse skal være en **separat, manuelt gennemgået artefaktattestation**. CI-testen gælder alene en syntetisk database, ikke produktionsdata eller opnået RPO/RTO.

## Eksempler – skal ikke køres mod produktion uden særskilt godkendelse

På en autoriseret host med lokal PostgreSQL-peer-auth, **efter** sikker staging og transport er besluttet:

```bash
# Udgangspunkt: mounten findes; /secure/offline-stage-root er en privat,
# godkendt destination UDEN FOR live Render-disken.
python3 /opt/display/scripts/display_62b_backup_evidence.py \
  --capture \
  --mount /var/data/clientflow-release-artifacts \
  --stage-parent /secure/offline-stage-root \
  --release-id clientflow-1.3.44-seq-1245 \
  --expected-sha256 28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5 \
  --expected-size 223610880
```

På en **anden, offline** maskine med en privat kopi og Docker:

```bash
python3 scripts/display_62b_backup_evidence.py \
  --verify-stage /secure/private-copied-stage/planiq-display-62b-YYYYMMDDTHHMMSSZ-XXXXXXXXXXXX
bash scripts/display_62b_offline_restore.sh --verified-stage \
  /secure/private-copied-stage/planiq-display-62b-YYYYMMDDTHHMMSSZ-XXXXXXXXXXXX
```

Begge handlinger er separate fra CI og kan returnere **STOP**. De skal ikke udføres på nuværende trin, før arkitektur, destination, databeskyttelse og tilbageførselsmulighed er godkendt.

## Driftsvalg til næste gate

| Vej | Fordel | Ulempe/risiko | Godkendelseskrav |
| --- | --- | --- | --- |
| Behold single-node og acceptér korte deployafbrydelser | Færre faste driftskomponenter; minimumsændring | HTTP 502 under Render-disk-deploy og begrænset HA | Reelle backup-/restoreøvelser, bedre deploykommunikation og recoveryberedskab |
| Ekstern managed PostgreSQL, objektlager til immutable signerede releases, stateless backend | Potentiale for zero-downtime og horisontal API-skalering | Datamigration, driftsomkostninger, auth/release-autoritet og en grundig rollbackstrategi | Isoleret restore, komplet kost-/risikovurdering, read-only parallel kontrol, eksplicit cutover-gate, fysisk pilot |

Der foreligger endnu **ikke** reelle målinger af RPO, RTO eller økonomiske konsekvenser for valget. Beslutningen må ikke bygges på antagelser om, at en ny cloud-database automatisk bliver billigere eller hurtigere. 62B er en forudsætning for den beslutning, ikke et stille migrationsskridt.
