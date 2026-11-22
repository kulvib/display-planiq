# PlanIQ Display – Fase 63D-33: Render/Docker transportmålinger og HLS

## Infrastruktur – fast forudsætning

**PlanIQ Display kører på Render med Docker – ikke på Neon.** Dette projekt skal
ikke have Neon-projekt, Neon-databasetransaktioner eller Neon-forbrugsmålinger som
del af fase 63D-33. Den eksisterende Render/Docker-installation, dens lokalt
drevne PostgreSQL-service og nuværende godkendelses- og sessionskontrol forbliver
uændrede. Der indføres ingen nye cloud-tjenester, baggrundspolling, databasenavne,
portåbninger eller fakturerede dependencies.

Dette gælder **Display**; det ændrer ikke databasevalget i andre PlanIQ-produkter.

## Fysisk reference (Viborg1, 22.11.2026)

Fase 63D-32 dokumenterede for 5 lokale RDP/GTK-farveskift: p50 120,7 ms,
maks. 123,7 ms til observeret FreeRDP X11-buffer; GTK click ACK p50 1,4 ms.
Dette er en direkte lokal GNOME RDP-forbindelse til 127.0.0.1, **ikke** browser,
Render, HTTPS/443 eller HLS. Den fysiske test blev ryddet helt op. Draft PR #404
og release 1248 forbliver uændrede.

## Faktiske aktuelle Display-transportveje

- Remote Desktop: browser -> WSS eller HTTPS long-poll fallback -> Render/Docker
  Remote Desktop-broker -> klientens netværksagent -> jpeg_rpc capture/input ->
  svar via samme broker -> browserens JPEG-billedelement.
- Livestream: klientcapture -> 2s segmenter/HLS-m3u8 -> klientuploader ->
  Render/Docker medielager -> browserens HLS-afspiller.
- Den godkendte GNOME RDP-loopbackpilot erstatter **ikke** disse veje.
  3389 må ikke åbnes til internettet, og sikkerhedsgates/rollback må ikke fjernes.

## Indhold i denne sikre 63D-33-batch

1. Browseren måler (performance.now) modtagelse af JPEG, RAF-tildeling og
   img.load; en bounded ring med 32 poster viser p50/p95 og hvor mange
   uviste billeder der blev erstattet. De indsamlede tal er **browserinterne**,
   ikke ægte museklik til pixels, ikke netværkslatens før browseren.
2. HTTPS-inputfallback har fortsat FIFO af alle knapper, tastetryk, releases,
   filer og kommandoer. Kun tilstødende, endnu ikke sendte mouse-move-pakker i
   samme dragtilstand samles. Nye caps: 128 ventende pakker og 512 KiB af
   faktisk UTF-8-JSON. Overløb lukker kontrollen fail-closed (ingen skjult
   bortkastning af museknap- eller key-up), med lokale send-/poll-målinger.
3. Livestreams felt "Uploadalder" var fejlagtigt knyttet til \`hls.latency\`;
   det omdøbes til **HLS livekant**. 32 begrænsede hls.js-målinger viser
   browserens p50/p95, men **ikke** uploadalder eller capture-to-screen.
4. Ingen billeder, indtastninger, credentials, live-URLs eller manifestindhold
   logges, persists eller overføres som måledata. Ingen ændrede backend-API'er,
   netværksprotokoller, HLS-segmentlængder eller ekstra REST/DB-requests.

## Accept og begrænsninger

Først GitHub CI, frontend regressionstests og Render single-node PostgreSQL
smoke på den eksakte kandidat-commit. Herefter separat kontrolleret frontend-
og klientaccept (WSS og HTTPS-fallback; inputorder og medierespons; HLS
segmentproduktion/uploader/manifest/browser). Testresultater fra Viborg1
skal sammenlignes med 63D-32s **lokale** resultater med tydelig metodeadskillelse.

Denne batch er en **måle- og tilbagepresningsforbedring**, ikke en gennemført
udskiftning til GNOME RDP som browsertransport og ikke en løsning af
15-sekunders livestreamforsinkelse. Først målbar faktisk browser/Render/klient
flaskehals afgør ændringer i media codec, WebRTC, upload, caching eller HLS.
Det beskytter de eksisterende sikkerhedsgates og omkostningsrammer.
