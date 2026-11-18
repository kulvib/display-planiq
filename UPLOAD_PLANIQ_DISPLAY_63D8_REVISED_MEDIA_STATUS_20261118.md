# PlanIQ Display – Fase 63D-8 (revideret): Remote Desktop-hotpath og deploymentstatus

**Kilde:** `display-planiq-main(20261118-205649).zip`, `main` SHA `8fac706f41b487413c15b37dde222f465630b470`.
**Tidligere pakke:** `PlanIQ_Display_Fase63D8_Deployment_Status_Media_Balance_Final_20261118.zip` er **forkastet**; må ikke uploades sammen med denne branch.

## Formål

Denne fase samler dokumenterede optimeringer i den eksisterende Remote Desktop-/Livestream-belastningskæde med en brugbar oversigt over faktiske ClientFlow-deployments. Den hævder **ikke**, at den dominerende fysiske forsinkelse på Viborg1 er bevist eller elimineret.

### Backend: Remote Desktop-billeder

- Et skærmbillede med gyldig `screen_width/screen_height` bruger klientens native geometri **uden SQLModel-opslag**. Manglende geometri udløser højst én fallback-læsning pr. browsersession; `stream_stopped` udløser ingen opløsningslæsning.
- Browseroverførslen har højst **ét ventende JPEG-frame** pr. session; et nyt frame erstatter det gamle, hvis websocket-send er optaget. Ét allerede afsendt frame kan ikke annulleres sikkert. Input-, fil-, fejl- og livscyklusmeddelelser kasseres **aldrig** af denne mediepolicy.
- Alle browserbeskeder bruger samme per-session sendelås, så billed- og kontrolsend ikke overlapper på WebSocket. Sessionslukning afbryder senderen og rydder ventende frame.
- Kiosk-clientens uændrede `1.3.45/1246` sender fortsat JPEG-frames via den eksisterende kanal. Ingen ny klientpakke, 1246-byteændring eller migrationskode indgår.

### Frontend: Remote Desktop

- JPEG-frame bliver ikke længere gemt som stor `frameSrc`-streng i React-state. En isoleret, testbar "newest-only"-painter opdaterer det eksisterende `<img>`-element højst én gang pr. animationsframe; alle ældre ventende frames erstattes.
- Native skærmgeometri og inputmapping bevares. UI-state for framealder opdateres højst én gang pr. sekund; geometri og streamstatus opdateres kun, når de ændres.
- WSS eller HTTPS-fallback vises ved afspilleren. HTTPS-fallback viser eksisterende sendeaktivitet og lokal **indholdsfri** statistik om inputkøen (ventende antal, sidste HTTP-send, sammenlagte musebevægelser). Intet skrives til Neon og ingen nye netværksrequests foretages for målingerne.
- Stale events fra tidligere sessioner bliver ignoreret ved reconnect. Museklik, release, drag og tastatur har samme semantik, og fallbackens FIFO-order er bevaret.
- **Ingen** manuel `Prioriter Livestream`-knap, kvalitets- eller FPS-ændring indgår i pakken.

### Opdateringsstatus

- `Administration → ClientFlow Releases`: seneste 20 faktiske deployments fra den eksisterende tabel, sammen med status, faktiske trin, tidspunkter, fejl og recovery. Læses kun ved første superadmin-sidevisning og eksisterende manuel opdatering. Inaktive planer holdes tydeligt adskilt.
- `Klient → Software`: en separat knap til at hente op til 10 rigtige deployments; ingen ekstra polling i klientens allerede optimerede hotpath.
- Ingen kunstig downloadprocent; status følger backends autoritative state machine.

## Hvad er **ikke** løst/bevist?

- 1246-klientens JPEG-upload og Livestream H.264/HLS deler stadig samme uplink og GNOME/Mutter/PipeWire-ressourcer. Backend kan nu undgå at sende forældede frames videre til browseren, men det reducerer **ikke nødvendigvis** den oprindelige klient-uplink.
- Input/RPC-forsinkelsen inde i 1246-klienten, ukendte WebSocket-fejl og de to Mutter-capture-sessioners konkurrence er ikke ændret. En eventuel ændring her kræver ny reproducerbart bygget, signeret ClientFlow-release (tidligst 1.3.46/1247), aldrig patch af 1246-artifactet.
- Automatisk rollback, fleet-udrulning, stabil promotion og nyinstallation åbnes ikke.

## Forventede acceptgates

1. GitHub CI inklusive PostgreSQL/SQLModel, frontend build, source freeze og dependency audit er fuldt grøn; Render frontend/backend kører samme commit.
2. På Viborg1: kontrollér WSS vs HTTPS-fallback, HTTPS-inputkø/latency under musetræk og klik, framealder, CPU/netværk, lokal `media-telemetry.json` og HLS-buffering; tag samme målinger før/efter hvis muligt.
3. Test mindst 10–15 minutter Livestream alene, 10–15 minutter Remote Desktop alene (mus, tastatur, drag, release) og 10–15 minutter begge samtidig under aktiv mus. Gentag Livestream på en **anden enhed** for at skelne browserressourcer fra uplink/capture.
4. Sørg for ingen nye skjulte status-/Neon-forespørgsler, unormal DB-aktivitet, eksponerede tokens, genstartsløkker, uventede capture- eller recoveryfejl.
5. **Hvis musen fortsat hænger eller Livestream buffer under belastning**, hold 1246 som pilot og fortsæt med målt, klientrettet 1247-transport-/capture-arbejde. Denne fase er ikke grundlag for automatisk stabil promotion.

## Render Environment

Ingen tilføjelser, ændringer eller sletninger. `CLIENTFLOW_RELEASE_ARTIFACT_DIR` og `CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1` bevares.
