# PlanIQ Display – komplet vurdering af Terminal-hjælpekommandoer

Kilde: den friske `display-planiq-main(20261021-135309).zip` (GitHub `main` PR #302, SHA `563ee403eb5aaa7b5c920c81c0c5eab00e50ac09`). Denne ændring er kun frontend, tests, audit og checksum-manifest. Ingen backend-API, Terminal-auth, livestreampolicy, klientinstallation, OS-netværkspolitik eller releasekatalog ændres.

## Eksisterende hjælpescripts: bevar alle 15

| Gruppe | Kommando | Beslutning | Begrundelse |
|---|---|---|---|
| Runtime | ClientFlow samlet status | Bevar | Samlet driftsbillede og hurtig triage. |
| Runtime | Display / kiosk browser | Bevar | Browser, kiosk og guard-status. |
| Runtime | Aktiv release / updater | Bevar | Deployment, status og rollback-fejlsøgning. |
| Runtime | Livestream v2 status | Bevar | Streamproducentens egen tilstand. |
| Runtime | Terminal status | Bevar | Fejl i terminaltransport og tilhørende tjenester. |
| Runtime | Remote Desktop status | Bevar | Fejl i separat RD-transport/broker. |
| Runtime | Aktive ClientFlow units | Bevar | Kompakt systemd-oversigt. |
| Ubuntu/host | Ubuntu / APT health | Bevar | `dpkg`/APT-kontrol uden opdatering. |
| Ubuntu/host | Disk, RAM og oppetid | Bevar | Ressourcefejl og performance. |
| Ubuntu/host | Netværk, DNS, tid og backend | Bevar | Overordnet forbindelses- og tidsdiagnose. |
| Logs | Display/browser logs | Bevar | Optrævling af Chrome/kiosk-fejl. |
| Logs | Status/System logs | Bevar | Presence og systemkommandoer. |
| Logs | Livestream logs | Bevar | Medie- og uploadfejl. |
| Logs | Terminal logs | Bevar | Remote-terminal-problemer. |
| Logs | Remote Desktop logs | Bevar | RD/capture/broker-problemer. |

Ingen af de 15 er dokumenteret obsolete i den seneste kilde. Overlap mellem samlet status og specialiserede kommandoudtræk er nyttigt under fejlsøgning; ingen kommandofjernelse eller ændring af privilege-grænser.

## Nye Admin-hjælpere

1. **WiFi / NetworkManager diagnose**: skrivebeskyttet `nmcli`-oversigt over WiFi-adapter, radio, signal/netværk (cache uden tvungen rescan), aktive og gemte profiler, IP, default-route og DNS. Ingen `--show-secrets`, ingen ændring af netværk eller service, ingen journal med mulig hemmelig data.
2. **Tilføj WiFi-profil (uden aktivering)**: interaktiv root-beskyttet TTY-guide til at vælge eksisterende WiFi-interface, SSID, skjult SSID, WPA2/WPA3-personlig type og adgangskode. Kræver eksplicit `OPRET`. Der skrives en NetworkManager-keyfile med `0600`-rettigheder via **Bash-indbyggede `printf`** til midlertidigt, root-beskyttet område under `/run` og installeret i NetworkManagers systemprofilmappe. Profilen indlæses med `nmcli connection load`, men har `autoconnect=false`. Den aktive forbindelses UUID/enhed verificeres uændret. Ved fejl forsøges oprydning af *kun* den nye UUID og den nye fil.

Adgangskoden passerer aldrig gennem `nmcli`-argumenter eller frontend-supportkommandoen. Den er dog nødvendigvis lagret i den nye root-beskyttede NetworkManager-profil efter oprettelse. Terminal-/rootadministratorer har dermed adgang til den; lokale auditlogs og supportudtræk skal fortsat behandles fortroligt. Input optræder ikke i selvvalgte normale logudskrifter. Ingen succesbesked før NetworkManager-profilen er indlæst og kontrolleret.

Kun WPA2/WPA3-Personal (PSK/SAE). Ikke Enterprise/802.1X, captive portal, WiFi-hotspot eller automatisk skift af default-route. En profil med `autoconnect=false` hjælper med fjernklargøring, men etablerer *ikke* forbindelse af sig selv.

## Udeladt med vilje

- Automatisk WiFi-aktivering/deaktivering, sletning eller ændring af eksisterende profil, radio-toggling, tvungen rescan, ændring af routing eller reboot.
- Omgåelse af Admin-terminalens godkendelse, root/sudo til kioskbrugeren eller ændrede Polkit-regler.
- WiFi-cutover via remote adgang uden fysisk fallback og eksplicit rollback-plan; en sådan funktion kræver separat design og fysisk test.
- Livestream-start/stop-ændring; PR #301's accepterede isolation bevares.

## Dokumenterede kontroller og resterende accept

- Fem frontend-kilde-/sikkerhedskontrakttests, Bash-syntakskontrol af wrapper og indre Bash-script.
- Simuleret pseudo-terminal/NetworkManager: bekræftelse, oprettelse i midlertidig mappe, keyfile i `0600`, `autoconnect=false`, ingen `nmcli connection up/down` og uændret aktiv uplink. Dette er en *lokal simulation*; NetworkManager-parseren og rigtig WiFi-radio er ikke fysisk testet.
- GitHub CI er endelig gate. Efter merge: kort skrivebeskyttet fysisk WiFi-diagnose fra autoriseret Admin-terminal. Oprettelse af testprofil må kun ske på godkendt test-SSID og uden aktivering; ingen ændring af Heidi1's eksisterende forbindelse.

## Senere optimering

Kontrollér med fysisk NetworkManager, at alle understøttede SSID/password-kombinationer parses korrekt. Separat, eksplicit godkendt remote WiFi-cutover kan eventuelt designes med NetworkManager-checkpoint/rollback, men må ikke automatisk introduceres i denne fase.
