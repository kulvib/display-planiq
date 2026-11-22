# PlanIQ Display · Fase 63D-43 · Samlet supervisor-kontrakt og RFB 3.8 syntetisk end-to-end

Dato 22. november 2026. Én sammenhængende kodebatch i den eksisterende
draft PR #407, oven på grøn 63D-42.

## Hvorfor denne store batch

PlanIQ Display skal styre Viborg1's GNOME Wayland-skrivebord direkte
i eksisterende web-frontend med lav latenstid, uden separat
administratorprogram eller ekstra Render-server. GNOME/FreeRDP/Xvfb
blev fysisk accepteret i 63D-32, men den ekstra RFB-producent
og den endelige browserpixelsti er endnu ikke godkendt.

Dette er én samlet kilde-/CI-batch med fire dele:

1. client/runtime/clientflow_runtime/native_rfb_supervisor_contract.py:
   fuldstændig inert, unit-testbar lease-/generationsmodel for en fremtidig
   root-supervisor: én klient/session/stream-generation, eksplicit owner UID,
   privat verificeret AF_UNIX socketgeneration, max 360 sekunder absolut
   lease, startup max 15 sekunder, revokerede sessions og ingen forlængelse.
   Modellen er IKKE en root-daemon, starter/stopper ingen processer og kan
   ikke love watchdog- eller reboot-oprydning. Fire kildegates skal være
   godkendt før modelarming: native_rfb_local_gate.PRODUCER_APPROVED,
   separat CVE_CLEARANCE_APPROVED, ROOT_CLEANUP_WATCHDOG_APPROVED og
   PHYSICAL_CLIENT_ACTIVATION_APPROVED. Alle er hardcoded False.
   Negative tests bruger udelukkende monkeypatch i testprocessen.

2. scripts/clientflow_63d43_synthetic_rfb38.py:
   En rigtig Python AF_UNIX testserver på engangs Ubuntu 26.04 CI.
   Syntetisk RFB 3.8 banner, dummy RFB security type None på en helt privat
   testfixture, rå 2x1 framebuffer pixels og 4 binære inputevents
   (tastatur ned/op og mus ned/op). Ingen mock-auth type None i drift.
   Den bruger ClientFlows eksisterende NativeRfbClientSession
   gennem den autoritative NativeRdpRelaySession backend-brokermodel.
   En syntetisk Python-browser udfører binær RFB-framing med ACK.
   Ingen x11vnc, TigerVNC, Xvfb, GNOME, TCP, WebSocket-netværkslytter
   eller ægte pixels fra Viborg1. Produktets source flags forbliver OFF.

3. Negative kontrakt- og regressionstests:
   manglende kilde/CVE/watchdog/physical approval, lease over 360s,
   manglende startup, forkert owner UID, klient/session/generation,
   erstatning af socketmetadata, replay, timeout og øjeblikkelig
   tilbagekaldelse. Synthetic RFB testes med wire-header, raw pixels,
   binære input down/up, forkert stream-ID, ugyldige payloads,
   ACK-framing, EOF og oprydning.

4. Eksisterende Ubuntu 26.04 CI-job udvides med syntetisk RFB-kontrol.
   Hele backend/frontend-suiten, PostgreSQL-smoke, de eksisterende
   5/10/15-client load gates og SHA256SUMS bevares.

## Sikkerhedsbeslutning — STOP

Dette er IKKE en accept af virkelig RFB-produktion.

- Ubuntu 26.04 x11vnc / CVE-2026-32853: Needs evaluation.
- Ubuntu 26.04 TigerVNC / CVE-2026-34352: Needs evaluation.
- LibVNCServers undersøgte TCP_NODELAY-fejlgren logger alene,
  men alle andre grene og faktisk Unix-only RFB runtime mangler bevis.
- Der mangler virkelig root-supervisor og systemd watchdog med oprydning
  ved process-crash, reboot og logout og dokumenteret nul TCP/UDP ports.
- Der mangler fysisk noVNC-in-browser pixel/input p50/p95 over
  autentificeret WSS og HTTPS fallback samt HLS mindst 90 sek.

Referencer:
- https://ubuntu.com/security/CVE-2026-32853
- https://ubuntu.com/security/CVE-2026-34352
- https://ubuntu.com/security/notices/USN-8494-1

Ingen CVE-clearing på dummy pixels, ingen runtime via miljøvariabel,
ingen NeoN, betalt hosting, separat RDP-program eller permanent service.

## Næste store implementeringspakke efter denne

A. Dokumenteret sikker RFB-producent, netværksisoleret runtime-proof,
   privat AF_UNIX og nul IPv4/IPv6/UDP, implementeret virkelig
   root-supervisor/cleanup, derefter browser/WSS+HTTPS og fysisk Viborg1.
B. Hvis producenten ikke kan sikkerhedsgodkendes, skift til en kilde-
   godkendt producent eller en browser-native RDP/WASM transport
   med faktisk interoperabel HTTPS fallback.

Fase 63D-43 ændrer ikke main, Render Docker med integreret PostgreSQL,
klientkonfiguration eller ClientFlow-release. Viborg1 er fortsat
ikke i produktion og forbliver på release 1248.
