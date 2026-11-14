# PlanIQ Display – samlet Mutter/PipeWire-startupdiagnostik og sikker backoff

**Status:** Kildekandidat, endnu ikke godkendt ClientFlow-release. Baseret på brugerens helt friske `display-planiq-main(20261114-163225).zip`. Installeret Viborg1 er stadig ClientFlow 1.3.43, sequence 1244. Intet i denne kandidat må installeres ved at overskrive den tidligere godkendte releaseidentitet.

## Faktiske fund, 14. november 2026

- Viborg1 var online via WiFi. Alle fire Livestream systemd-tjenester var aktive.
- Den grafiske GNOME-brugersession, PipeWire og WirePlumber var aktive. Kerneludskriften viste ingen klar GPU-fejl.
- Ni opstartsforsøg i tidsrummet 17.39–17.43 fik en Mutter/PipeWire-node, men `source_buffers=0`, `encoded_buffers=0`, `muxed_buffers=0` og intet første HLS-segment efter op til 25 sekunder.
- Der er **ikke** dokumentation for, at node-ID 63 repræsenterer den samme fejlende session; PipeWire kan genbruge node-ID'er.
- Den præcise årsag til manglende buffers er ikke bevist. HTTP 502 fra Render var en tidsmæssigt nærliggende, separat transporthændelse, ikke bevis for årsagssammenhæng.
- Den eksisterende 90-sekunders HLS-watchdog arbejder **efter** første segment og kan ikke i sig selv afhjælpe nul-buffer-opstartsfejlen.

## Samlet ændring

1. **Kilde- og forhandlingsdiagnostik:** Capture-helperen logger hver 10. sekund under opstart uden HLS-output, hvor i pipeline fremdrift sidder fast: `pipewire_no_buffers`, `encoder_no_buffers`, `mux_no_buffers` eller `hls_sink_no_segments`. Output er begrænset til GStreamer-state, boolean for forhandlede source caps og den eksisterende progress-tælling. Ingen pixeldumps, framebilleder, medieindhold eller adgangsoplysninger.
2. **Ærlig nodebesked:** `clientflow_wayland_capture_ready` bevares af hensyn til eksisterende driftslogs, men indeholder `phase=node_only`, så den ikke forveksles med faktisk video eller et produceret segment.
3. **Kontrolleret retry-backoff:** Mislykket capture-start eller en unormalt afsluttet child får stigende intervaller (5, 10, 20, 40, 80 og maksimum 120 sekunder). Supervisoren kontrollerer ønsket tilstand hvert sekund, også mens den venter; stop eller ny generation ophæver gammel backoff. Efter mindst 180 sekunders stabil capture nulstilles fejltælleren. Flere efterfølgende fejl kan fortsat automatisk genoprettes, men med højst ét nyt forsøg hvert andet minut, når maksimum er nået.
4. **Ingen skjult succes:** Producer-status `retrying` indeholder `attempt`, `reason`, `retry_after_seconds`, `next_retry_at`. Startkommandoens agent behandler `retrying` som en retrybar tilstand, ikke som en bekræftet start. Normalt `running` kræver fortsat første HLS-segment.
5. **Ekstra diagnosticeringsværktøj:** Admin-terminal har nu 21 hjælpescripts. `Livestream / PipeWire årsagsdiagnose` er skrivebeskyttet og viser status samt filtrerede 90-minutters hændelser. Rå exception-traces og signerede URLs vises ikke; menuen har dansk formål, anvendelsestidspunkt, resultatvejledning og sikkerhedsadvarsel.
6. **Regression:** Unit-tests med stubbet Mutter/GStreamer dækker retryintervaller, stop, nyt generations-id, kortvarigt succesfuld capture og nul-buffer-milestone. De eksisterende standardtests for HLS, videoformat, Remote Desktop og terminal bevares.

## Bevidst uændret

- PipeWire source-indstillinger, Mutter DBus-kald, HLS-parametre, bitrate, codecs, fps, native videogeometri og opstartsdeadline på 25 sekunder.
- Ingen automatiske genstarter af GNOME Shell, brugerens grafiske session, PipeWire, WirePlumber, Chrome eller Ubuntu.
- Authentication, MFA, admin-gate, credential adgang, rollback, backend og releasekatalog.
- Ingen ændringer på Viborg1 eller i produktion.

## Godkendelsesgate

**Før merge:** Alle CI jobs (Pytest, Ruff, sikkerhed, API kontrakt, frontend tests, ESLint, dependency-audit, build) skal bestå. SHA256SUMS skal svare til de faktiske filer. Den nye diagnosetekst skal revideres for credential-læk og statusfelt-kompatibilitet.

**Før klientinstallation:** Der kræves ny særskilt build-identitet, eksempelvis 1.3.44/1245; officiel reproducerbar keyless release-build, godkendelse og kompatibilitetskontrol for in-place opdatering. Den allerede godkendte 1244 skal forblive intakt. Den fysiske pilot skal afprøve normal capture, nul-buffer recovery med gradvist backoff, stop under backoff, Remote Desktop alene og i kombination, WiFi-udfald, kiosk-cookie-refresh, og om `source_caps` eller pipeline-state afslører rodårsagen. Enheden må ikke genstartes blot for at få et grønt resultat.

**Åben risiko:** Manglende source buffers kan også skyldes Mutter/PipeWire upstream. Instrumentering og backoff reducerer retry-stormen og gør fejlen nemmere at forstå; de dokumenterer ikke, at den underliggende grafikfejl er løst.
