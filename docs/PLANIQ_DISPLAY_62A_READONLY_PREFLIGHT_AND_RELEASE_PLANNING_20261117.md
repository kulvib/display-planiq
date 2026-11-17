# PlanIQ Display 62A · Driftstilgængelighed og releaseplanlægning

Dato: 17. november 2026. Kildegrundlag: vedhæftet `display-planiq-main(20261117-103549).zip`, GitHub `main` på `d280417040dc662b9d9b0d1f901d73d66563174f`.

## Resultat og præcis afgrænsning

Dette er **første sammenhængende, ikke-destruktive kodeleverance i fase 62**. Tre sammenhængende ændringer leveres i én branch:

1. Administration / ClientFlow Releases bruger den samme `AdminRefreshButton` som Organisation og Brugeradministration, og placerer den eksplicit øverst til højre i sektionsheaderen, også ved smal skærm.
2. Serveren leverer en skrivebeskyttet `POST /api/clientflow/release-administration/preview`. Den kræver superadmin uden impersonering, låst 61A-politik, aktuel politisk revision, samme låste målrelease og Status-agentens aktive, matchende credential og kildeversion for **alle** 1–25 klienter. Den returnerer **aldrig** deploymentautorisation. Den samme kontrol gentages under `POST /drafts`, selv hvis en preview lige var bestået (TOCTOU-sikring). Intet nyt deployment- eller rollback-API indføres.
3. `scripts/display_62_storage_preflight.py` er en standardbiblioteksbaseret, **rent skrivebeskyttet** lokal lagerkontrol: faktisk PGDATA, PG18-layout, sikker artifact-map, filtype, præcist SHA256 og valgfri længde for låst 1.3.44/1245-TAR. Viser ledig plads diagnostisk og afviser symlinks og beskadiget release. Den hverken kører SQL, `pg_dump`, reparerer, flytter eller ændrer data.

### Uændret og fortsat spærret

- Katalog: 1.3.44/1245 er eneste godkendte stabile release. 1.3.45/1246 er usigneret kildekandidat.
- `clientflow_release_control`: nyinstallation, fleet og DB-cutover forbliver `false`.
- Fysisk pilotaccept og releasegodkendelse er ikke givet. Intet klientdeployment, ingen signering, ingen arkivændringer, ingen ændrede migrationsfiler, ingen Render-miljøvariabler.
- Denne preflight er **ikke** backup-, restore-, integritets-/WAL-, zero-downtime- eller migrationsbevis.

## Verificeret nuværende hosting – vigtigt

Det *aktive* Render-backendmiljø bruger det alternative single-node Docker-flow (`backend/Dockerfile.single-node`, `backend/scripts/start_single_node.sh`) med **PostgreSQL 18 og immutable release-TAR på samme persistente Render-disk** under `/var/data/clientflow-release-artifacts/`. PostgreSQL lytter kun på Unix-socket, og startup overskriver `DATABASE_URL` til lokal DB. Den Neon-baserede `render.yaml` eksisterer stadig i repository, men er **ikke** beskrivelsen af den aktive drift og må ikke rulles ud som en utilsigtet erstatning.

Mens den persistente disk er monteret på API-servicen, medfører Render-redeploy som udgangspunkt afbrydelse. Frontendfejl-/CORS-håndtering kan forklare en `502` pænt, men kan ikke give faktisk høj tilgængelighed. Bare at fjerne eller flytte release-TAR er ikke tilstrækkeligt, fordi den aktive PostgreSQL-database stadig bruger disken. Separat DB + eksternt object storage/release authority, migrationssikkerhed, og flere stateless API-instanser kræver **eget arkitektur-/budgetvalg og fysisk rollbackøvelse**; det er ikke implementeret eller automatisk aktiveret her.

## Render Shell – frivillig read-only statuskontrol

Udfør kun, hvis du ønsker en ny lagerrapport. Scriptet kopieres til næste backend-build efter CI/merge. Det ændrer intet og må aldrig bruges som eneste beslutningsgrundlag for migration:

```bash
python3 /opt/display/scripts/display_62_storage_preflight.py \
  --mount /var/data/clientflow-release-artifacts \
  --release-id clientflow-1.3.44-seq-1245 \
  --expected-sha256 28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5 \
  --expected-size 223610880
```

Resultatet indeholder bl.a. `storage_preflight_ok`, antal check, frigjort plads observeret, og de altid falske `backup_verified`, `restore_verified`, `database_cutover_authorized`, `deployment_authorized`. **PASS betyder alene, at grundlæggende filstruktur og én godkendt TAR er til stede og hashkontrolleret.** Filer kan godt ændres under læsningen af levende PostgreSQL, og PGDATA-læsetjek verificerer ikke relationer, WAL eller replikering. Den installerede backend kan mangler adgang til PGDATA, hvis Shell ikke har tilstrækkelige læserettigheder; en sådan fejl giver STOP, ikke forslag om at ændre databasens rettigheder.

## Næste store gate (ingen automatisk handling)

**62B – ikke-destruktiv recoverybevis og arkitekturvalg** før eventuel flytning:

1. Autoritativ produktionsopgørelse: PostgreSQL-version, databasestørrelse, migrationsrevision, relevante tabelantal, diskforbrug, godkendte TAR-hashes og de 3 beskyttede recoveryrelease-referencer. Ingen hemmeligheder i rapporten.
2. Fuld *konsistent* logisk PostgreSQL-backup (`pg_dump -Fc`), eksternt krypteret backupmål og dokumenteret SHA256. En kopi på samme Render-disk tæller **ikke** som offsite backup.
3. Isoleret restore-øvelse (`pg_restore` til nyt, ikke-produktionsmiljø), tabelforhold og integration-smoketest. Der skal også foreligge separat testet recovery af releasekatalog, signerede artefakter og immutabel godkendelseshistorik.
4. Designbeslutning: (A) accepter kontrolleret downtime på den billige single-node-arkitektur og fjern unødige redeploys, eller (B) adskil DB/releaselager fra API og planlæg stateless, redundant API. **B har nye omkostninger og kræver eksplicit godkendelse**; Render-disk må ikke fjernes, før beviserne er grønne.
5. Ved fysisk cutover: frys ændringer, sikr nye backups, test DNS/router/auth/WebSocket/longpoll og klienternes reconnect, udfør datakontrol, samt hold en dokumenteret failback-vektor. Ikke-destruktiv migration betyder, at originalen bevares indtil fysisk accept.
6. Separat release- og pilotgate: usigneret 1.3.45/1246 bygges reproducerbart; signering og fysisk pilot er egne godkendelsespunkter, og masseudrulning/rollback forbliver lukket indtil dette er bevist.

### Yderligere negative tests før en senere 62B/62C

- PostgreSQL og release-TAR forsvinder aldrig ved en redeploy eller en mislykket migration; valider igen SHA og databaserevision.
- Ingen automatisk DB-reset ved manglende `PG_VERSION`, diskfuld/hård fejl, eller skift af backend-mode.
- Fejlet database-/artefaktsnapshot gør deployment/rollback **forbudt**. Ingen nyinstalleret klient må få ufuldstændige releases.
- Sessions, passkeys og superadmin nødberedskab forbliver brugbare eller håndteres med separat driftsprocedure. Ingen automatiske credentialsændringer.
- Browserens netværksfejl vises som midlertidig tilgængelighedsfejl, ikke forkert kode eller mystisk CORS-konfigurationsfejl.

## Accept for 62A

Fuld GitHub CI, inkl. backend preview-integration, frontend lint og de nye filsystemtests. Dernæst read-only smoke: release-siden viser 1.3.44 stable, kan vælge Viborg1 v1.3.43, sikker preview returnerer `deployment_authorized=false`, og lagerrapport giver et dokumenteret grundlag uden produktionændringer. **Ingen klientpilot og ingen automatisk godkendelse.**
