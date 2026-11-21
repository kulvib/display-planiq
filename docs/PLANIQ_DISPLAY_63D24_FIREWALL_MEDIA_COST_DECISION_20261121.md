# PlanIQ Display · 63D-24 · Firewall, Remote Desktop, Livestream og billigste drift

Dato: 21. november 2026. Baseline: GitHub `main` `29e786a4ca5b04eef2a14ee6a424a3d4f69687cb`.
Status: **skrivebeskyttet feasibility-/arkitekturfase; ingen ny produktions- eller klientrelease**.

## Fastlåste forretningskrav

1. Minimum 100 registrerede ClientFlow-klienter uden softwarelicenser, betalte features, tidsbegrænset trial eller bruger-/klientbaseret licensgrænse. **100 samtidig aktive mediesessioner er ikke bevist og skal kapacitetstestes særskilt.**
2. Kommunale og statslige netværk skal kunne anvende godkendt udgående HTTPS/TCP 443; hverken browser eller kiosk må kræve UDP, STUN/TURN, offentligt RDP/VNC, port-forwarding eller WebSocket Upgrade for *grundlæggende* funktionalitet. Overhold organisationens politik; ingen omgåelse af eksplicit blokering.
3. Læsbar tekst og hurtig, korrekt input i Remote Desktop. Ikke kun lav TCP relay send-tid: mål browserens synlige end-to-end frame-delay, træk, klik, tastatur og rettighedskontrol.
4. Stabil HLS-video i frontend med målbar, acceptabel forsinkelse; normal HLS på HTTPS er et andet transportproblem end interaktiv Remote Desktop.
5. Genbrug aktiv **Render Docker Starter** med lokal PostgreSQL 18 og 2 GB persistent disk, hvis fysisk test/kapacitet tillader. Ingen ekstra betalt service, Neon-database, ekstern cache, database eller ny diskstørrelse uden målt begrundelse.
6. Ingen kioskaafbrydelse på grund af menneskelig MFA; aldrig offentliggør RDP/guacd eller credentials, og bevar eksisterende produktadgang, revocation, logs og signeret releasekontrol.
7. Alle ændringer i store sammenhængende batcher med statisk sikkerhedskontrol, CI, fysisk Viborg1-gate og reversibel test. Ingen automatisk 1249-godkendelse.

## Faktisk driftsgrundlag (read-only Render, PlanIQ workspace)

Aktiv `display-backend`: Docker `backend/Dockerfile.single-node`, én Starter-instans, Frankfurt, 2 GB persistent disk. Entrypoint tvinger lokal PostgreSQL gennem Unix-socket `/run/display-postgres`. Der er ingen separat Render PostgreSQL/Key Value-service. Den statiske `display-frontend` er separat.

Observerede Render metrics 14.–21. nov. 2026: ca. 0,0073 CPU i gennemsnit af tilgængelige punkter (limit 0,5), ca. 165 MB RAM i gennemsnit (limit 512 MiB), ca. 3,62 GB backend-transfer og ca. 18,8 MB frontend-transfer, ca. 283.500 backend HTTP requests. **Målinger er ikke fakturerede beløb, kapacitetstest eller komplette SQL query counts.** Ekstra servertrafik og mange samtidige mediesessioner er endnu ikke dækket af disse tal.

Render-log viser, at flere 502-svar var sammenfaldende med deployments i testperioden; driftsårsag for alle 5xx er ikke dokumenteret. Persistent disk betyder driftsafbrydelse ved deploy; hæv ikke kapacitet eller antal workers uden en særskilt vurdering af den lokale PostgreSQL-kontrakt.

Følg den eksisterende driftsbaseline i `docs/PLANIQ_DISPLAY_63_COST_PERFORMANCE_BASELINE_20261117.md` og dens scripts. Duplikér ikke allerede fjernede DB-pollere eller allerede implementerede capability-gates.

## Nuværende medieimplementering (source-backed)

