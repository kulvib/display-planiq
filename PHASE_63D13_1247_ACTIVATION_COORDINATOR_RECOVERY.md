# PlanIQ Display · Fase 63D-13 · 1247-aktiveringens installationslås

**Status: Kodekandidat til review og CI. Ingen klientaktivering, manuel recovery eller opdatering af signerede bundles sker ved merge.**

## Dokumenteret hændelse 20. november 2026

- Fysisk klient: Viborg1, backend ID 3, fysisk aktiv release `clientflow-1.3.45-seq-1246`.
- Eksisterende backend-deployment: `f99607f6-f1b7-43e5-a489-d756246e1849`; mål: `clientflow-1.3.46-seq-1247`, status `activating` siden 11:17:41 (databasetid).
- Updater download/verify/stage og activation-start blev registreret, men der kom ingen `health_check_started`/`succeeded`.
- Lokalt: controller `activation_authorized`, installationskoordinator `owner=update_clientflow` med samme deployment-ID, release-state `active_release_id=1246`, `staged_release_id=1247`, `activation_intent=null`.
- `clientflow-update-controller.service` fejlede gentagne gange med generisk recovery-fejl; status-agent kørte stadig.
- Operatøren har stoppet `clientflow-updater.timer`, bekræftet `inactive` timer/updater, `failed` controller og `active` status-agent. Bevar denne tilstand, indtil recovery er særskilt godkendt.

## Bekræftet kodekonflikt

Den allerede installerede 1246-controller tager en holdbar reservation med `install_coordinator.claim(owner='update_clientflow', operation_id=<backend_deployment_id>)`. Den kaldte release-transaktion accepterede historisk kun `fresh_install` som ejer, når en reservation fandtes. Resultatet var et afslag **før** `activation_intent` og før et release-skift. Den historiske 1246-kilde og aktuel main indeholdt konflikten.

## Samlet kildeændring

1. `transaction.activate_release` modtager valgfrit `expected_update_deployment_id`, kun på den root-kontrollerede opdateringssti. Den afviser alle andre låseejere, manglende eller forkert UUID, første installation, ukorrekt stage og downgrades; frisk installations flow berøres ikke.
2. Den privilegerede controller videregiver den **backend-bundne** `snapshot.deployment_id`, når backend allerede er i `activating`.
3. Negative regressions- og historiske controller-tests er opdateret. Kun en eksakt lås kan fortsætte; låsen frigives stadig først af controllerens eksisterende terminal-/recoverylogik.
4. `scripts/phase63d13_viborg1_recovery_preflight.py` er et **læsebeskyttet** værktøj til en senere fysisk fase. Det kender præcis Viborg1/1246/1247, deployment-ID, SHA og approval og afviser enhver afvigelse. Det aktiverer intet, frigiver ingen låse og foretager ikke netværkskald.

## Kritisk separation mellem kode og faktisk recovery

- En merge/redeploy til Render kan **ikke** opdatere den allerede installerede 1246-controller. Genstart ikke updateren efter merge; det gentager blot fejlen.
- **Approved 1247** GitHub/Render TAR er immutable: `3d6df5ec096a5713866943a67d9f88bba3fc6287458d0ea2f616bd41e42db150` (223692800 bytes). Ingen rebuild af `1.3.46/1247` med nye bytes, ingen ompakning og ingen ændring inde i `/opt/clientflow/releases`.
- Kodekorrigeringen er også grundlag for en **fremtidig, separat godkendt kildeidentitet**; den ændrer ikke allerede frigivne releases. Der må ikke køres en ny release-build under sekvens 1247.
- Recovery af den eksisterende 1247-deployment kræver først ny, skrivebeskyttet backendbekræftelse af state `activating` og events/versionsgrundlag. Den kræver desuden præcis CI-godkendt/individuelt attesteret reparationskode uden for immutable release, med en særskilt operatørbeslutning og sikkerhedsgates. Dette repository leverer **ikke** en automatisk recoverygenvej.
- `READ_ONLY_PREFLIGHT=PASS` betyder alene, at den lokale state opfylder forventningerne. Den autoriserer ikke aktivering; scriptet angiver altid `recovery_approved=false`.

## Efter grøn GitHub CI

1. Merge kodekandidat først efter review af signerings-/source-frysepolitikken. Hold updater-timer `inactive` på Viborg1.
2. Overfør **kun** det læsende preflight-værktøj fra det verificerede repository til Viborg1 under root-kontrolleret sti og verificér hash/ejerskab; kør det læsende.
3. Kontrollér samtidig i **Render Docker PostgreSQL** (Unix-socket, ikke historisk Neon), at samme deployment stadig er `activating` uden nye terminalevents.
4. Først derefter kan en særskilt, idempotent og operatørgodkendt *off-release* recoveryartefakt udvikles og prøves med sand 1246-aktiveringskode. Ingen låse-/state-reset eller uautoriseret statusændring.
5. Ved faktisk gennemført aktivering skal controller/server-endepunkter rapportere `health_check_started`, `succeeded`, status `1.3.46`, intakte credentials og returneret terminalstatus. Derefter genaktiveres updater-timeren kontrolleret.

## Afgrænsning

Ingen DB-migration, ny Render-variabel, automatisk rollback, fleet-åbning, fresh-install-åbning, sletning af gamle klientposter, 1247-rebuild eller direkte fysisk klientændring.
