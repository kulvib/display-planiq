# Upload: PlanIQ Display · Fase 63C · 18. november 2026

**Branch:** `feature/display-63c-remote-livestream-stability-20261118`.
**Basis:** `display-planiq-main(20261118-093113).zip` (fresh `main`).

Upload filerne fra ZIP **med samme relative stier** til en ny branch oprettet fra den tilsvarende `main`.
ZIP er et overlay af ændrede/nye filer, **ikke** et komplet repository.
Der er ingen secrets eller databaseændringer. Bevar eksisterende miljøvariable og tjenester.

**Ændringer:** HTTPS-museinput coalescing, newest-only pending browser JPEG frames, lavere JPEG-kvalitet kun via HTTPS-fallback, non-passive wheel-handler og ny sendetids-telemetri på klienten. Bevarer Livestreams separat screen capture og bounded retries. Se `docs/PLANIQ_DISPLAY_63C_REMOTE_DESKTOP_LIVESTREAM_STABILITY_20261118.md`.

**Gate:** fuld GitHub CI + dependency audit + checksum source test skal være grøn. Merge ikke på grundlag af de lokale tests alene.

**Efter merge:** Render-deploy og backend/frontend-smoke. ClientFlow-runtimeændringer virker først efter **en separat godkendt ClientFlow-release og installation på Viborg1**. Udrul ikke til andre klienter uden pilot.

**Viborg1-pilot:** Remote Desktop alene, Livestream alene og begge samtidigt; bekræft mus/keyboard, klik, drag, scroll, frisk billede, billedgeometri, stabil capture samt stop/start og netværksgenopretning. Sammenlign `media-telemetry.json` med tidligere input-to-frame avg. 985,642 ms. Nye nøgler `relay_send_ms_last`, `relay_send_ms_avg`, `relay_send_ms_max` er **ikke** browserens paint-tid.

**Kendte udeståender:** Mutter/PipeWire zero-buffer fejlen er ikke løst eller reproduceret i tests på Ubuntu; fysisk simultantest er nødvendig. WebSocket-opgradering på netværket er ikke ændret. Intet krav om ekstra Render-kapacitet eller betalte tjenester.
