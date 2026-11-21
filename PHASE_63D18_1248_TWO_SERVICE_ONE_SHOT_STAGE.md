# PlanIQ Display · Fase 63D-18 · Præcis Viborg1 1247→1248 engangsinstallation (kun kildeforberedelse)

**Status: KILDEKANDIDAT / INGEN FYSISK INSTALLATION / INGEN KATALOGPROMOVERING / INGEN DB-AUTORISATION.** Denne ændring gør **ikke** 1248 valgbart og igangsætter ikke en updater. Backendens aktive katalog skal fortsat være **1247**, indtil en separat godkendt katalogpromovering og en særskilt fysisk pilotbeslutning.

## Verificerede operatørdata, 21. november 2026

- Host `viborg1-NUC14MNK-B2`, klient ID **3**, `/opt/clientflow/active` og lokal releasejournal peger på `clientflow-1.3.46-seq-1247`; `activation_intent` er `null`. Lokalt SHA `3d6df5ec096a5713866943a67d9f88bba3fc6287458d0ea2f616bd41e42db150`.
- `clientflow-updater.timer`: **disabled/inactive**. `clientflow-update-controller.service`: **inactive**. `clientflow-status-agent.service`: **active**.
- Installeret 1247-kode, SHA256 fra fysisk klient, kontrolleret mod 1247-kildens checksummer og tilsvarende uændrede kildefiler:

| Original fil | Installeret SHA-256 |
| --- | --- |
| `transaction.py` | `196b4e7b957e3de4aacc7978e95a87d62331ebf936d2c66e5ca6ef6cfeb24e5f` |
| `update_controller.py` | `af611f805a29a02b2e968b1fda2750a0a0bfa9a36736772f30ed3ff1f1da9edb` |
| `updater_state.py` | `a39a087d2001d800ba1fc76361c6a176e9e6ffeec7b6d0f491a7e29c0b5f1767` |
| `updater_client.py` | `6bd9cbe526e38dcf3ab6b9e13a43d5246eb90424e021a6bf8f6e24bd8ec686ce` |
| `install_coordinator.py` | `f236b9d9964c5c0fcf2b68ee8872a6af0cad8fcd14e2b78b6f00a9512955caeb` |

- 1248-godkendelse: `clientflow-1.3.47-seq-1248`, størrelse **223692800**, SHA `9ca8852ba29153f2ec40b58d18007c738a03f9569f14762486fc1953c59eb6ff`, approval `CF-1.3.47-1248-20261121-c0d5a092-f8240014`; korrigeret transaktionskilde fra godkendt 1248 source har SHA256 `459bf6d9821f87e461c6a73efae579606bf2b8acd26ad78b2b4339c1f006c4b8`.
- Render / lokal PostgreSQL read-only audit: aktivt katalog [1245,1246,1247], kun staged [1245,1247,1248], klient ID 3 online med version 1.3.46 og én aktiv Update credential, ingen aktiv deployment, ingen uafklaret `recovery_failed`, `cutover_enabled=false`, `fleet_open=false`, `fresh_install_open=false`, stabil 1245. 1247-deployment er `succeeded`, id `f99607f6-f1b7-43e5-a489-d756246e1849` (det gamle ID må **ikke** genbruges til 1248).
- Render lager: fire fysisk bevarede TAR 1245–1248; `RELEASE_STORE_AUDIT=PASS`, `invalid_artifacts=[]`, cirka **643948544** bytes ledige. `RELEASE_RETENTION_READY=NO` og `RELEASE_APPROVED_LIMIT_MET=NO` er **forventede** ved den allerede godkendte midlertidige lagerundtagelse. Ingen fil må slettes i denne fase.

## Vigtig opdagelse: systemd-kæden kan aktivere controlleren uden timer

Den signerede 1247 `clientflow-updater.service` er `Type=oneshot` med:

`OnSuccess=clientflow-update-controller.service`

**Selv når updater-timeren er disabled, vil et enkelt manuelt `systemctl start clientflow-updater.service` efter en succesfuld verificering kunne starte den eksisterende fejlbehæftede 1247 update-controller. Start derfor ikke nogen af de to services, før en separat eksplicit fysisk autorisation, en verificeret midlertidig controller-override og grønne preflights er gennemført.** Den tidligere 63D-14-recovery er præcedens for en root-private, runtime-only systemd-overstyring; dens gamle deployment-ID eller staged recovery-state må ikke genbruges.

## Hvad kildeændringen indeholder

`/scripts/phase63d18_viborg1_1248_one_shot.py` har to modes:

