# PlanIQ Display · 63D-30 · Reversibel GNOME RDP-test på Viborg1

Dato: 21. november 2026. **Status: draft CI-kandidat, ikke en fysisk eller produktionsgodkendt RDP-løsning.**

Denne fase bygger oven på 63D-24–29 og PR #403. Det dokumenterede fysiske 63D-29 rollback resultat var `RECOVERY_STATUS=PASS`: den midlertidige firewalltabel, systemd-unit og display-manager-drop-in blev fjernet, display-manager forblev aktiv, og GNOME RDP var slukket. Viborg1 kører fortsat test-release `1.3.47/1248`.

## Formål, økonomi og firewallkrav

Vi undersøger GNOME 50.2 *Remote Assistance / Desktop Sharing* som kilde til en skarp, lavforsinket Remote Desktop-video, i stedet for yderligere komprimering af det eksisterende JPEG-billede. Det er en **lokal motor-/kioskfunktionstest**, ikke en komplet PlanIQ-webintegration. Ingen ændringer i Render Docker, PostgreSQL, frontend, backend, ClientFlow-agent, release eller kiosk-login. Ingen ny Render-service, Neon, Guacamole, RDP-licens, TURN/STUN eller betalt abonnement.

Den endelige løsning skal fortsat kunne anvende godkendt klientinitieret udgående **HTTPS/443**, også hvis WebSocket er blokeret. **GNOME RDP er ikke HTTPS, og denne kandidat etablerer ingen reverse-HTTPS-tunnel eller browsergateway.** Derfor er netværkskompatibilitet og 100-klienters kapacitet stadig uverificeret. Ingen RDP-port må åbnes på LAN/Wi-Fi/internet.

## Kildebegrundelse

GNOME upstream dokumenterer, at brugerbaseret `grdctl rdp` deler den eksisterende aktive session og konfigureres med TLS, særskilte credentials og `systemctl --user`. GNOME har også separate `--system` Remote Login og `--headless`; **ingen af dem må anvendes i piloten**. Det installerede Ubuntu 26.04.1 har `gnome-remote-desktop` `50.2-0ubuntu0.1`, brugeren `clientflow-kiosk` har aktiv GNOME/Wayland og user-D-Bus.

Primærkilder:
- https://github.com/GNOME/gnome-remote-desktop/blob/main/docs/configuration.md
- https://manpages.ubuntu.com/manpages/resolute/man1/grdctl.1.html
- https://github.com/GNOME/gnome-remote-desktop/blob/main/man/grdctl.txt
- https://sources.debian.org/src/gnome-remote-desktop/51.0-1/src/grd-ctl.c (GNOME 51-kilde understøtter stdin-prompt med 0 args; verificér operationen på fysisk 50.2 før tillid)
- https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html

## Allerede fysisk målte baselineværdier på Viborg1

| Kontrol | Fysisk resultat |
|---|---|
| Host / ClientFlow identity | `viborg1-NUC14MNK-B2`, klient ID 3 |
| GNOME Remote Desktop | installeret 50.2, user service `inactive/disabled` |
| GNOME system Remote Login | `inactive/disabled` |
| RDP enabled | `false` |
| port / negotiation | `uint16 3389` / `true` |
| screen-share-mode / view-only | `mirror-primary` / `true` |
| auth-methods | `['credentials']` |
| TLS/key | tomme |
| credentials | Username = empty, Password = empty |
| TCP/UDP 3389–3398 | Ingen lyttere |
| 63D-29 residual guard, unit, drop-in | Begge systemd og nft fjernet, efterkontrol PASS |
| RDP-klient på Viborg1 | `xfreerdp`, `xfreerdp3` og `winpr-makecert` er **ikke** installeret; OpenSSL findes |

## Kodekandidat

`scripts/clientflow_63d30_local_rdp_pilot.py`, testet i `scripts/tests/test_clientflow_63d30_local_rdp_pilot.py`. Den bruger den eksakt SHA-256-fastlåste, fysisk recoverytestede `scripts/clientflow_63d29_persistent_rdp_guard.py`.

