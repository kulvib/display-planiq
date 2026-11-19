# PlanIQ Display · Fase 63D-10 · 1.3.46/1247 source-kandidat

**Status: UNSIGNED BUILD CANDIDATE, IKKE EN GODKENDT RELEASE.**

## Grundlag
- Kilde: frisk `display-planiq-main(20261119-182025).zip` efter Fase 63D-9R.
- Viborg1 baseline ved måling: 1.3.45/1246. JPEG-capture ca. 23 ms, relay-send i størrelsesorden 1–3 s, input-to-frame op til ca. 3,1 s. Det er klient-tider, ikke bevis for browser-ende-til-ende.
- Livestream: uploader aktiv (`state=uploading`), ingen verificeret ende-til-ende-afspilningsforsinkelse.

## Denne source-stage
1. `client/VERSION` = `1.3.46`; `client/release/release-input.json` = 1247 med uændret Ubuntu 26.04 amd64 / runtime Python 3.13.14.
2. Read-only source-/build-gaten kræver *præcis* dette version/sekvens-par. Andre eller ældre identiteter kan ikke bruges til et nyt build via den gate.
3. Historiske preflight-test og kildetests accepterer kun det eksplicitte successor-par; gamle godkendte 1245/1246-kontrakter og hash-låse er uændrede.
4. SHA256SUMS.txt validerer opdaterede kildefiler; ingen ændring af hardening-, auth-, DB-, Render- eller policy-settings.

## Uændrede begrænsninger
- Aktivt katalog forbliver `catalog_sequence=1246` med 1245 stabil og 1246 update-only; 1247 er *ikke* indsat i kataloget.
- Ingen ny `clientflow_pilot_1247_approval.json`, ingen publiceret TAR, ingen ny deploy-API eller operator-gate; ingen client skal kunne autoopdateres til 1247.
- 1246 på Viborg1 fortsætter uændret, indtil unsigned 1247-kandidat er bygget reproducerbart, separat godkendt og autoriseret til én fysisk pilot.
- Eksisterende tre-release retention og alle rollback/fresh-install-begrænsninger bibeholdes.

## Næste gates (må ikke springes over)
1. Upload samlet source-branch fra præcis den friske main. Grøn GitHub CI inkl. Ubuntu 26.04 host-proof, kilde-SHA- og sikkerhedstests.
2. Kør separat `release-build.yml` for **eksakt SHA** og låst runtime-input-transport. Reproducerbart build a/b, fuld `REPRODUCIBILITY.json`, signatur-/kandidatkontrol. At et build lykkes godkender ikke en release.
3. Lav særskilt non-destructive, én-klient 1247 autorisations-/katalogfase, når den reelle TAR-hash og signatur er kendt. Må ikke forfalskes eller genbruge 1246-godkendelsen.
4. Fysisk Viborg1-pilot efter eksplicit godkendelse. Test klik/up/drag/key, WebSocket og kontrolleret HTTPS-fallback samt E2E-RTT/billedalder med stabil backend. Ved fejl: STOP, behold 1246.
5. Efter pilot: evaluér faktisk museforsinkelse samt HLS-segmenternes alder og synlig stream-latency. Ingen bred udrulning uden ny beslutning.