**Livestream:** Klientens `livestream_uploader.py` uploader HLS `.m3u8` og `.ts` gennem HTTPS PUT. Browseren henter manifest og segmenter gennem HTTP HLS / hls.js. Browserens viewer-heartbeat udsteder afgrænset capability; start/stopkommando-agenten har WSS wake + HTTPS long-poll fallback. HLS video kræver ikke WebSocket. 1249-kandidatens særlige `_normalize_hlssink_media_sequence` fix er endnu ikke samlet releasegodkendt. Undgå ny streamingmotor uden fysisk evidens.

**Remote Desktop:** Den aktuelle 1248-klient producerer native JPEG, Base64 i JSON gennem control WebSocket eller HTTP-relay. Kontrol-input bruger en særskilt lane. 63D-21/22-fysiske tests beviste bedre mus ved TCP-pressure-kontrol og lav billedopløsning, men 960×404/kvalitet 40 var ulæseligt. PR #402 er stadig **draft**, ikke merged. Ændringerne derfra er hypoteser, ikke godkendte produktionsforbedringer.

## Arkitektursammenligning og blokeringer

| Kandidat | Mulig fordel | Uafklaret forhold før implementering | Indstilling |
|---|---|---|---|
| GNOME Remote Desktop *Remote Assistance*, RDP til aktiv Wayland-session + kontrolleret reverse-gateway | Naturlig skriftrendering via RDP og eksisterende GNOME-skærm | Findes/kan bruges på Viborg1? Kiosk-oplevelse, auth, cert, reverse-tunnel over kun outbound HTTPS, reel browserserver-memory og browser HTTP fallback | **Fysisk read-only preflight først** |
| Apache Guacamole + guacd (og evt. Java/Tomcat) | Dokumenteret browserprotokol med WS/HTTP tunneling, RDP-klient | Standard Docker-konfiguration er flere containere; 512 MiB budget + netværksvej fra server til RDP bag NAT er **ikke** afklaret; guacd må aldrig eksponeres offentligt | Ikke tilføj ekstra service nu |
| Eksisterende ClientFlow JPEG med tile/delta/dirty-rect og prioriteret input | Kan genbruge nuværende FastAPI/HTTPS-relay uden ekstra service | Kræver korrekt billedcache, sekvenser, rekonstruktion, fil-/clipboard-sikkerhed, tab/restore og browser end-to-end latencytests | Alternativ hvis RDP-pilot ikke består |
| WebRTC | Effektivt ved video | Må ikke introducere UDP/TURN/STUN/eksternt servicekrav; 443-only fallback stadig nødvendig | Ikke obligatorisk arkitektur |
| Livestream HLS som i dag | Browserportabilitet og HTTP/443, ingen ny service | Manifest-konsistens, reel latency, disk, medie-trafik/buffer og auth under 443-only test | Behold og afprøv |

**Kritisk netværksfaktum:** GNOME Desktop Sharing på en klient bag firewall kan ikke bare nås af Guacamole på Render. En godkendt, **klientinitieret og identitetsbundet reverse-forbindelse** eller en anden sikker topologi skal konkret designes og testes; åbning af port 3389/3390 på internet er ikke tilladt.

**Kiosk-faktum:** GNOME *Remote Login* kan logge den lokale session ud; brug kun *Desktop Sharing / Remote Assistance* til pilot, aldrig headless/remote-login til erstatning af kioskdesktop.

## Fasegate A – fysisk, read-only Ubuntu/GNOME capability inventory

På Viborg1, som root, kør `python3 scripts/audit_viborg1_rdp_capability.py` fra en betroet kopi af denne repo-branch. Scriptet læser kun:
- verificeret hostname og klient ID=3, GNOME Remote Desktop-pakke og `grdctl`-tilstedeværelse;
- kioskbrugerens eksisterende D-Bus/runtime og status på *user*-tjenesten uden at enable/starte den;
- kun antal og lokal-/ikke-loopbackstatus for allerede lyttende RDP 3389/3390 sockets; ingen IP-adresser, certifikater, brugernavne, passwords eller tokens;
- eksisterende ClientFlow Remote Desktop agent-aktivitet.