CLI-kommandoer:
- `stage`: Kopiér kun pilot- og 63D-29-guardkilde til et root-ejet, privat katalog under `/var/lib/clientflow`, og installér en root-owned `systemd`-timer/service. Ingen RDP-ændring. Staging kræver de to kilder side om side, SHA-256 verificeret af operatøren.
- `start`: Verificér maskine/uid, uændret baseline, tomme credentials og inaktivt RDP. Opret **root-ejet pilotstate før muterende handlinger**, installér og verificér persistent nftables `inet` drop-regel for TCP+UDP 3389–3398 på alle ikke-loopback interfaces, kontrollér timer og display-manager afhængighed. Først derefter midlertidig self-signed TLS i kioskbrugerens tmpfs `/run/user/<uid>/clientflow-rdp-pilot-63d30`, RDP credentials genereret i root-ejet `/run/clientflow-rdp-63d30/credentials`, og `grdctl rdp set-credentials` via **stdin**. Ingen credentials i kommandoargumenter, miljøvariabler eller logs. Deaktivér portforhandling; bevar `mirror-primary`; aktivér mus/tastatur til test.
- `probe`: Kontroller egen root-watchdog, RDP-setting, nft-guard, præcis port 3389 og **kun** loopback TCP X.224-negotiation. **Bestået probe er ikke bevis for fuld RDP TLS-login, billedpixels eller latency.**
- `status`: Redigeringsfri status uden følsomme værdier.
- `stop`: Slå user-GNOME RDP fra, stop/disable user service, verificér nul TCP/UDP-portlyttere, ryd credentials, gendan alle otte baseline-GSettings og verificér dem, kontrollér system-/user-RDP inaktivt og disabled. **Først derefter** fjern 63D-29-guard med den fysisk recoverytestede `remove`-metode. Slet TLS, credential-file og pilotstate; afmontér root-watchdog.
- `tick`: Persistent root-timer med en planlagt 10-sekunders kadence. Hvis deadline er udløbet, boot-ID har skiftet **eller den faktiske kernel-firewall ikke kan verificeres**, udføres straks samme sikre `stop`. Hvis kioskens user-D-Bus mangler ved reboot, bevares firewall og der forsøges igen ved næste timer-trigger. Kadencen garanterer ikke absolut responstid.
- `unstage`: Kun efter bevisligt ingen aktiv pilot og ingen guard.

Pilotens maksimale normale vindue er **6 minutter**. Den gemmer både wallclock, monotont tidspunkt og boot-ID og har en eksklusiv root-lock mod samtidig start/stop/timer. En fejl i cleanup må ikke åbne netværksadgang.

### Vigtigt om at validere watchdog og boot

En systemd-timer alene giver ikke en absolut garanti for timeout/oprydning. Kombinationen af boot-ordnet nftables-service, display-manager `Requires/After`, persistent 10-sekunders timer, kernel-drop-rule-verifikation, boot-ID-tjek, fysisk negativ network test og root stop-rækkefølge skal gennemgås og testes – især *guard service failure* mens systemet genstarter. Måles dette ikke, **ingen aktiv RDP-autorisation**.

### Sikkerhedsgrænser

1. Kør ikke `start`, `stage`, `stop`, `probe` eller en downloaded Python-kilde på Viborg1 før fuld CI, kildehashkontrol og særskilt review af den komplette fysisk muterende pilot.
2. Beskyt credentials: udskriv **aldrig** `/run/clientflow-rdp-63d30/credentials` til denne chat eller logs; vis den kun lokalt på maskinen ved behov for test.
3. Ingen SSH-tunnel, FreeRDP/RDP-klientinstallering eller 443-proxy er inkluderet i denne kodefase. De kræver egen validering, fordi den eksisterende kiosk ikke har en installeret RDP-testklient.
4. Der må ikke laves `grdctl --system`, `--headless`, `ufw allow`, `nft flush ruleset`, eksponeret 3389 eller runtime-release-mutation.
5. Et systemd-/GSettings-/Secret Service-/nft-driftproblem under rollback betyder **STOP og behold firewall**; genstart ikke blindt.
6. PR #404 er draft, baseret på PR #403, og må ikke merges til `main` eller deployes som ClientFlow-release, før fysisk test og code review er grønne.

## Fysisk acceptmatrix – endnu ikke udført

