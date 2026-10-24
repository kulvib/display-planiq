# PlanIQ Display – kiosk, terminalhjælp, WiFi og samlet fejlhistorik

**Kilde:** `display-planiq-main(20261024-131103).zip` (GitHub `main` SHA `30c9a56be53b8ebc7dfe3972384b36ad82ffa6b5`). Koden i denne ændringspakke er en ny **source-stage**, ikke en installeret immutable ClientFlow-release. Ingen nøgle, releasegodkendelse eller produktionstjeneste ændres.

## 1. Internet-gate på kiosk

Den nuværende ClientFlow Display Runtime har `InternetMonitor` og må ikke starte Chrome, før to succesfulde kontroller er fordelt over mindst 10 sekunder. Et bekræftet forbindelsesudfald i mindst 20 sekunder lukker Chrome og bevarer `browser_requested` til en ny godkendt forbindelse; en manuel/kalender-stop nulstiller ønsket. Kontrollen bruger backend `/health` uden database og derefter HTTPS-origin fra kiosk-URL. Det er *faktisk HTTPS-reachability*, uanset om den aktive rute er WiFi eller Ethernet, ikke blot et positivt NM-connectivity-flag.

**Ændring:** HTTPS-origin-parseren afviser brugerinfo (`user:password@host`) og ugyldige porte, og konstruerer korrekt bracketed IPv6, så den aldrig videresender legitimationsoplysninger/path/query/fragment ved et fallback-probe. Ingen timeout, hysteresetærskler, stoplogik eller CPU/DB-polling ændret.

**Fysisk accept mangler stadig:** offline boot, aftaget kabel med WiFi-fallback, WiFi-offline med Ethernet, faktisk DNS/TLS-tab, kalender-stop under offline, stabil genforbindelse og manuelt stop. Afprøv ikke kabelafbrudt fjernadgang uden fysisk rescue.

## 2. Fuldskærm-visning

`browser_fullscreen` er en eksplicit, tidsbegrænset **serverobservation**. Den må kun vises som chip når både `clientOnline` og `chrome_running` er `true`; ved `false`, `null`, stale/offline eller fravær af observeret browserproces skjules den helt. Under reel drift med ukendt fuldskærmsobservation vises `Fuldskærm: Ukendt`, ikke en fabrikeret positiv status. Samme policy bruges af klientliste og Control Room, og indeholder regressionstests for begge.

## 3. Audit af samtlige terminal-hjælpere

**Alle 19** har en særskilt, praktisk funktion. Der slettes ingen af de oprindelige 15; de opdaterede hjælpere inkluderer 2 eksisterende WiFi-hjælpere samt 2 nye. En statisk test kontrollerer samtlige etiketnavne, Bash-syntaks for hver flerlinjekommando, og at alle 28 refererede ClientFlow-systemd-units er definerede i repository. Disse kildetests er **ikke** det samme som en fysisk test af `sudo`, NetworkManager eller systemd.

| Hjælper | Beslutning | Begrundelse / bemærkning |
|---|---|---|
| ClientFlow samlet status | Bevar + opdater | Centrale agenter. Nye stabile outbox-units medtaget; fravær før 1242 er forventeligt |
| Display / kiosk browser | Bevar + hårdn | Services, browserproces og allowlistede runtime-/internetstatusfelter, uden at dumpe signeret kiosk-URL eller rå konfiguration |
| Aktiv release / updater | Bevar | Aktivt symlink, updater-timer og journal; ingen kommando til update/rollback |
| Livestream v2 status | Bevar + hårdn | Producent/agent/uploader med allowlistet status; hemmelige nøgler eller URL'er udskrives ikke fra rå statusfiler |
| Terminal status | Bevar | Agent og standard-/root-sockets; socket-aktiveret service kan være inaktiv i normal drift |
| Remote Desktop status | Bevar | Agent, capture og input-broker; socket-aktivering er ikke i sig selv en fejl |
| Aktive ClientFlow units | Bevar | Kort oversigt i forhold til den dybe samlet status |
| Ubuntu / APT health | Bevar | `dpkg --audit`, `apt-get check` og reboot marker; ingen opdatering installeres |
| Disk, RAM og oppetid | Bevar | Ikke-privilegeret ressourcestatus |
| Netværk, DNS, tid og backend | Bevar + hårdn | IP, DNS, NTP og backend `/health`; udskriver kun backend scheme/host, ikke usanitiseret URL |
| WiFi / NetworkManager diagnose | Bevar | Læser interface, radio, tilgængelige AP'er (uden tvungen scanning), aktive/gemte profiler, IP/routing/DNS; ingen secrets |
| Tilføj WiFi-profil (uden aktivering) | Bevar | Root-only keyfile med `0600`, `autoconnect=false`; TTY-prompt uden PSK i argv, og verificering af uændret aktiv netværksprofil |
| Test gemt WiFi (auto-rollback) | **Ny** | Kun genererede ClientFlow-profiler, interaktiv `TEST`, `nmcli device checkpoint --timeout 120` og **krav om manuel `Yes`**; uden bekræftelse gendanner NM forbindelsen |
| Rollbackrapportering / outbox | **Ny** | Systemd-timer og eksporter-journal; viser kun antal filer i den korrekte `/var/lib/planiq-rollback-outbox`, ingen receipts eller tokens |
| Display/browser logs | Bevar | Browser-/runtime-/guard-journal |
| Status/System logs | Bevar | Presence og system-agent-journal |
| Livestream logs | Bevar | Agent/producer/uploader-journal |
| Terminal logs | Bevar | Forbindelse, PTY og broker-journal |
| Remote Desktop logs | Bevar | RD-agent/capture/input-journal |