**Nej:** Ingen pakkeinstallation, `grdctl enable`, læsning af adgangsoplysninger, netværksforbindelse, firewall-regel, serviceændring, reboot eller diskwrite.

Helt legitimt resultat: `gnome_remote_desktop_installed=false`, `user_service=unknown` eller ingen lytter. Det er *ikke* bevis for, at funktionen ikke kan installeres; næste gate kræver særskilt, reversibel opt-in.

## Fasegate B – godkendt RDP feasibility-pilot (endnu IKKE autoriseret/udført)

1. Vurdér Fasegate A uden skjulte credentials. Design og test en isoleret RDP-motor til *eksisterende kioskdesktop*, mens kiosk-browser fortsætter normalt.
2. Bevis 443-only udgående fra klient og browser, og HTTPS-fallback uden WebSocket gennem faktisk Render-proxy. Ingen public RDP, ingen offentlig guacd, ingen løse auth cookies.
3. Mål skriftlæsbarhed ved 2560×1080; bevæg, drag, klik, keyboard, clipboard og revocation. Sammenlign med brugerens acceptable museoplevelse fra 63D-22, men uden 960px-ulæselige billeder.
4. Mål RAM/CPU for app + PostgreSQL + evt. gateway, aktivt medie MB/min og p95 faktisk input-to-painted-frame. Stop ved OOM/træghed/autorisationstab.
5. Test automatisk reconnect, session-udløb, force-close og recovery uden at miste eksisterende kiosk-session. Rolback uden geninstallation.

## Fasegate C – HLS + omkostnings- og firewallmåling (endnu IKKE autoriseret/udført)

Test almindelig HTTPS uden WebSocket browser/klient, HLS-manifest & segment continuity, stale recovery og reel live-delay. Korrekt sekvensnormalisering og client generation kræves. Mål både 1 bruger og flere *godkendte* samtidige brugere, ikke fabrikerede benchmarks. Brug driftsbaseline-scripts til før/efter-måling og skel fakturerbar trafik fra HTTP request-tællinger.

## Accept- og sikkerhedsgrænser

- PR #402 forbliver draft, og release 1249 tilbageholdes, til arkitektur og fysiske tests er afklaret.
- Ingen ny Render-service, diskændring, Neon, betalingstjeneste, miljøvariabel, database-migration, production deployment, PR-merge eller ClientFlow-release i denne fase.
- Scriptets returkode 0 betyder kun read-only preflight gennemført; **ikke** at RDP/HTTPS, Guacamole eller 100 klienter er godkendt.

## Verificerbare primærkilder

- Ubuntu 26.04 Desktop Sharing (eksisterende session vs. Remote Login): https://ubuntu.com/desktop/docs/en/26.04/how-to/share-your-desktop-remotely/
- GNOME Remote Desktop modes: https://github.com/GNOME/gnome-remote-desktop/blob/main/docs/configuration.md
- Apache Guacamole Docker-komponenter og guacd sikkerhed: https://guacamole.apache.org/doc/gug/guacamole-docker.html
- Guacamole WSS/HTTP-tunnel og proxybuffering: https://guacamole.apache.org/doc/gug/reverse-proxy.html
- Apple HTTP Live Streaming: https://developer.apple.com/documentation/HTTP-Live-Streaming

## Fysisk Viborg1-preflight – bekræftet 21. november 2026

Operatøren udførte den skrivebeskyttede fase-63D-24 kontrol på `viborg1-NUC14MNK-B2` (CLIENT_ID 3). Output:

| Observation | Fysisk resultat |
|---|---|
| Root, host og client ID | PASS |
| `gnome-remote-desktop` installeret | true |
| `grdctl` tilgængelig | true |
| `clientflow-kiosk` user D-Bus | true |
| `clientflow-kiosk` GNOME shell | true |
| GNOME Remote Desktop user service | inactive |
| Existing ClientFlow Remote Desktop agent | active |
| RDP listener ports 3389/3390 | 0 |
| Ikke-loopback RDP listener | false |
| Konfiguration ændret | false |
| Netværks-/RDP-forbindelse testet | false |

