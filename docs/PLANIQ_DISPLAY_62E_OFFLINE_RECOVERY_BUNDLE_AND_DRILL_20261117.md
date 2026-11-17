# PlanIQ Display · 62E · Samlet offline recoverypakke og isoleret gendannelsesøvelse

**Dato:** 17. november 2026. **Source of truth:** vedhæftet `display-planiq-main(20261117-131538).zip`, GitHub `main` SHA `8b02a00c4937c02e05b06572b5dec49f3b1aa78d`. Ingen ændringer af live API, datamodel, migrations, auth/MFA, klientruntime, releasekatalog eller deployment-gates.

## Hvorfor denne samlede fase?

62B kan oprette et lokalt PostgreSQL 18 `pg_dump` sammen med TAR-filer fra **det aktive** ClientFlow store. 62D viser, at recovery også kræver de tre seneste godkendte releasehistorikker, inklusive dem der ligger i et **separat** offline arkiv. De eksisterende beviser kan derfor være korrekte, men fysisk fordelt på flere steder. En faktisk offline restore kan blive udført uden en sikret, komplet samlet kopi.

**62E lukker dette praktiske hul uden at gå i produktionen:**

1. `scripts/display_62e_offline_bundle.py --assemble` gennemfører 62B + 62D SHA256-kontrol og *kopierer* den gyldige stage og eventuelle manglende historiske TAR-filer til én **ny** privat offline bundle-mappe. Den hverken skriver til eller sletter kildematerialet.
2. Den interne `bundle.json` oplister præcist alle kopierede relative filstier, SHA256 og størrelser. Filer kopieres med `O_NOFOLLOW` og eksklusiv oprettelse, private 0600/0700-rettigheder og fsync. Uventede filer, symlinks, utilstrækkelig destinationsplads (10 % eller 16 MiB margin), forkerte bytes, forkerte releaseidentiteter, manglende 1243/1244/1245 og falske godkendelser fører til **STOP**. Manglende kopier giver ingen succesfuld bundle.
3. `--verify-bundle` verificerer igen både 62B-manifest, alle kopier, de tre pinned releaseidentiteter og selvstændigt SHA256 af `bundle.json`. Resultatet er kun et **bytebevis**, ikke en produktionsrestore.
4. `scripts/display_62e_offline_drill.sh --verified-bundle ...` er en eksplicit, **manuel** øvelse på en **separat offline maskine**. Først lykkes `--verify-bundle`; derefter kalder den eksisterende 62B-restoreprocedure en *ny* isoleret PostgreSQL 18 Docker-container med `--network none`, `--exit-on-error`, schema-/migration-/releasepolitik- og gatekontrol. Ingen eksisterende database eller volumen tilgås eller ændres. Containeren fjernes efter kontrol.

62E omfatter **ingen automatiske backupplaner, ingen Render shell-kald, ingen databaseeksport, ingen prod-restore og ingen datamigration**. De eksisterende releaseauth/gates forbliver lukkede. En kode-/CI-godkendelse er ikke et prod-recoverybevis.

## Pinned releasehistorik

* `clientflow-1.3.42-seq-1243`: SHA256 `ee35cc6caa9304bbc7ee4b1c763ecdeaf03d9d58a6c73cee943805251d8d6914`, 223610880 bytes.
* `clientflow-1.3.43-seq-1244`: SHA256 `d3fdae8fb2a93f74431780f4aadde21625d10917e99cfbe6095ff2394e1e856b`, 223610880 bytes.
* `clientflow-1.3.44-seq-1245`: SHA256 `28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5`, 223610880 bytes.

**SHA256 er ikke en udstedersignatur eller en garanti for kryptering og offsite-holdbarhed.** En tidligere release i recoveryarkivet er ikke derved installationsgodkendt.

## Operatørprocedure — kræver særskilt samtykke og godkendt privat backupdestination

**STOP før nogen live eksport:** Beslut krypteret separat/offsite destination, ansvarlig operatør, dataminimering, kapacitet, rotations-/retentionspolitik, restore-tidsvindue, beskyttelse af secrets/passkeys og adgang til recoverymateriale. Den eksisterende 62B `--capture` må aldrig køres, før disse forhold er afklaret. Dump og TAR må **aldrig** lægges i repo, pull requests, GitHub CI artefakter, ChatGPT, ubeskyttede Render-logs eller offentlig fildeling. Genbrug ikke live produktionsmount som destination.

