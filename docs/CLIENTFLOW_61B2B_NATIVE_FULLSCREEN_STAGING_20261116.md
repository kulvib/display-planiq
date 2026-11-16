# PlanIQ Display – 61B-2B: offline fullscreen-skærm under OS-/firmwarevedligeholdelse

**Grundlag:** `display-planiq-main(20261116-134913).zip` (senest godkendte main fra 16.11.2026).  
**Leverancetype:** kun kildeændringer/test; **ikke** en signeret ClientFlow-release eller produktionsudrulning.

## Ændringer

- Ny `client/libexec/update-maintenance-screen`: separat, unprivilegeret GTK4-fullscreen-skærm i lokal Wayland-session. Ingen HTTP, installationskommandoer, dialoger, adgangskoder, fjernstyring eller reboothandlinger. Den viser kun faste danske statusbeskeder for den eksisterende root-ejede OS-/firmware-maintenance-marker.
- `display_runtime.py` starter skærmen først, når Chrome er stoppet, og så længe root-brokerens vedligeholdelseslås er aktiv. Skærmen genstartes skånsomt ved uventet exit og fjernes igen, når installationen er afsluttet. Mislykket visning ændrer **ikke** root-brokerens sikkerhedstilstand, Chrome-gate eller systemrebootjournal.
- Skærmen genlæser status hvert 2. sekund lokalt; ingen ekstra backend-/Neon-kald og ingen opdigtet installationsprocent eller afslutningstid. Root-ejerskab, type, filrettigheder, symlink og størrelsesgrænse kontrolleres før læsning; korrupte markører giver advarsel, ikke succes.
- Releasebuilderen kender den nye helper som del af fremtidige **nye, signerede** installerbare releases. Eksisterende 1.3.44/1245, installationsarkiv, katalog, approval, migrationskæde og udrulningsgates er uændrede.

## Drift og negative tilstande

1. **Ingen aktiv markør**: ingen fullscreen-skærm; eksisterende Chrome-/kalender-/internetregler er uændrede.
2. **`browser_stopping`**: den aktive Chrome skal lukkes af System-broker først; fullscreen-skærmen starter først derefter.
3. **`installing`**: Chrome forbliver lukket, GTK-skærmen viser opdatering uden procent.
4. **`rebooting`**: marker forbliver aktiv gennem boot; GTK-skærmen kan starte igen, når lokal Wayland-session er tilgængelig.
5. **`post_boot_check`**: status vises frem til brokerens eksisterende boot-ID- og servicecheck er grønt.
6. **`recovery_required`** eller korrupt markør: vis advarsel; browser forbliver spærret af eksisterende 61B-2A fail-closed-regel.
7. **`completed`**: fullscreen afsluttes, og eksisterende internettjek og kioskbrowserstart overtager. Systeminstallationssuccess er stadig **ikke** fysisk kiosksuccess.
8. **Grafisk session utilgængelig / GTK starter ikke**: status/skærm kan mangle, men browser- og installationsspærringer forbliver aktive. Ingen automatisk reboot-loop.

## Bevidste afgrænsninger

- GTK's fuldskærmsprioritet i GNOME/Wayland, visning under faktisk apt/fwupd, reboot, systemservice-genstart og recovery skal afprøves på en fysisk klient. Et succesfuldt unit-testforløb beviser ikke, at skærmen altid er synlig under alle firmware-bootfaser.
- **ClientFlow's egen signerede in-place-aktivering** bruger stadig selvstændige deployment-, staging-, health- og rollback-gates. Dette source-staging ændrer ikke controllerens root-transaction eller dens rebootgate. En vedvarende fullscreen-skærm *på tværs af selve releaseskiftet* kræver særskilt controller-/systemd-handoff-design og fysisk pilot; den er **ikke** påstået løst her.
- Installeret 1.3.43/1.3.44-klient får ikke denne skærm ved Render-redeploy alene. Den kræver ny signeret og godkendt release efter fysisk pilot, hvorved 1.3.44/1245 forbliver uændret rollbackhistorik.
- Denne ændring tillader ikke nyinstallationer, pilot, fleet eller DB-cutover. Ingen produktionsvariabler eller DB-data ændres.

## Test og release-gates

Kør `PYTHONPATH=client/runtime python -m pytest -q backend/tests/test_clientflow_61b2b_fullscreen_maintenance.py backend/tests/test_clientflow_61b2_update_maintenance.py`, eksisterende system-/browser-/recovery-kontrakttests og fuld GitHub CI. Kontrollér den signerede release-byggers liste over hjælpeprogrammer. Fysisk pilot kræver eksplicit testklient og godkendelse, med observation af skærm, stabilitet, boot-ID, internetkontrol, kioskens reelle fullscreen, fravær af ekstra deployments og recovery.