**Gate A godkendt som inventar, ikke som RDP-feature.** Ubuntu/GNOME-dokumentationen bekræfter, at `Desktop Sharing` knytter til eksisterende session, men GNOME Desktop Sharing kan som standard åbne en RDP TCP-port (3389/3390). Derfor må hverken `grdctl rdp enable`, `systemctl --user enable --now gnome-remote-desktop.service` eller udlevering af RDP credentials udføres før et specifikt, fysisk rollback- og host-firewall-gate; en kommunal browser kan ikke kommunikere direkte til RDP bag NAT.

Næste fasegate er derfor et særskilt **skrivebeskyttet kontroltrin af installeret GNOME version, dækkende host firewall-regler og sikker isolation af RDP til loopback**. En eventuel RDP-start skal være tidsbegrænset og skal verificere, at porten aldrig er eksponeret på Wi-Fi/Ethernet/LAN. Dette er endnu ikke gennemført. Behold 1248 og draft PR #402 uændret.

## Fysisk RDP-firewallkontrol – 21. november 2026 (sikkerhedsstop)

Brugerens anden **skrivebeskyttede** kontrol på Viborg1 viste:

| Observation | Resultat |
|---|---|
| Pakkeversion `gnome-remote-desktop` | `50.2-0ubuntu0.1` |
| System-Remote Login `is-active` | `inactive` |
| System-Remote Login `is-enabled` | `disabled` |
| ClientFlow RD-agent | `active` |
| `ufw status` | `Status: inactive` |
| Aktuelle nftables-INPUT base chains | `0` |
| Nuværende dokumenteret RDP-isolation | `false` |
| Konfiguration ændret | `false` |

**BESLUTNING: Ingen GNOME RDP-aktivering, før en konkret og reversibel isolation er på plads.** Fravær af nft INPUT chains og inaktiv UFW betyder kun, at de to mekanismer ikke beskytter RDP i den observerede netværksnamespace; upstream firewall- og netværkspolicystatus er ikke bevist. GNOME Desktop Sharing bruger ifølge Ubuntu normalt port 3389 eller 3390, og et almindeligt `grdctl rdp enable` er **ikke** en garanti for loopback-only binding. Ingen offentlige/LAN RDP-porte accepteres.

Dokumenteret tilgang før en ændrende pilot:
1. Undersøg *read-only* den installerede `nft`-kommandos parser/understøttelse, 50.2 `grdctl`-optioner og mulig RDP local-client test.
2. Vælg én dedikeret, genstartssikker **default-deny for RDP på ikke-loopback** på IPv4 **og** IPv6 (for eksempel en lille `inet` nftables INPUT drop-chain), men **ændr ingen eksisterende regler eller andre porte**. Reglerne skal først verificeres atomisk, og automatisk fail-safe rollback skal sættes op **før** RDP-tjenesten startes.
3. Bind eller verificér RDP-porten faktisk, og kontroller isolation lokalt og fra separat LAN-vantage point. Hvis `grdctl` ikke understøtter eksplicit loopback-bind, må ingen dokumentation påstå det. Afvis hvis en ikke-loopback forbindelse kan oprettes.
4. Konfigurer kun GNOME *screen sharing* for den eksisterende `clientflow-kiosk` Wayland-session; **aldrig** system-Remote Login, og gendan alle ændringer efter pilot.
5. Før integration: dokumentér, hvordan **udgående, klientinitieret HTTPS/443** i ClientFlow sikkert kan transportere RDP til eksisterende Render-backend uden at gøre RDP/guacd offentligt. Dette er ikke etableret ved host firewall-gaten.
6. Mål læsbar tekst, mus/drag, input-to-painted-frame, CPU/RAM, 443-proxykompatibilitet, trafik og 2 GB disksikkerhed; behold 1248 indtil godkendt.

