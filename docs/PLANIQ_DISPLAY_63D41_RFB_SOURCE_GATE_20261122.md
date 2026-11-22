# PlanIQ Display · Fase 63D-41 · Ubuntu-kildekode og sikker AF_UNIX-feasibility

Dato: 22. november 2026. Kildebaseret gates i den eksisterende draft PR #407,
med Viborg1 (ID 3, Ubuntu 26.04) uændret på ClientFlow release 1248.

## Accepteret udgangspunkt

Fase 63D-40 er fuldt grøn på SHA
3288eb3dc5f752bb0ddf2207992be43b998744de:

- CI: https://github.com/kulvib/display-planiq/actions/runs/45061378490
- Display single-node PostgreSQL-smoke:
  https://github.com/kulvib/display-planiq/actions/runs/45061378521

Den CI-isolerede, SHA-256-fastlåste binæraudit identificerede ELF64 x86_64
x11vnc og faktisk NEEDED afhængighed til libvncserver.so.1 og
libvncclient.so.1, uden at installere eller eksekvere RFB-komponenter.
Dette beviser ikke privat AF_UNIX-funktion, fravær af TCP eller sikkerhed.

## Fase 63D-41: præcis Ubuntu-kildepakke før en RFB-proces

Der er fortsat en vigtig producentblokering:

- Ubuntu CVE-2026-32853 klassificerer x11vnc på 26.04 som
  "Needs evaluation"; den særskilte libvncserver-kildepakke som
  "Not affected". Dette er en UltraZip-klientdekoder-sag, ikke
  TigerVNC's framebuffer-SHM-fejl.
  https://ubuntu.com/security/CVE-2026-32853
- Ubuntu CVE-2026-34352 klassificerer TigerVNC på 26.04 som
  "Needs evaluation". Ubuntu's 1.15.0+dfsg-2build1 er ikke
  automatisk lig en distro-patchet upstream 1.16.2.
  https://ubuntu.com/security/CVE-2026-34352
- x11vnc upstreams dokumentation om -unixsock / -rfbport 0
  indeholder stadig et teknisk forbehold ved LibVNCServer
  rfbserver.c/TCP_NODELAY setsockopt:
  https://github.com/LibVNC/x11vnc/blob/master/doc/OPTIONS.md

Derfor er producenten fortsat **ikke godkendt**.

Nyt separat GitHub CI-job på disposable Ubuntu 26.04 henter
Ubuntu-arkivets GPG-verificerede APT deb-src metadata og downloader
kun disse eksakte kildeversioner:

- x11vnc 0.9.17-2
- libvncserver 0.9.15+dfsg-3ubuntu0.2

De originale Debian kildearkiver verificeres med dpkg-source og
udtrækkes kun i en privat mappe på runneren. Ingen compile, install,
execution, privileged VNC-proces, offentlig TCP-listener, SSH- eller
firewallændring, maskin/genstartsarbejde, Render/Neon-oprettelse.

Nyt Python source-gate verificerer:
- distributionens eksakte source/changelog-version,
- faste C-/dokumentationsfiler og deres SHA-256,
- de konkrete AF_UNIX og rfbNewClient referencer,
- LibVNCServers TCP_NODELAY setsockopt-kildesti og
  x11vnc's dokumenterede afhængighed/advarsel.

Negative tests kræver at ukendte kildefiler, symlinks, forkerte
versioner, fjernede advarsler og uautoriseret runner fejler lukket.

**Grøn source-audit er IKKE en runtime- eller CVE-accept**:
output sætter altid producer_approved=false,
activation_permitted=false, unix_socket_runtime_proven=false,
tcp_listener_absence_proven=false og physical_client_modified=false.

## Næste gate

Før en fysisk Viborg1-installation skal vi have en dokumenteret
binær-/kildeafklaring af Unix-socket-problemet og CVE-status.
Hvis det er uafklaret, testes x11vnc **ikke** som en ubevogtet
server. Næste valg er enten en kildefastlåst rettelse fra en
godkendt producent eller et andet isoleret RFB-/browseralternativ.

Efter sikkerhedsaccept kan vi lave en kortvarig, netværksisoleret
CI-test af en privat AF_UNIX socket med negative tests af
andre UID'er, fuld afbrydelse og ingen IPv4/IPv6/UDP port.
Derefter root-superviseret 360-sekunders on-demand runtime og
PlanIQ Display browser-WSS/HTTPS-fallback med målt input→pixel
p50/p95, key-up/mouse-up, rollback, HLS mindst 90 sekunder.

Følgende forbliver kildedeaktiveret:
- client/runtime/clientflow_runtime/native_rfb_local_gate.py:
  PRODUCER_APPROVED=False
- backend/service1/routers/native_rdp_pilot.py: PILOT_ENABLED=False
- frontend RemoteDesktop-kildeflag for native RFB: false

Ingen ændringer i eksisterende Render Docker med integreret
PostgreSQL. Ingen Neon, ekstra betalt server, offentlig VNC-/
RDP-port eller uafhængig administrator-RDP-applikation.
