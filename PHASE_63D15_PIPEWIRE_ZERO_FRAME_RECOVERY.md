# PlanIQ Display · Fase 63D-15 · afgrænset Mutter/PipeWire zero-frame recovery

**Status: SOURCE-ONLY KODEKANDIDAT. Ingen fysisk klientrettelse er verificeret, ingen signeret release er ændret, og ingen updater er genaktiveret.**

## Kildegrundlag og observerede forhold

- Frisk repository-kilde: `display-planiq-main(20261120-163053).zip`, modtaget 20. november 2026, ikke en ældre ZIP.
- Viborg1, klient-ID 3, fysisk test (ikke produktion): aktiv immutable release `clientflow-1.3.46-seq-1247`.
- Den eksisterende release-controller blev sikkerhedsgodkendt til manuel 1247-aktivering med den separate engangsrecovery. Midlertidigt override er fjernet. `clientflow-updater.timer` er og skal forblive `disabled/inactive`, indtil en senere signeret release med 63D-13 er autoriseret og installeret.
- Livestream: backend-agent modtog startkommando, men `producer_start_failed`, `pipeline_state=paused`, `source_caps=yes`, `source_buffers=0`, `encoded_buffers=0`, `muxed_buffers=0` i gentagne 25-sekunders forsøg.
- Remote Desktop: `Mutter/PipeWire capture kunne ikke genetableres: GStreamer returnerede ingen frame`; ældre telemetri var forældet og kan ikke bruges som verificeret nuværende RTT.
- GNOME Shell 50.1/Wayland, PipeWire 1.6.2, GStreamer 1.28.2. `pw-dump` bekræftede aktive forbindelser (`gnome-shell` 63 -> `python3.14` 66, også 70 -> 73 ved overlappende optagelse), men ingen source-buffere i ClientFlow. `pw-top` angav `BGRA 2560x1080`; nul RATE/QUANT er **ikke** dokumentation alene for en defekt scheduler.
- Primær årsag til, at upstream/pipewiresrc leverer ingen frames, er **endnu ikke verificeret**. Ingen systempakkeopgradering, DMA-BUF-antagelse, nyt skærmcapture-backend eller root/sikkerhedsundtagelse indføres på dette grundlag.

## Samlet kodeændring

1. **Livestream source:** Bevar den eksisterende native-geometry HLS/encoder/transport fuldstændigt på normalt førsteforsøg. Tilføj begrænset alternativ PipeWire-kildetilstand `bounded` med `min-buffers=2 max-buffers=4 use-bufferpool=false`. Denne tilstand er en testbar kompatibilitetshypotese, **ikke** en verificeret løsning på maskinen. Intet permanent krav om ekstra kopiering eller nye env-variabler på den normale vej.
2. **Livestream producer og backend-ack:** Første opstart forsøger normal kilde i højst 12 s. **Kun hvis HLS-klargøring udløber**, stoppes tidligere capture-child og der forsøges én bounded mode i højst 14 s i samme generation/kommando. Backendagentens afventning øges fra 30 til 45 s, mens eksisterende 60 s lease keeper forbliver. Først når et reelt HLS-segment og manifest findes, kaldes generation `started`. Ved andre fejl afvises fallback; efter mislykket samlet forsøg anvendes eksisterende exponential backoff med bounded mode. Operatorstop og generationsskift nulstiller mode. Ingen automatisk ACK af `starting`/`retrying`.
3. **Remote Desktop:** Første `GStreamer returnerede ingen frame` giver højst ét nyt capture-forsøg med bounded PipeWire bufferindstillinger. Andre RuntimeErrors bevarer eksisterende clean restart uden at ændre kilde-mode. Den succesfulde mode bevares for en session og nulstilles ved `stop_capture`/sessionoprydning. Ingen ændring af root inputbroker, autentificering, HTTPS/WebSocket fallback, skærmgeometri eller JPEG-indhold.
4. **Status og diagnostik:** Livestream producer angiver `source_mode` og `next_source_mode`, og logfører sikkert fallback-hændelsesnavn. Der logges ingen pixels, screenshots, tokens, e-mails, rå D-Bus-objekter eller signed URLs. Ingen nye DB-kald, tabeller, Render-variabler eller hardwareinvesteringer.
5. **Eksisterende 63D-13:** Den permanente transaktions-/coordinator-rettelse er **allerede** i modtaget `main`; tests kontrollerer fortsat denne. Samme rettelse skal være inkluderet i en ny signeret release, **ikke** i en muteret 1247-TAR.

## Test og sikkerhed

- Nye deterministiske tests i `scripts/tests/test_phase63d15_pipewire_recovery.py`: normal/alternativ pipeline, HLS-native aspect ratio, begrænset retry, backend command-timing, stop uden uendelig løkke, remote normal/scaled/native, rollback til normal ved ny session, eksisterende koordinatorfix.
- Eksisterende zero-frame-, HLS-progress-, remote capture-, transport-, relay-, 63D-13- og 63D-14-kontroller skal fortsat være grønne.
- Ubuntu 26.04 på fysisk Viborg1, GPU/DMABUF, sensor-synlig frame og E2E-latency kan **ikke** bevises med de lokale unit tests og er derfor udtrykkelige pilotgates.
- Ingen nuværende 1244/1245/1246/1247 signeret release, deployment-approval, katalog, release-store eller updater-timer ændres ved denne source-stage.

## Pilotaccept for en fremtidig ny release

1. Efter CI og review: opret **ny release-identitet**, foreslået `1.3.47/1248`, via separat source-freeze, SHA-256 manifest, signerede og reproducerbare builds; **genbyg ikke 1247**. Hold godkendelse, publicering og katalogpromovering adskilt.
2. Kontrollér at permanent coordinator 63D-13 er i den byggede runtime. Ingen åbning af automatisk updater på Viborg1 før kontrolleret signeret installation og ny godkendt opdateringssti.
3. Én fysisk Viborg1-pilot (ID 3), eksplicit autoriseret, ikke fleet. Test: kiosk-browser, admin-terminal, GNOME `seat0`, Livestream startet med reelle `source_buffers > 0`, nye HLS-segmenter, korrekt endelig started-ACK, faktisk video i browser, også ved genstart/stop/start og uden capture-leak.
4. Remote Desktop: kontrolsession etableres, første og senere JPEG-frames er **friske**, mouse down/up/move, drag, keyboard og input-til-synlig-frame måles. WebSocket og kontrolleret HTTPS fallback må ikke fejlklassificeres som capturefejl. Registrér median/p95 og total E2E-latency, ikke kun relay send.
5. Ved fortsatt `source_buffers=0`, HLS-timeout eller `GStreamer returnerede ingen frame`: **STOP** pilot, bevar fysisk fungerende kiosk og adgang; indsamling af målrettet evidens. Ingen ekstra spontane genstarter, usignerede runtime-patches, ændring af PipeWire-systempakker eller auto-rollback.
6. Mål Render/netværks-/DB-kald før/efter for at verificere nul ekstra persistente DB-løkker og begrænset kø under begge aktive visningssessioner.

## Grænser

Denne fase garanterer **ikke**, at Ubuntu/GNOME 50 fremover producerer frames; den giver én sikker, kontrollerbar alternativ bufferforhandling og forbedrer sammenhængen mellem fysisk capture og backend-ACK. Næste beslutning er GitHub CI og derefter én fysisk pilot på en **ny** approved runtime, ikke direkte ændringer i allerede installeret 1247.