Officiel dokumentation: https://ubuntu.com/desktop/docs/en/26.04/how-to/share-your-desktop-remotely/ (Desktop Sharing 3389/3390 og Remote Login forskel), https://documentation.ubuntu.com/security/security-features/network/firewall/nftables/ (nft rulesets), https://netfilter.org/projects/nftables/manpage.html (INPUT hooks og regeltraversal).

## Fysisk nftables-dry-run – 21. november 2026

Operatøren har udført `sudo nft --check --file -` på Viborg1 med en specifik `table inet clientflow_rdp_preflight`, en `input`-hook ved priority `-100` og `iifname != "lo" tcp dport {3389,3390} drop`.

Output:
- `NFT_SYNTAX_VALID=True`
- `RULES_INSTALLED=False`
- `RDP_ENABLED=False`
- `READ_ONLY=True`

**Resultat:** Syntaksgate PASS. Dette er *ikke* bevis for, at fremtidigt installerede regler faktisk beskytter RDP, eller at en HTTPS-only reverse tunnel findes.

**Næste ændrende gate:** En isoleret nft guard-only øvelse kan installere denne *dedikerede* inet-tabel kortvarigt, verificere den installerede regel og derefter fjerne netop den, med watchdog-rollback. GNOME RDP skal fortsat være deaktiveret i denne øvelse. Først derefter kan der udarbejdes en særskilt fuld RDP-pilot, hvor en autoriseret, krypteret localhost RDP-session og sikker udgående HTTPS/443 transport verificeres uden at åbne LAN-port. En RDP/guacd implementation er ikke automatisk berettiget af denne PASS.

## Fysisk 63D-25 guard-only øvelse – PASS, 21. november 2026

Operatøren har kørt den SHA-256-fastlåste kilde fra commit `6c7497b08fe9aef27ce36cdd2afbce36ed298880` på Viborg1, `client_id=3`, som root.

- `PINNED_SOURCE_SHA256=PASS`
- `ROLLBACK_TIMER=ARMED_120_SECONDS`
- `KERNEL_RULE_INSTALLED_AND_VERIFIED=True`
- `RDP_ENABLED=False`
- `RDP_CONNECTION_TESTED=False`
- `NFT_GUARD_REMOVED=True`
- `ROLLBACK_FAILSAFE_ARMED=False`
- `RDP_NEVER_ENABLED=True`

**Resultat:** Midlertidig nftables `inet` guard kunne installeres, observeres og fjernes igen uden RDP-start. Dette er ikke en empirisk test af ekstern RDP-blokering, live-TLS, RDP-autentifikation eller browserintegration. Brug ikke samme firewall-tabelnavn som en fremtidig permanent sikkerhedspolitik.

**Næste gate:** Inden GRD ændres skal den eksisterende kioskbrugers *user-mode* RDP-konfiguration inventariseres uden at printe TLS-paths, usernames, password eller keyring-indhold. Vurder GNOME 50.2 `grdctl` for *Remote Assistance/Screen Sharing* og design rollback af alle ændrede dconf/GSettings-, credential-, TLS- og systemd-state. Der må ikke startes system-mode remote login eller headless session. Reverse HTTPS/443-tunnel til Render er stadig udesignet og ikke dokumenteret som mulig inden for eksisterende Starter-budget.

## Fysisk 63D-26 GNOME RDP baseline – PASS, 21. november 2026

Operatøren verificerede på Viborg1 (ID 3) med skrivebeskyttet user-mode `grdctl status`, `gsettings`, systemd og nft:

| Kontrol | Observeret |
|---|---|
| `grdctl status` og `gsettings` kan læses | Ja |
| `org.gnome.desktop.remote-desktop.rdp enable` | `false` |
| TLS-cert og privatnøglesti konfigureret | Begge mangler |
| `gnome-remote-desktop.service` user | `inactive` / `disabled` |
| Tidligere nft guard | `absent` |
| Resterende rollout-/rollback-timere | 0 |
| OpenSSL | Tilgængeligt |
| `winpr-makecert`, `xfreerdp3`, `xfreerdp` | Ikke installeret |
| `/opt/clientflow/active` | `clientflow-1.3.47-seq-1248` |
| Passwords, TLS-filer eller GSettings ændret | Nej |