| Gate | Bestået når | Status |
|---|---|---|
| CI/negative tests + pinned source | All green på præcis SHA | Afventer |
| Boot-fail-closed | nft drop + display-manager strong dependency ved forced service failure/reboot | Afventer |
| Secret/TLS | Ingen secrets i argv/env/logs; korrekt fjernelse efter timeout | Afventer |
| Lokal RDP | Kun loopback X.224, TLS/NLA-auth med autoriseret klient | Afventer |
| Ægte GNOME session | Ingen ny login/logout; samme primære skærm før/under/efter | Afventer |
| Mus/tekst | Læsbar tekst ved faktisk skærmgeometri og acceptabel, målt input-to-frame | Afventer |
| WiFi/LAN | Ikke-loopback RDP 3389–3398 afvises for IPv4/IPv6, også ved reboot | Afventer |
| Recovery | Original GSettings, credentials/tls tom, user-service disabled, guard/timer/artifacts fjernet | Afventer |
| HTTPS/443 | Outbound klientinitieret relay, proxy fallback, auth/revocation, belastning | Ikke denne fase |
| Render/økonomi | Bevis for ingen backend-regression, ingen ny service/licens | Ikke målt |

**Beslutning:** Pilot-kode kan auditeres/CI-testes nu. Fysisk `start` tilbageholdes, indtil de sikkerhedskritiske boot-/timeout-/credential-gates er objektivt efterprøvet.

## Fysisk preflight før nogen `stage` / `start`

Den samlede skrivebeskyttede `scripts/clientflow_63d30_physical_preflight.py` er nu tilføjet med automatiske tests. Den validerer på **fysisk Viborg1/klient ID 3** GNOME 50.2-pakken, præcis release 1248, kiosksessionens D-Bus, alle otte GNOME RDP-baselineindstillinger, tomme credentials uden at vise dem, begge system/user tjenesters inaktiv/disabled, fravær af alle TCP/UDP 3389–3398 listeners, ingen rest af 63D-29 guard/63D-30 pilot, display-manager aktiv, `Requires` ryddet, installeret `grdctl --help` med nødvendige funktioner samt `systemd-analyze calendar` accept af 10 sekunders timer.

Preflight rapporterer også om SSH-serveren kører og om `xfreerdp3`/`xfreerdp` allerede er installeret. **De to sidste oplysninger er kun oplysende** og beviser hverken SSH-adgang fra en Mac eller evnen til at gennemføre RDP TLS/NLA-login og videomåling.

Prøven udfører kun read-only kommandoer og skriver ikke credential- eller TLS-stier. Den kræver grøn fuld CI og grøn PostgreSQL-smoke på den eksakte SHA samt SHA-256-kontrol af preflight-kildefilen, før fysisk kørsel. `PHYSICAL_PREFLIGHT=PASS` er nødvendig, **men ikke tilstrækkelig**, til at tillade RDP-aktivering: boot-fail-closed, watchdog-rollback og fysisk autentificeret RDP-klient skal stadig have en godkendt lokal testplan.

Ingen `stage/start`-kommandoer må sendes til operatøren, før den sidste sikkerhedsgate er dokumenteret.

## Fysisk 63D-30 preflight: credential parser STOP og rettelse (21. november 2026)

Operatøren kørte den SHA-256-fastlåste preflight fra commit `fa343c5b22627b74223de6a515c73a0835b8ba7b`. Både `CI` og `Display single-node PostgreSQL smoke` var PASS, ligesom kildehash. Fysisk resultat: **Alle kontroller undtagen `RDP_CREDENTIALS_EMPTY` viste PASS**; den ene viste `FAIL / UNKNOWN`, og totalen var `PHYSICAL_PREFLIGHT=STOP`. Ingen ændringer i GNOME RDP, systemd, firewall eller netværk. `SSH_SERVER_RUNNING=False`, `FREERDP_CLIENT_INSTALLED=False` (ingen autentificeret RDP-klient klar).

**Konkrete parserfejl identificeret:** GNOME Remote Desktop `grdctl status` udskriver `\tUsername:` og `\tPassword:` (GNOME-kilde, `printf("\\tUsername: %s\\n", ...)`), mens den nye preflight og pilotens credential checker kun accepterede en linjestart med ASCII-mellemrum (`^ *`). Den tidligere fysiske 63D-28-kontrol brugte `^\\s*` og viste tomme credentials. Derfor blev `UNKNOWN` **ikke** et bevis på gemte oplysninger, men en fejl i indrykningsparseren.

**Rettelse:** Begge parserfunktioner accepterer nu kun afgrænset vandret indrykning `[ \\t]*`, kræver præcis ét felt hver for Username og Password og accepterer kun literal `(empty)` som tomt. Enhver duplikat, manglende felt eller `(hidden)` afvises. Negative CI-tests dækker GNOMEs tabulator-indrykning, blandet mellemrum/tab, CRLF, duplikater, skjult/password-nonempty og manglende felter. Ingen rå credential-værdier logges.

