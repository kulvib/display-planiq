# PlanIQ Display · 63D-40 · Offline ELF/ABI evidence gate

Dato: 22. november 2026. Fase 63D-39 er verificeret grøn på præcis
commit d9ba0c6a2bc8b5c84a4134348ec7562a0509d393:
- CI: https://github.com/kulvib/display-planiq/actions/runs/45060534169
- Single-node PostgreSQL smoke:
  https://github.com/kulvib/display-planiq/actions/runs/45060534125

Ingen merge, deployment, ClientFlow-release, root-runtime, firewall,
GNOME, livestream eller produktionsdatabase ændres.
Viborg1 forbliver på ClientFlow 1248.

## Sikkerhedsblokeringer

63D-39 downloadede de faktiske Ubuntu 26.04 RFB-arkiver. Begge
LibVNCServer-biblioteker matcher USN-8494-1, men det godkender
ikke RFB-producenten.

Ubuntu 26.04 markerer x11vnc/CVE-2026-32853 som Needs evaluation,
mens separat libvncserver er Not affected. CVE'en vedrører
LibVNCServer UltraZip-dekoder og må ikke forveksles med
TigerVNC CVE-2026-34352 vedrørende lokale SHM-tilladelser.
TigerVNC 26.04 er også Needs evaluation, og den distro-pakkede
1.15.0 ligger under upstream rettelse 1.16.2.

- https://ubuntu.com/security/CVE-2026-32853
- https://ubuntu.com/security/CVE-2026-34352
- https://ubuntu.com/security/notices/USN-8494-1

x11vnc upstream beskriver -unixsock sammen med -rfbport 0, men
advarer samtidig om en LibVNCServer rfbserver.c ændring efter
setsockopt. Et flag er derfor ikke bevis for stabil socket-only
drift med Ubuntu-binæren:
https://github.com/LibVNC/x11vnc/blob/master/doc/OPTIONS.md

## 63D-40: Kilde-/CI-leverance, aldrig aktivering

- scripts/clientflow_63d40_rfb_offline_elf.py genbruger de fire
  downloadede .deb-filer på engangs GitHub Ubuntu 26.04 CI-runner.
- Kontrollen fastlåser de præcise fire SHA-256 og versioner fra
  run 45060143659 og kræver en positiv 63D-39 provenance audit.
- Udpakning sker alene med dpkg-deb -x til en privat, midlertidig
  CI-mappe; readelf inspicerer ELF64, x86_64, NX-stack og NEEDED SONAME
  uden at starte eller installere nogen RFB-eksekverbar.
- Kodefilen har en streng kommandotilladelsesliste, ingen shell,
  ingen netværkslytter, ingen root-processer og ingen fysisk klient.
- Negative tests dækker ændret SHA/version, uventet godkendelse,
  manglende/dublerede/symlinkede arkiver, forkert ELF, eksekverbar
  stack og forsøg på at kalde andre systemkommandoer.
- Den eksisterende 63D-39 CI-job udvides, så samme arkiver
  genbruges uden gentagne downloads.

Et grønt resultat er kun bevis for statisk binærevidens.
Koden rapporterer stadig producer_approved=false,
activation_permitted=false, x11vnc_unix_socket_abi_proven=false,
no_tcp_listener_proven=false og physical_host_changed=false.

## STOP og næste godkendelser

1. Uafhængig gennemgang af præcis Ubuntu x11vnc+LibVNCServer ABI,
   binærens reelle Unix-only egenskaber og alle relevante CVE'er.
   Hvis sikkerhed ikke kan dokumenteres, vælges en anden producent,
   ikke en standardinstallation med ukendt risiko.
2. Kun efter bestået sikkerhedsaudit: fysisk isoleret, tidsbegrænset
   sandbox-test på engangsrunner med absolut ingen offentlig VNC
   listener og sikker AF_UNIX kontrol. Ingen installeret RFB på Viborg1.
3. Kildefastlåst, root-superviseret, on-demand Xvfb/FreeRDP/RFB,
   max 360s lease, 0700/0600 Unix-socket, watchdog, rollback,
   ingen langlivet credential og ingen idle process.
4. Derefter den nu kilde-deaktiverede native agent/HTTPS/WSS/noVNC
   direkte inde i PlanIQ Display, testet på Viborg1 med p50/p95,
   mouse/key-up, WSS blokeret → HTTPS, rollback, HLS mindst 90 sek.
5. Bevar Render Docker med integreret PostgreSQL, uden Neon eller
   ekstra betalte servere.

Den allerede fysisk godkendte 63D-32 GNOME/FreeRDP-test
(5/5 klik, p50 ~120,7 ms lokalt) skal ikke gentages alene på grund
af flyttede kildefiler. Den beviser ikke browser-Remote Desktop.
