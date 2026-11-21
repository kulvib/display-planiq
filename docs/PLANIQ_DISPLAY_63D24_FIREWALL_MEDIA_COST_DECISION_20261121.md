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
