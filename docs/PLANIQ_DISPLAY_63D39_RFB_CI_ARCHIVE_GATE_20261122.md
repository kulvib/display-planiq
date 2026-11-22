# PlanIQ Display · Fase 63D-39 · Isoleret Ubuntu RFB-pakkeaudit

Dato: 22. november 2026. Udelukkende kildekode og CI i den eksisterende
draft PR #407. Ingen merge, Render-deploy, installation eller serviceændringer
på Viborg1. ClientFlow forbliver på release 1248.

## Baseline fra 63D-38

Den SHA-256-fastlåste, skrivebeskyttede præflight blev gennemført på
Viborg1 med target_verified=true, policy_query_ok=true og uden installation.
De observerede Ubuntu 26.04-pakkekandidater var:

- x11vnc: 0.9.17-2
- libvncserver1 og libvncclient1: 0.9.15+dfsg-3ubuntu0.2
- tigervnc-scraping-server: 1.15.0+dfsg-2build1

Bibliotekerne opfylder minimumskravet i Ubuntu USN-8494-1. Det udgør
**ikke** godkendelse af x11vnc. Ubuntu 26.04 markerer fortsat
x11vnc/CVE-2026-32853 og TigerVNC/CVE-2026-34352 med
"Needs evaluation". LibVNCServers separate CVE-2026-32853-status
er "Not affected" på 26.04; de to kildepakkers status må ikke forveksles.

Kilder:
- https://ubuntu.com/security/CVE-2026-32853
- https://ubuntu.com/security/CVE-2026-34352
- https://ubuntu.com/security/notices/USN-8494-1

## Implementeret i 63D-39

Ny GitHub Actions-job på disposable Ubuntu 26.04 runner:

1. Opdaterer udelukkende runnerens APT-indeks og **downloader** præcis
   fire RFB-pakkearkiver via de officielle konfigurerede APT-kilder.
2. Installerer eller eksekverer ingen af dem. Ingen RFB-port, VNC-proces,
   GNOME RDP-service, firewall- eller Render-ændring.
3. Efterprøver arkivernes faktiske Package, Version, Architecture,
   SHA-256 og størrelse, samt USN-8494-1-minimum via dpkg-sammenligning.
4. Afviser forkerte, manglende, dublerede, symlinkede og ugyldige arkiver.
5. Enheds-/negative tests validerer disse afvisninger og CI-hostgrænsen.

En grøn audit betyder alene, at **pakkeinventaret** kunne efterprøves.
Output vil fortsat være producer_approved=false,
activation_permitted=false og browser_rdp_proven=false. Kan ikke ændres
ved en Render environment variable eller et valgfrit scriptargument.

## Stop før næste fase

- Kræv separat, dokumenteret vurdering af den **præcise** Ubuntu x11vnc
  build med CVE-backports og af dens koblede LibVNCServer ABI. Et
  upstream versionsnummer eller et CLI option-flag er utilstrækkeligt.
- Undersøg den reelle Unix-socket-only drift på isoleret,
  netværksafskåret CI før en fysisk klientinstallering.
- Byg derefter en kildefastlåst, root-overvåget 360-sekunders
  Xvfb/FreeRDP/RFB supervisor med private 0700/0600 Unix sockets,
  genstarts-/logout-oprydning, ingen TCP/5900 og fail-closed sikkerhed.
- Tilslut kun den eksisterende agent/HTTPS/WSS browsertransport efter
  særskilt godkendelse og derefter fysisk måling af pixels, mus/tastatur,
  browserinput p50/p95, WSS fallback, rollback og HLS >=90 sekunder.

Allerede godkendt lokal GNOME/FreeRDP 63D-32 skal ikke gentestes alene
fordi kildekoden er flyttet. Den er ikke en browser-integrationstest.
Eksisterende Render Docker med indbygget PostgreSQL bevares. Ingen Neon,
ekstra betalte tjenester eller proces pr. inaktiv klient.