**Fysisk konklusion:** GNOME Screen Sharing kan undersøges uden at migrere runtime eller installere GNOME RDP. Før egentlig aktivering skal TLS, credential-oprettelse og rollback planlægges. Ingen test har endnu vist et fungerende RDP-skærmbillede.

### Vigtigt sikkerhedsfund: Portforhandling

GNOME's RDP-GSettings-skema dokumenterer **`negotiate-port=true` som standard**, hvilket kan få Desktop Sharing til at lytte på første ledige af **10 porte startende ved `port`**. Ved standardport 3389 svarer det til 3389–3398. Derfor er den gamle 63D-25 nft guard, som kun blokerer 3389 og 3390, **IKKE tilstrækkelig til en ændrende RDP-pilot**; den gamle guard-only øvelse var sikker, fordi RDP aldrig var aktiv.

**Hard stop:** Før aktivering skal `port`, `negotiate-port`, `screen-share-mode`, `view-only` og `enable` aflæses i kioskbrugerens eksisterende GNOME-D-Bus. Pilotdesign skal sætte et eksplicit, verificeret portvalg (helst forhandlingsfri) med rollback af oprindelige GSettings-værdier og samtidig firewallblokering på alle potentielt valgte porte for både IPv4 og IPv6. Verificér kernereglen og faktiske listeners *før* nogen LAN-eksponeringstests. Ingen vellykket `nft --check` alene giver denne garanti. `grdctl --system` og `--headless` er forbudt i denne pilotscope.

**Kilder:** https://sources.debian.org/src/gnome-remote-desktop/51.0-1/src/org.gnome.desktop.remote-desktop.gschema.xml.in (51.0 skema som dokumenterer 10-port forhandling; lokal 50.2 skal inspiceres), https://manpages.ubuntu.com/manpages/resolute/man1/grdctl.1.html (eksakt installeret pakkeversion), https://github.com/GNOME/gnome-remote-desktop/blob/main/docs/configuration.md (eksisterende-session Remote Assistance og TLS).

## Fysisk 63D-27 RDP/port/skærmdelings-gate – verificeret 21. november 2026

Den seneste skrivebeskyttede måling fra Viborg1 (CLIENT_ID=3) dokumenterer den faktiske brugerindstilling:

| GSettings-nøgle | Læst værdi |
|---|---|
| `port` | `uint16 3389` |
| `negotiate-port` | `true` |
| `screen-share-mode` | `'mirror-primary'` |
| `view-only` | `true` |
| `enable` | `false` |
| `auth-methods` | `['credentials']` |
| TCP listeners 3389–3398 | Ingen |
| UDP listeners 3389–3398 | Ingen |
| Konfiguration ændret | Nej |

**Beslutning for fysisk RDP-pilot:** Bevar `mirror-primary` og `auth-methods=['credentials']`. Hvis piloten skal kunne styre mus og tastatur, skal `view-only` midlertidigt sættes til `false`. `negotiate-port` må ikke forblive `true` med en 3389/3390-only firewall; brug et eksplicit, verificeret portvalg og bloker alle mulige RDP-porte på ikke-loopback for IPv4 *og* IPv6 som defense-in-depth. Den faktiske port og lytter skal observeres efter aktivering.

**Reboot-sikkerhed / rollback:** Den eksisterende 63D-25 guard-only timer **sletter** sin firewall-tabel efter 120 sekunder. Den er *kun* sikker, fordi den aldrig aktiverer RDP. Den må **aldrig genbruges** som failsafe for en aktiv RDP-pilot: Ved proceskrasj ville den efterlade RDP aktiv og fjerne beskyttelsen. En rigtig RDP-pilot skal have et selvstændigt watchdog-flow, der først stopper/disable RDP og verificerer lytteren lukket og alle GSettings restored, og **derefter** kan fjerne firewallreglen. Ved fejl skal firewallreglen bevares, og der skal findes beskyttelse ved reboot før GNOME-brugersessionen startes. Certifikat/private key og credentials må ikke logges eller sendes i argumenter/PR. Restore må ikke slette eksisterende secrets uden baseline og ejerskab.