### WiFi-procedure og begrænsninger

1. Kør **WiFi / NetworkManager diagnose** i autoriseret Admin-terminal. Kontrollér især at netværksruten til fjernterminalen fungerer, og at den rette radio/interface findes.
2. Kør **Tilføj WiFi-profil (uden aktivering)**. Indtast SSID, sikkerhedstype og PSK interaktivt. Dette **etablerer ikke forbindelsen**. Keyfilen ligger root-only i NetworkManagers systemprofilmappe; det er tilsigtet, at NetworkManager kan læse dens PSK.
3. På en fysisk overvåget testklient: kør **Test gemt WiFi (auto-rollback)**, indtast den oprettede UUID, interface og `TEST`. NetworkManager administrerer checkpoint med 120 s timeout og spørger om bekræftelse, selv når command wrapper læser fra en pipe. **Skriv kun `Yes`, når internet, routes og fjernadgang er verificeret.** Uden bekræftelse rulles netværksændringen tilbage.
4. Ny profil har fortsat `autoconnect=false` efter en vellykket test. Dette er sikkerhedsdesignet: produktions- eller genstartsaktivering kræver særskilt godkendt politik for fallback, prioritet og automatisk forbindelse. Scripts bør ikke tavst ændre default-route eller gøre en usikker profil permanent.

**Afsnit 3 er ikke fysisk kvalificeret**: Det er usikkert at garantere, at WiFi-switch, en specifik NetworkManager-installation, adgangskodebehandling, journalrettigheder eller checkpoint bevarer den eneste remote admin-kanal, uden en fysisk klienttest. Et checkpoint er gendannelse af NetworkManager-konfiguration, ikke hardwaregaranti ved firmware-/driverfejl eller strømbrud. Ingen tester bør deaktivere eneste aktive uplink på en klient uden lokal reserveadgang.

## 4. Superadministrator – central hændelses- og fejlhistorik (design, endnu ikke kode)

Dagens `health_issues`-liste genereres dynamisk ved Control Room-læsning, og er **ikke** en historik. Den kan ikke vise, om en tidligere fejl forsvandt, hvornår, eller i hvilken bootperiode. Auditloggen opsamler administrative handlinger, men er ikke et fuldstændigt hændelses-/recoveryledger.

**Næste sammenhængende, migrationstunge implementering** skal levere:

- Ny reviewed Alembic-successor efter `20261023_59a_rollback` **med eksakt schema, historisk baseline-adoption og migrationskontrakter**. Eksisterende 59A, dataintegritet og historiske snapshots må ikke ændres/skjules.
- Append-only hændelser for `raised`, `still_active` kun ved væsentlige ændringer, `observed_cleared` og `reopened`. Deduplikering på klient/domæne/fejlkode og en unik åben periode; idempotent ved retries og samtidige rapporter.
- Kun autentificerede Status/Display/System-/updater-hændelser må ændre sagernes tilstand. Eventuelle nye lokale fejl skal køes holdbart og rapporteres efter offlineperioder med begrænset payload. Aldrig logge adgangskoder, private nøgler, adgangstokens, autorisationsheaders eller signeret URL.
- `first_seen_at`, `last_observed_at`, `cleared_at`, kilde/domæne, fejlkode, alvor, klient, release/boot-ID og dokumenteret observation af løst fejl efter genstart. **En ny boot må ikke automatisk markere fejlen løst**, og en fejl der forsvinder efter reboot må ikke automatisk tilskrives reboot som *årsag*.
- Offline/stale tilstand må være `ukendt/ikke verificeret`, ikke `løst`. Hvis klienten ikke længere indsender telemetry, bevares sagen som åben/ubekræftet.
- Superadministrator-side **Driftsfejl og historik**, med filtrering på åben/løst/ukendt, klient, organisation, severity, tidsrum, reboot-ID, seneste signal samt manuel åbning af Control Room. Kun læseadgang til hændelser og role-scopet API; no-store, begrænset paginering, autorisation server-side. Ingen ny konstant DB polling per klient: journalen skrives kun ved transitions, UI læser on demand.
- Retentionsstrategi og verificeret hard-delete/decommissionering; GDPR/persondata/fortrolighedsvurdering inden deployment. Skal også afdække backend-/API-fejl i stedet for kun klientens allerede modellerede advarsler. Aftal hvilke kritiske fejl, der er accept-kriterier, og dokumentér ikke-observerbare perioder.

**Ikke gjort i denne pakke:** ny database, Alembic-head, migrationskontrakt, historisk API eller UI. En forhastet 60A-migration på tværs af det hårdt frosne 59A-baseline-system ville ikke være en sikker ændring af samme karakter som de isolerede kiosk-/terminal-/UI-fixes. Dette er en planlagt særskilt samlet fase, ikke en påstand om historisk logging i den nuværende kode.

## 5. Gates og releasegrænse

- Ingen ClientFlow 1.3.41 / 1242 releasebundles bygges i denne fase, og signeringsnøgler forbliver deaktiverede/uprovisionerede.
- Source-only frontend/browser-script og Python runtime skal gennem GitHub CI, Ubuntu 26.04-proof og friske kildehashes. Ændringspakken må først merges til `main` efter alle obligatoriske gates er **success**.
- Desktop Systemd/WiFi-checkpoint, browserlukning via Ethernet/WiFi og 1242-rollbackrapportering er fysiske accepttests, ikke automatiske CI-godkendelser.