**Næste gate:** Fuld CI og PostgreSQL smoke på den nye commit, derefter fysisk **read-only** preflight igen. Først hvis `PHYSICAL_PREFLIGHT=PASS`, kan vi gennemgå `stage/start`-gate og fysisk klientadgang. Der er fortsat **ingen autorisation til at aktivere RDP**.


**Yderligere source-audit (samme rettelse):** `grdctl status` kan både vise `RDP:` og `VNC:` med hvert deres `Password:`-felt. En global `Password`-søgning kan derfor give falsk `UNKNOWN` eller fejlagtig klassifikation. Begge parserfunktioner læser nu **kun den entydige `RDP:`-sektion**, og accepterer dens præcis ét Username/Password-felt. Kilde: GNOME `src/grd-ctl.c` `print_rdp_status`, `print_vnc_status`; GNU/Debian source 51.0, formatet skal stadig verificeres fysisk på 50.2. Negativtests dækker VNC-siden med en anden Password-tilstand samt dublerede RDP-sektioner. Fysisk preflight viser desuden alene ikke-følsomme `GRDCTL_CREDENTIAL_STATUS_QUERY` og `GRDCTL_RDP_STATUS_BLOCK_PRESENT` – ikke hele output eller fejltekst, som kan indeholde indhold fra user-session. RDP forbliver slukket.


## Fysisk GNOME 50.2 preflight – **PASS**, 22. november 2026

Brugeren kørte den SHA-256-pinnede, skrivebeskyttede GNOME preflight på commit `8d1bf90aa30e67d8e1da2d8677dd4cb9e7b881f7`. Fysisk resultat: `PHYSICAL_PREFLIGHT=PASS`, `GRDCTL_CREDENTIAL_STATUS_QUERY=PASS`, `GRDCTL_RDP_STATUS_BLOCK_PRESENT=PASS`, `RDP_CREDENTIALS_EMPTY=PASS`/`EMPTY`. Alle otte baseline-GSettings, GNOME service inactive/disabled, ingen RDP TCP/UDP listeners, nul nft/guard/pilot rest, aktiv display-manager og verificeret 10-sekunders timer syntaks: PASS. `SSH_SERVER_RUNNING=False` og `FREERDP_CLIENT_INSTALLED=False`; dette er nu kendte mangler ved en autentificeret fysisk RDP-klienttest, ikke problemer med GNOME RDP.

**Beslutning:** Gå videre med en **localhost-baseret test på den samme Viborg1-testklient** med Ubuntu 26.04 officielle pakker `freerdp-x11`, `xvfb`, `xauth` (ingen SSH-server, ingen ny Render/Neon-infrastruktur, ingen åbne RDP-porte). Før installation undersøges pakke-kandidater og afhængigheder **skrivebeskyttet** med `scripts/clientflow_63d30_local_client_package_preflight.py` / `apt-get -s` (og kontrollerer ingen `Remv`, ledig disk og fortsat RDP-inaktivitet). Foretag ingen pakke-installation, hvis simulationen viser package-removals eller uventet opgradering af systemkritiske pakker.

Når pakken er efterset/installationen særskilt godkendt, kan ny `auth-probe` bruge FreeRDP `+auth-only`, `/args-from:stdin` (password kun på lukket standard input) og `/cert:fingerprint:sha256:<one-time-cert-hash>`, alene på `127.0.0.1:3389` under Xvfb. `exercise-auth` er en samlet root-staged start/auth/rollback-drill og har `finally` cleanup, så scriptets normale afslutning stopper GNOME **før** firewallregler fjernes. Begge må under ingen omstændigheder aktiveres uden korrekt boot-/watchdog-/negative network isolation fysisk verificeret i samme acceptance window. Ingen credential udsendes til terminalen.

**Afgrænsning:** Auth-only viser alene TLS/NLA/credentials, ikke en ægte remote skærm, tydelig tekst, input-to-frame, mus eller browser HTTPS/443. Det er næste acceptgate; ingen produktionsklarhed kan udledes af en grøn auth-only prøve.

Kilder:
- https://packages.ubuntu.com/resolute/freerdp-x11
- https://packages.ubuntu.com/resolute/xvfb
- https://manpages.ubuntu.com/manpages/resolute/man1/xfreerdp3.1.html (`+auth-only`, `/args-from:stdin`, `/cert:fingerprint`)
