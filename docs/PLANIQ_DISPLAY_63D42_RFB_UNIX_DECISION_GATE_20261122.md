# PlanIQ Display · Fase 63D-42 · Samlet kildegate og AF_UNIX-sikkerhedstest

Dato 22. november 2026. Baseline: fuld CI og PostgreSQL-smoke grøn på
9e5ca449026f94cdd4854997be02822a7ff33639. PR #407 forbliver draft.
Viborg1 er testklient ID 3, Ubuntu 26.04, release 1248.

## Problem og mål

GNOME Wayland Desktop Sharing -> FreeRDP/Xvfb er fysisk accepteret
i 63D-32. PlanIQ Display skal senere vise skrivebordspixels inde i
eksisterende noVNC-browserkomponent over autentificeret WSS/HTTPS-fallback.

x11vnc's upstream -unixsock med -rfbport 0 advarer om et historisk
LibVNCServer TCP_NODELAY/setsockopt-problem: forkert fejlbehandling
kan lukke AF_UNIX-forbindelsen i rfbserver.c. At kommandolinjeflagene
findes, er ikke bevis for faktisk sikker drift.

Kilder:
- https://github.com/LibVNC/x11vnc/blob/master/doc/OPTIONS.md
- https://github.com/LibVNC/libvncserver/blob/master/src/libvncserver/rfbserver.c
- https://ubuntu.com/security/CVE-2026-32853
- https://ubuntu.com/security/CVE-2026-34352

## Den store samlede batch

1. Genbrug Ubuntu 26.04s udtrukne source pakker fra fase 63D-41
   uden nye downloads. Ingen installation eller RFB-binæreksekvering.
2. Lås SHA-256 for de fire centrale C-/dokumentationskilder til
   præcis kildemateriale verificeret af 63D-41.
3. Klassificér den præcise rfbserver.c klient-TCP_NODELAY-fejlgren.
   En ikke-fatal fejlgren, der alene logger, er kilde-evidens,
   ikke bevis for vellykket runtime. Return/goto/close/abort eller
   ukendte variationer afvises; andre source branches er uafklarede.
4. Udfør en rigtig, **ufarlig Python AF_UNIX-test** i engangs CI
   runner: privat 0700 katalog, 0600 Unix socket, SO_PEERCRED,
   bounded syntetisk payload/ACK og sikker oprydning. Testen
   starter ikke VNC eller åbner TCP/UDP.
5. Integrér negative tests mod kildebytte, malformed/fatal branch,
   ukendt peer-UID, overskredne permission bits, symlink,
   forkert host/CI og at grøn evidens ikke kan aktivere RFB.
6. Bevar fuld Python-/frontend-/PostgreSQL-/Ubuntu- og
   5/10/15-klientbelastningsgate samt uændret SHA256-manifeststyrke.

## Arkitekturvalg og go/no-go

x11vnc med den præcise Ubuntu LibVNCServer kan kun fortsætte som
kandidat efter reel CVE-/ABI-godkendelse og efterfølgende runtime-
isolationsbevis. En kildegren, der alene logger TCP_NODELAY-fejl,
er nyttig dokumentation, men hverken CVE-accept eller
RFB-handshake-test.

TigerVNC 1.15.0 fra Ubuntu kan ikke blot bruges som erstatning:
CVE-2026-34352 er uafklaret (Need evaluation). En godkendt
isolationspatch/alternativ RFB-producent eller browser-native
RDP/WASM vurderes, hvis x11vnc ikke er egnet. IronRDP kræver
rigtig binær WebSocket-håndtering; eksisterende JSON HTTPS-fallback
er ikke automatisk interoperabel.

Permanent sikkerhedslås: native_rfb_local_gate.PRODUCER_APPROVED=False,
native_rdp_pilot.PILOT_ENABLED=False og browser-native-RFB flag=false.

Et grønt 63D-42-resultat betyder kun statisk feasibility +
rigtig **syntetisk** AF_UNIX transportkontrol. Følgende er stadig
false: producer_approved, activation_permitted,
real_unix_rfb_handshake_proven, producer_tcp_udp_absence_proven,
physical_client_modified.

## Næste større implementering, først efter godkendelse

Samlet netværksisoleret test af faktisk sikker RFB-producent, nul
IPv4/IPv6/UDP listeners, derefter on-demand root-supervisor med
max 360 sek lease, private sockets og reboot/logout watchdog.
Derpå agent+browser WSS/HTTPS fallback samt Viborg1-fysisk accept
af pixels, mus/tastatur, key-up, input→pixel p50/p95, rollback og
livestream HLS mindst 90 sekunder. Ingen idle-proces pr. klient,
ingen dobbelt capture, ekstra serverbetaling eller Neon.

63D-42 rører ikke main, Viborg1, ClientFlow-release, Render Docker,
integreret PostgreSQL eller produktionsnetværk. PR'en forbliver draft.