Når en **autoriseret operatør** senere har skabt og kopieret 62B-staging plus de historiske 1243/1244-filer over til en **separat offline og krypteret destination**, kan følgende udføres på den *offline* maskine:

```bash
# 1. Forbered på den OFFLINE maskine to private mapper (0600 filer, 0700 mapper).
mkdir -m 700 /secure/private-recovery-bundles

# 2. Saml verificeret 62B-stage og separat recoveryarkiv.
python3 scripts/display_62e_offline_bundle.py \
  --assemble \
  --verified-stage /secure/private-stage/planiq-display-62b-YYYYMMDDTHHMMSSZ-XXXXXXXXXXXX \
  --offline-recovery-archive /secure/private-recovery-archive \
  --destination-parent /secure/private-recovery-bundles

# 3. Overfør den komplet oprettede bundle via en godkendt krypteret kanal
#    og sammenlign bundle_manifest_sha256 på modtageren (håndholdt attest).
python3 scripts/display_62e_offline_bundle.py \
  --verify-bundle /secure/private-recovery-bundles/planiq-display-62e-YYYYMMDDTHHMMSSZ-XXXXXXXXXXXX

# 4. Faktisk offline DB-gendannelse på en SEPARAT testmaskine.
#    PostgreSQL 18.4-image med pinned digest skal ligge klar lokalt.
bash scripts/display_62e_offline_drill.sh \
  --verified-bundle /secure/private-recovery-bundles/planiq-display-62e-YYYYMMDDTHHMMSSZ-XXXXXXXXXXXX
```

Hvis samtlige tre historiske releases allerede er i den verificerede 62B-stage, er `--offline-recovery-archive` valgfri. Ellers er den nødvendig, og manglende 1243 eller 1244 giver STOP. Navne ovenfor er **eksempler**, ikke faktiske backupstier eller filer.

**Bemærk:** `--verify-bundle` kan køres med almindelig Python 3. `--verified-bundle`-drill kræver Docker og det i 62B pinned PostgreSQL 18.4-image, **uden** internetadgang. Kør aldrig drill på en aktiv Render-/Display-host. Bundlemanifestet er ikke kryptografisk signeret. Sammenlign det oplyste SHA256-fingeraftryk fra den oprindelige, uafhængige overførsel; ellers beviser en lokal SHA alene ikke korrekt proveniens.

## Endelig acceptmatrix efter faktisk test

| Kontrolpunkt | Kan 62E-kode/CI bevise det? | Manuel accepteringsgate |
|---|---|---|
| 62B dump-format og SHA256 | Syntetisk test/fixture | Reel produktionscapture + offline hash |
| Alle tre historiske release-TAR'er | Syntetisk test/fixture | De faktiske pinned 1243/1244/1245 bytes |
| Én samlet recoverykopi | Ja, offline syntetisk test | Reel privat krypteret kopi med kvittering |
| Gendannelse i separat PG18 | Eksisterende 62B CI fixture | Reel produktionseksport i isoleret Docker |
| Aktuelle organisations-/klientrelationer | Nej | Særskilt sikker dataafstemning uden persondata i logs |
| Passkeys/credentials, signaturer, klientenhed efter recovery | Nej | Særskilt funktionel og fysisk test |
| Offsite-holdbarhed, RPO/RTO | Nej | Dateret prøve af transport, restore og recoverytid |
| Database-/API-migration, fysisk rollout/rollback | **NEJ** | Selvstændig eksplicit go/no-go og pilot |

En `DISPLAY_62E_OFFLINE_DRILL_PASS` er bevis for gennemført *isoleret* DB-restore og verificerede TAR-bytes **på det givne testmateriale**. Den autoriserer ikke databasecutover, fysisk klientinstallation, rollback, releasepromotion eller identitetsmigration.

## Større efterfølgende leverance, først når rigtig recoveryøvelse er godkendt

Vælg målarkitektur baseret på faktisk drift og dokumenteret totaløkonomi: (A) behold single-node med accepteret deployment-afbrydelse og dokumenteret recovery, eller (B) flyt PostgreSQL til separat managed instans, immutable signeret release-lager til ekstern objektstore, og gør backend stateless. **Ingen ændring af `render.yaml`, databasekonfiguration, skema, secrets eller live mounts i 62E.** Særskilte faser for shadow-reads/afstemning, adgangssikkerhed, datakonsistens, rollback og fysisk klientpilot for mindst 100-klienters mål. Undgå ekstra manuelle Render-deployments af samme commit.
