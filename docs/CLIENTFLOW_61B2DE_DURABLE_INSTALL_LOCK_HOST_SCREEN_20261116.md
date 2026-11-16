# PlanIQ Display 61B-2D + 61B-2E — stor, sammenhængende sikkerhedsændring

**Kanonisk grundlag:** `display-planiq-main(20261116-154328).zip`, GitHub `main` `8e197c4df5079d509b98390bcd96e578a9cc1c53` (16. november 2026). Denne pakke er **kun kildekode og tests**, ingen signeret release, ingen Render-konfiguration og ingen klientinstallation. 1.3.44/1245, release-input, migrationsfiler og gates er uændrede.

## 61B-2D: holdbar eksklusivitet på klienten

- En fælles root-ejet lokal CAS-journal under `/var/lib/clientflow/install-coordinator` med 0700-katalog og 0600-filer, `O_NOFOLLOW`, `flock`, atomisk replace og `fsync`. Kun root kan anvende den på rigtig maskine.
- Bundet til præcis én `{owner, operation_id}`: Ubuntu, firmware eller privilegeret ClientFlow-controller. Andre ejere/operationer STOPPER før de ændrer systemet. Samme operation kan genoptages efter procesgenstart; journalen slettes ALDRIG bare fordi en proces afsluttes eller en timeout indtræffer.
- System-brokeren reserverer før browserstop og `apt`/`fwupd`; frigiver først efter *durabelt* fuldført kommandojournal. Genstart skal fortsat bevises med nyt boot-ID og sunde tjenester, før en reboot-afsluttet operation frigives. Fejl eller ukendt tilstand beholder låsen.
- ClientFlow-controlleren reserverer før stage/aktivering; frigiver kun ved sammenfaldende terminal backendstatus og lokal holdbar succes eller rollback. Genstart efter crash kan rydde en tidligere bevist terminal operation efter genverifikation af den lokale historik. Ingen ændring af approval, release-signatur, install-policy, sundhedstjek eller rollback-autoritet.
- Test-rødder bruger en **isoleret** lås, aldrig hostens rigtige status.
- En blokeret eller tvetydig journal må ikke ryddes automatisk. En særskilt, auditeret operatørprocedure med release- og bootbeviser kræves før en eventuel fremtidig recovery-kommando.

## 61B-2E: uafhængig offline fullscreen

- En særskilt `planiq-display-maintenance.service` kører som lokal kioskbruger, via en root-ejet og checksum-verificeret **host-kopi** i `/usr/lib/clientflow/maintenance/host-screen`, ikke via `/opt/clientflow/active`-symlinket.
- Den ligger **uden for** `clientflow.target` og release-transaktionens quiesce-liste og installeres via hostens eksisterende signerede rollback-promotion. Den kan derfor fortsætte under senere release-swap (grafiksessionen og selve maskinen skal naturligvis stadig være tilgængelige).
- Ingen installationsrettigheder, netværksadgang, tokens eller CLI til browser/reboot. Viser kun sikkerhedskontrollerede OS/firmware-markører og root-ejet ClientFlow-release-status. Forældede, beskadigede eller symlinkede markører vises som recovery-advarsel, aldrig som grønt resultat.
- Den eksisterende 61B-2B-runtime-skærm er bibeholdt som fallback, hvis den selvstændige service ikke er aktiv. Det er vigtigt ved første opgradering og fejl i servicepromotion.
- Host-promotion er **best-effort for visning**: et skærmproblem må ikke ændre sundhedstjek, aktivering eller rollback af den signerede release. Under fysisk pilot skal host-tjenesten dog særskilt verificeres; et manglende skærmforløb er STOP for videre udrulning.

## Bevidste sikkerhedsgrænser før fysisk pilot

1. Den første opgradering fra en tidligere version har ikke garanteret uafbrudt host-visning, fordi den stabile host-komponent først kan promoveres fra en ny godkendt release. Den gamle fallback kan også stoppes ved release-swap. Test første opgradering og *næste* release-swap særskilt.
2. Wayland/GTK, GNOME-session og placering af fullscreen-vinduet er ikke fysisk bevist. CI tester kilde, parsing, tilstand og systemd-kontrakt — ikke pixels på en kiosk. Kræv fysisk bevist topmost fullscreen og boot-recovery.
3. Låsen dækker de **automatiserede** ClientFlow-controller-/System-broker-opdateringer. Direkte manuelt root-initieret rollback og første fabriksaktivering følger fortsat deres eksisterende særskilte transaktionslåse. Det er en eksplicit afgrænsning og **STOP-gate**, hvis de skal køre parallelt med en OS-/firmwarevedligeholdelse. Indfør ikke en manuel omgåelse for at spare tid.
4. Når en uafklaret lås efterlades, kan nye opdateringer ikke starte. Det er bevidst fail-closed og kræver autoriseret recovery; ingen automatisk lock-expiry eller reboot-loop.
5. Ingen fysisk pilot før ny separat signeret klientrelease, fuld GitHub CI, faktisk host-service-/rollbacktest, verificerede lukkede DB-gates og eksplicit godkendelse.

## Lokale tests og næste kontrol

Kør med `PYTHONPATH=client/runtime:client/release/lib:backend` blandt andet:

`python -m pytest -q backend/tests/test_clientflow_61b2de_install_coordinator_and_host.py backend/tests/test_clientflow_61b2_update_maintenance.py backend/tests/test_clientflow_61b2b_fullscreen_maintenance.py backend/tests/test_clientflow_61b2c_release_visibility.py backend/tests/test_clientflow_update_controller.py backend/tests/test_clientflow_update_controller_source.py backend/tests/test_clientflow_update_recovery_contract.py backend/tests/test_clientflow_update_safety_baseline.py`

Kør **alle** GitHub-jobs, inklusive Ubuntu 26.04 host/preclaim, release-building, SHA256 og frontend. Lokal fuld backend-suite kan ikke indsamles i dette arbejdscontainer-miljø (manglende `passlib`); det er **ikke** en godkendt erstatning for GitHub CI.

**Branch:** `feature/display-61b2de-durable-install-lock-host-screen-20261116`. Upload filerne til den branch fra den angivne `main`, kontrol CI og derefter bevidst merge/deployment. **Intet fysisk installeres** af almindelig Render redeploy.