1. `--check`: **kun aflæsning** af fysisk host, ID 3, aktiv source, lokal journal, ingen `activation_intent`, fri koordinator, tidligere controller terminalt ren, alle fem signerede 1247-kildehashes, den eksakte 1248-korrigerede `transaction.py`, updater-timer og service-status. Returnerer aldrig en godkendelse.
2. `--execute --deployment-id <NYT UUID>`: **standardafvist** uden præcis operatorbundet `CLIENTFLOW_63D18_ONE_SHOT=<samme UUID>`, systemd `INVOCATION_ID` og original `CREDENTIALS_DIRECTORY`; kræver den signerede, fysisk tilstedeværende 1247-controller, en separat root-ejet stagingmappe med 0700, filer 0600, et præcis godkendt 1248-target og den eksisterende DPoP-verificerede backend-deployment. Den originale 1247 `UpdateController.run_once()` forbliver ansvarlig for verificeret artifact-handoff, staging, aktiveringsgate, helbredstest, rollback og backendrapportering. Kun transaktionskoden indlæses fra en selvstændigt verificeret rettelse med eksakt SHA og same-class-identity; `activate_release` får altid det **nye, præcise 1248 backend deployment-ID** via `expected_update_deployment_id`.

Koden opretter ingen deployment, skriver ingen systemd-drop-in, starter ingen services, downloader ingen TAR og ændrer ingen signerede release-mapper af sig selv. `--execute` er en **fremtidig, særskilt operatørhandling**, ikke et CI-/merge-resultat.

## Sekventiel fysisk handoff – må ikke udføres alene på baggrund af denne PR

1. Merge kildeændring først efter fuld grøn CI, peer review og kontrollér at Render backend og frontend kører præcis merge SHA. Aktivt katalog forbliver 1247. Kræv opdateret fysisk og backend read-only kontrol, ikke genbrug af tidligere skærmbilleder.
2. En separat **reviewet 1248-katalogpromoverings-PR** skal først gøre det eksakte stage [1245,1247,1248] aktivt. 1245 forbliver eneste stable/default; 1246 forbliver *lagret* på Render; ingen fresh install, fleet, rollback, downgrade, auto cleanup eller ekstra TAR.
3. Indhent eksplicit fysisk autorisation, tilgængelig fysisk recoveryadgang og **ny** superadmin-pilotdeployment på præcis klient ID 3 fra 1.3.46. Kontrollér DB transaktion/UUID, Status frisk, én aktiv Update credential, fysisk verified 1248 TAR og komplet releasekilde. Ingen gammel `f996...`-autorisation må genbruges.
4. Placér kun den **commit-pinnede** one-shot runner plus `client/release/lib/clientflow_release/transaction.py` fra den signerede 1248-kilde i den root-private mappe `/var/lib/clientflow/63d18-1248`, mode 0700/filer 0600. Kontrollér begge filer mod den faktiske godkendte commit-SHA og SHA256; kør kun `--check` med den installerede **1247 interpreter**. STÅ AF ved afvigelser.
5. Før nogen start af updater-service: En separat fagligt reviewet **midlertidig /run/systemd/system/-drop-in** for `clientflow-update-controller.service`, hvor alene `ExecStart` rettes til commit-pinned one-shot-script med det nye backend deployment-ID og eksakt one-shot miljøbinding. Bevar `User=root`, original `LoadCredential`, `CREDENTIALS_DIRECTORY`, `StateDirectory`, `ProtectHome=tmpfs`, `BindPaths=/home/clientflow-kiosk`, serviceafhængigheder og de øvrige systemd-hardeningdirektiver. Valider effektive servicekontrakter efter `daemon-reload`. Den periodiske timer forbliver disabled.
6. Kun når begge read-only preflights og alle uafhængige operatørgates passer, må den særskilt godkendte operatør starte original `clientflow-updater.service` **én gang**, hvorefter dens `OnSuccess` når den kontrollerede controller. En fejl eller uentydig status er STOP: aldrig retry, manuel oplåsning eller oprydning uden særskilt recovery-review.
7. Verificér backendens deployment-events og terminal state, fysisk `active`, transaktionsjournal, `activation_intent=null`, kildeintegritet, systemd-services og korrekt reboot. Fjern først den midlertidige systemd-drop-in efter journalført sikkert terminaludfald og bevar log til fysisk accept.
8. Fysisk accept: PipeWire første frame, progressiv HLS segmentproduktion, faktisk Livestream i browseren, videoforsinkelse, Remote Desktop med mus/tastatur og friske frames, fallback/reconnect, CPU/RAM/DB-kald, genstart og reboot. Ikke samme som CI. Ingen fleet/auto-updater eller retention-cleanup før separat beslutning.

**Vigtig driftsnote:** Den særskilte katalogpromovering og installationsautorisation skal *ikke* ligge i samme automatiske Render deployment som denne source-only PR. `main`/Render-redeploy alene må aldrig aktivere 1248 på Viborg1.