**Gate 63D-27:** GNOME var fortsat deaktiveret, og den primære session er korrekt type. En aktiv RDP-billed-/inputtest er endnu **ikke** udført, og HTTPS/443-transportsystemet er ikke design- eller lasttestet. PR #403 er draft, release 1248 uændret.

## Fysisk 63D-28 credential-baseline – PASS, 21. november 2026

Operatøren udførte en skrivebeskyttet `grdctl status` med eksplicit filtrering (ingen rå statusdump, ingen `--show-credentials`). Output:

- `RDP_USERNAME_STATE=EMPTY`
- `RDP_PASSWORD_STATE=EMPTY`
- `SAFE_TO_CREATE_NEW_PILOT_CREDENTIALS=True`
- `CREDENTIAL_VALUES_PRINTED=False`
- `CONFIGURATION_CHANGED=False`
- `READ_ONLY=True`

Dette bekræfter, at *der ikke vises eksisterende credential-værdier i den undersøgte GNOME user-mode RDP status*. Det beviser ikke fremtidig write/clear-funktion, og almindelig `grdctl status`-output skal fortsat filtreres.

### 63D-29 sikkerhedsgate

Før nogen lokal RDP-start:
1. Brug alene `clientflow-kiosk` user-mode `grdctl rdp` og `gnome-remote-desktop.service`; **aldrig** `--system`, Remote Login, xrdp eller --headless.
2. TLS/private key må kun oprettes i et unikt, filrettighedsbeskyttet testkatalog. Credential må **ikke** optræde som command-line argument (GNOME 50.2 dokumenterer en stdin-variant), miljøvariabel, journal, GitHub eller delt rapport.
3. Dokumentér en atomisk, persistent nft-beskyttelse af forhandlingsområdet på **TCP og UDP** for begge IP-versioner og verificér et boot-time fail-closed service dependency. Den gamle 63D-25 timer må ikke fjerne en aktiv RDP-guard.
4. Implementér og test root-owned watchdog, som gendanner RDP `enable=false`, `view-only=true`, `negotiate-port=true`, TLS tomt, credentials tomme og `systemctl --user` disabled/inactive; fjern **først** firewallregler, når RDP beviseligt er stoppet, inklusive efter reboot. Ved uvished efterlades garderingen aktiv.
5. Lokal forbindelse skal kun ske via loopback (eventuelt en særskilt godkendt, autentificeret SSH-forward til localhost); SSH-forward er en isoleret fysisk test, **ikke** den endelige kommunale HTTPS/443-transport.
6. Remote Desktop skal observeres med **læsbar tekst ved skærmens faktiske opløsning**, input samt HLS-simultanitet, CPU/RAM, reconnect, netværksafbrydelse og rollback. Genbrug den eksisterende Render-server, hvis 512 MiB/CPU målinger består.

**STOP:** 63D-28 PASS alene giver ikke tilladelse til at tænde RDP. PR #403 forbliver draft.

## 63D-29 – boot-ordnet, ikke-destruktiv netværksbeskyttelse (kodekandidat)

Fysisk credential-baseline er PASS, men GNOME RDP forbliver slukket.

Ny kandidat: `scripts/clientflow_63d29_persistent_rdp_guard.py` med `install/status/remove`. Den opretter en dedikeret `nftables` `inet` INPUT drop-tabel for **TCP+UDP 3389–3398 på ikke-loopback** (både IPv4/IPv6), plus en uafhængig systemd boot-unit, som ordnes før `sysinit.target`, `network-pre.target` og `display-manager.service`. Ingen eksisterende nftables-tabel overskrives, og ingen GNOME RDP-login, TLS, GSettings, Sessioner, Render eller ClientFlow-release ændres.

