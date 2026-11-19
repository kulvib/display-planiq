# PlanIQ Display · Fase 63D-11 · 1247, retention, autorisation og fysisk pilot

**Status: KODEKANDIDAT – INGEN RENDER-PUBLICERING, KATALOGPROMOVERING ELLER KLIENTOPDATERING VED MERGE.**

## Fastlåst grundlag

- Kilde: main efter 63D-10 (`22a8a873899fe736018e8238f4b2ec4bb896f6a2`).
- Approved 1247 GitHub TAR: `clientflow-1.3.46-seq-1247`, SHA-256 `3d6df5ec096a5713866943a67d9f88bba3fc6287458d0ea2f616bd41e42db150`, **223692800 bytes**.
- Kandidat: `d60d63ba8daf182efd97c8a28183ddbde8f258ce3429e3c3bfe31bcb00f9d258`; installer: `e1f153643d34db81200bbb106069a89353fb918b9dce9435d10c2ce6aea4e864`.
- Approval: `CF-1.3.46-1247-20261119-22a8a873-d60d63ba`, GitHub approval run `44609878344`.
- Godkendt GitHub-releasearkiv: `clientflow-1.3.46-1247-approved-transport` (ikke et Render deployment).
- Render release-store ved observeret audit: tre godkendte og verificerede TAR-filer (1244, 1245, 1246), 868003840 bytes ledige, ingen ugyldige; audit køres som `display_app`, **ikke** root.
- Klient Viborg1, backend-ID 3, senest manuelt observerede aktive version **1.3.45/1246**.

## Samlet kildeændring

1. Ret historisk `1244`-reset-check i den almindelige *tre-release* retention. Den gamle ekstra 1244-gate for 4–6 pakker bevares uændret. Den aktive 1245-katalogpin, nyinstallationssuspension, ukendte offlineafhængigheder og begge eksplicitte prune-samtykker må aldrig omgås.
2. Tilføj skrivebeskyttede operator-gates: release-store/retention-preflight samt afgrænset Neon-dependencyaudit i en `SET TRANSACTION READ ONLY`-transaktion. De er ikke en backupattestation og autoriserer ikke sletning.
3. Lås eksakte 1247 TAR-, source-, candidate-, installer- og approval-værdier i en ny kildekontrolleret godkendelsesfil.
4. Tilføj separat, SHA-256-fastlåst **staged** 1247-katalog med tre valg (1245 stabil, 1246 supporteret, 1247 update-only). `clientflow_release_catalog.json` på main efter denne kodeændring forbliver **uændret på 1246**.
5. Forbered klientbundet, engangs, databasebaseret 1246→1247-rute. Eksakt Viborg1/ID 3, frisk aktiv Status-identitet (`1.3.45`), aktiv unik Update-identitet, superadmin + adgangskodegenbekræftelse, klient- og releasekontrollåse, inaktiv fleet/fresh-install/cutover, signed og fysisk publiceret TAR, revisionsmatch og ingen tidligere 1247-bestilling. Ingen Render-pilotflag.
6. Frontend validerer *præcist* begge godkendte pilotidentiteter; 1247-panelet vises kun efter en særskilt, gyldig katalogpromovering. Ældre 1246-panel forbliver særskilt. Hver knap kræver eksplicit brugerhandling – ingen automatiske baggrundskald.
7. Forhindr at en senere main-commit kan bygge *nye* 1247-bytes under den allerede godkendte 1247-identitet. `release-build.yml` afviser nyt source-SHA med samme versions-/sekvenspar.

## Sikker driftsrækkefølge efter grøn GitHub CI og Render deployment

**Fase A – kun aflæsning.** Køres fra Render Shell, mens backend er stabil, og ingen deployment er i gang:

```bash
cd /opt/display
gosu display_app python3 scripts/phase63d11_preflight.py \
  --artifact-dir "$CLIENTFLOW_RELEASE_ARTIFACT_DIR"
gosu display_app python3 scripts/phase63d11_dependency_audit.py
```

- **STOP** hvis status, permissions, hash, registrerede klienter eller aktive deployments ikke kan verificeres.
- DB-audit kan **ikke** bevise, at offline/udgåede maskiner eller alle recovery-afhængigheder er fjernet. En aktuel fysisk klient-/backupafklaring skal foretages separat.
- Indhent verificeret, **uafhængig ekstern** 1244-backup med samme TAR-SHA. En kopi på den samme Render-disk er ikke i sig selv et eksternt recoverybevis.
- Kør aldrig `rm`, `chmod -R`, `chown -R`, ukontrolleret `scp`-overwrite eller generisk release-prune.

**Fase B – separat destruktiv operatørbeslutning.** Først efter dokumenteret backup, offline-dependency review og særskilt accept kan præcis én ældste TAR (1244) fjernes med den eksisterende `prune_clientflow_release_retention.py` og begge eksplicitte operatørattestationer. Retention scripts sletter ellers intet. Dette kode-merge udfører **ikke** den handling.

**Fase C – immutable publicering.** Når release-store har to verificerede TAR'er, kan den originale GitHub-godkendte 1247 TAR hentes og verificeres mod `3d6d...db150`, størrelse 223692800, signatur/manifest og approval. Først derefter køres eksisterende `publish_clientflow_release.py` via `display_app`, med read-only preflight, uforanderlig publicering og efterfølgende ny read-only audit. Ingen anden version, kandidat eller GitHub Actions artifact-ZIP må publiceres.

**Fase D – særskilt katalogreview.** Når `1245/1246/1247` alle findes og er verificerede i Render, opret en *ny, reviewet* PR, der promoverer præcis `clientflow_release_catalog_1247_pilot.stage.json` til aktivt katalog. Ingen 1247-stable/default/fresh-install eller bred release.

**Fase E – Viborg1 pilot.** Først efter D kan superadmin eksplicit vælge og autorisere én 1246→1247-pilot i releaseadministrationen, med ny reauth, revision, frisk klientstatus, hash og fysisk recoveryklarhed. Dette opretter en **faktisk** deployment – ikke blot en kladde. Hold stadig Render backend stabil uden redeploy under måling. Test input-lane, down/up/drag/tastatur, WS og HTTPS-fallback, JPEG relay, HLS-manifest/faktisk afspilningsforsinkelse, DB-kald og recovery. Ved fejl: stop fysisk, dokumentér; ingen bred udrulning og ingen automatisk rollback.

## Krav der forbliver uændrede

- Ingen nye Render Environment-variabler, ingen credentialrotation, ingen klientgeninstallation.
- 1245 er fortsat fælles stable/default/fresh-install; `CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1` bevares.
- Ingen ændringer i historiske 1244/1245/1246 TAR-filer, godkendelsesreferencer eller releasepolitik med maks. tre godkendte aktivt lagrede TAR-filer.
- Ingen schemaændringer eller nye Neon-tabeller; kun en eksplicit, lille, read-only operatoraudit.
- Alle source-/build-, sikkerheds- og integrationskontroller skal være grønne i GitHub. Integrationstests, der kræver SQLModel/Node 24, kan ikke erstattes af lokale kildekontroller.