`remove` stopper ved en GNOME RDP system/user-service som er aktiv, `enable != false` eller en RDP TCP/UDP listener i den undersøgte port-range. Eksisterende guard skal matche den præcise dedikerede unit- og nft-fil, før fjernelse tillades.

**Denne kode er ikke i sig selv en RDP-aktiveringsautorisation:** En efterfølgende kildeaudit har nu tilføjet en særskilt `display-manager.service` drop-in med `Requires=clientflow-63d29-rdp-guard.service` og `After=...`, og den tidligere `ConditionPathExists=` er fjernet, så manglende firewallfil ikke blot får enheden til at blive sprunget over. `remove` kræver inaktiv RDP og fjerner drop-in **før** systemd-guard stoppes, ellers kan `Requires=` stoppe den aktive kiosk. Der er nu negative tests for både boot-afhængighed og ukendte drop-in-filer. Den faktiske boot-dependency, failure-injection og GPIO/sessionkæde er **ikke fysisk verificeret**, og en selvstændig RDP-first watchdog for credentials/TLS/portændringer mangler fortsat. Giv derfor ingen aktiv RDP-autorisation ud fra et PASS på firewalløvelsen alene. Prøv ikke at bruge 63D-25 den tidsstyrede guard, den sletter firewallreglen uden RDP-stop.

**Fysisk rækkefølge:** 63D-29 skal først passere GitHub CI og isoleret boot-/failure-injection-test. Derefter er en *guard-only* installation på Viborg1 tilladt som separat observeret test – RDP forbliver slukket. En fremtidig aktiv RDP-pilot skal laves som en samlet kandidat med TLS, hemmeligheder via stdin (verificér den konkrete GRD 50.2 CLI), autonom watchdog som stopper GNOME først, fail-closed ved boot samt en autentificeret localhost testklient. Ekstern/kommunal browser-HTTPS/443 transport er en anden fase, ikke bevist her.

## 63D-29 – fysisk fejl og sikkerhedsstop (21. november 2026)

Operatøren udførte den kildehash-verificerede `drill` fra commit `c40c8784a9bce626d3a360be62f0ff1224c9a605`. Output:

```text
PINNED_SOURCE_SHA256=PASS
PREFLIGHT=PASS
STOP= RuntimeError STOP: Kernereglerne matcher ikke expected TCP/UDP drop
NO_RDP_SERVICE_WAS_STARTED_BY_THIS_TOOL=True
```

**Dette er ikke en bestået firewalløvelse.** Koden installerede (eller forsøgte at installere) systemd-unit, display-manager `Requires=/After=` drop-in og nftables-regler **før** verifikationen. Da `guard_verified()` fejlede, stoppede `drill` inden `remove_guard()`. Eventuelt installeret firewall, unit og boot-afhængighed kan derfor være tilbage på Viborg1. Operatøren er instrueret i ikke at genstarte, aktivere RDP, installere igen eller slette filer før en read-only tilstandskontrol.

Sandsynlig parserårsag: nftables skriver talprioriteten `-150` som det semantisk identiske nøgleord `mangle`, mens parseren kun accepterede `-150` eller `raw + 150`. Dette er verificeret som nft-prioritets-alias i den officielle manpage, men **den faktiske kerneregel på Viborg1 er endnu ikke læst**, og andre formatteringsafvigelser kan ikke udelukkes. Rettelsen tilføjer `mangle` med positiv og negativ regressionstest. Der er fortsat **ingen fysisk isolationstest, boot-failure-drill eller aktiv GNOME RDP-test**.

**Recoverygate:** læs udelukkende den dedikerede `nft list table inet clientflow_63d29_rdp_guard`, `systemctl show/is-enabled/is-active` for den tilføjede unit og `display-manager.service`, de præcise oprettede filers tilstedeværelse, GNOME user/system service og GSettings `enable`. Først efter denne observation kan en præcist afgrænset, godkendt cleanup udføres, som ikke stopper display-manager eller fjerner anden firewallkonfiguration. Selv en grøn CI kan ikke erstatte denne efterkontrol.
