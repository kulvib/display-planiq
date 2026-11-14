# PlanIQ Display – samlet source-candidate til audit og pilot

**Udgangspunkt:** frisk `display-planiq-main(20261111-180347).zip`, verificeret identisk med GitHub `main` på commit `df4e6a6cf1fdfe6bc31a3fd1830ca206b6d38919` ved start af arbejdet. **Dette er ikke en bygget eller godkendt ny ClientFlow-release.** Aktiv 1.3.43/1244 forbliver uændret. Ingen GitHub-merge, Render-deploy, installation eller signering er udført.

## Samlede ændringer – kildekode

1. **Cookie-dialog ved timerstyret Chrome-reload:** Genregistrerer CMP-only tidlig CSS gennem den langlivede Browser Guard CDP-forbindelse, så registreringen også er til stede ved ny navigering. Skriver ikke cookies, klikker ikke samtykke og ændrer ikke indhold uden for de kendte CMP-selektorer. Der kræves fysisk validering med den faktiske kiosk-URL og gentagne refresh-cyklusser.
2. **Diagnostik:** Opdeler systemd-status og Livestream-processtatus i hver sin advarsel uden at undertrykke reelle procesfejl.
3. **Remote Desktop:** Klassificerer tabte WebSocket-/transportforbindelser separat fra capture-fejl; kontrolleret oprydning selv ved lukket kontrolkanal.
4. **Supportkommandoer:** Opretholder 20 hjælpescripts og tilføjer den nye skrivebeskyttede WiFi-hændelses-/recoveryanalyse.
5. **Hjælp i den aktive terminalmenu:** Alle 20 hjælpescripts har dansk formål, konkret anvendelsessituation, forventet resultat samt sikkerhed og begrænsninger. Risiko er synlig allerede før åbning af vejledningen. Dialogen skelner mellem »Indsæt«, »Kør« og »Kopiér«.
6. **WiFi:** Opsætning af ny profil og aktiv netværkstest forbliver adskilt. Profilen har `autoconnect=no`; test kræver fysisk fallback, eksplicit `TEST` samt NetworkManager-checkpoint med 120 s timeout. Styring af permanent WiFi-prioritet er ikke implementeret eller skjult tilføjet.
7. **Diskretion:** Browserprocesoversigt udskriver PID og procesnavn i stedet for hele kommandoargumenter, som potentielt kunne indeholde signerede kiosk-URL'er.

## Testerklæring

- Python: `python -m pytest -q scripts/tests/test_clientflow_browser_guard_consent_no_flash.py scripts/tests/test_clientflow_remote_desktop_transport_recovery.py scripts/tests/test_livestream_hls_pipeline_progress_62.py backend/tests/test_clientflow_display_internet_gate.py` **26/26 PASS** i dette miljø.
- Frontend: fire målrettede Node.js testfiler (`terminalSupportGuides`, `wifiSupportCommands`, `terminalSupportCatalogAudit`, `terminalV2Contract`): **25/25 PASS**.
- Bredere frontend `node --test tests/*.test.mjs`: **256 PASS, 7 kunne ikke starte** på grund af manglende `vite`/node_modules i dette arbejdsområde. Dette er en *miljøbegrænsning*, ikke et bevis for CI-failure eller CI-success. Fuldt frontend-build, lint og dependency audits skal køres i GitHub CI på den godkendte Node/npm-version.
- Browseradfærd under timerrefresh, TTY-prompt, NetworkManager checkpoint/rollback, WiFi-recovery, Remote Desktop og capture på fysisk Ubuntu 26.04-klient er **ikke** blevet udført i denne kildekodepakke.

## Uafklarede forhold – ikke skjult under PASS

- Periodisk Mutter/PipeWire-opstart med nul billedbuffere: årsagen er ikke fundet. Der er **ikke** ændret GStreamer-kodec, timeout eller systempakker ud fra en hypotese.
- Løbende frame-watchdog og HLS `muxed_buffers` tæller: kræver design/test af rammeflow og klare timeout-kontrakter, før en sikker implementering er klar. De er ikke lukket af denne pakke.
- Superadmin-fejlhistorik/recovery ledger: særskilt database- og migrationsopgave; ingen ny Alembic-migration indgår.
- Om WiFi og terminalværktøjerne virker med præcis installeret NetworkManager og opfører sig korrekt ved afbrudt fjernadgang, kan kun bekræftes ved fysisk pilot. At Bash-syntaksen er gyldig er ikke det samme som en vellykket hardware-/netværkstest.

## Gates

1. Importer kun til separat code-review-branch. Kør CI, lint, test, dependency-audit, build, source fingerprint og korrekt release-toolchain.
2. Review cookie-CSS og alle UI-selektorer mod faktisk kiosk-URL; forbyd automatisk accept af cookies.
3. Fysisk pilot med gentagne timerstyrede reloads, nul cookie-flash, sikker WiFi-profiloprettelse og checkpoint-rollback med lokal fallback, samt terminalvejledninger på realistiske fejl.
4. Kontroller at eksisterende release-retention, godkendelsesgate, identitetsdecommission og sikkerhed er uændret.
5. Ingen merge/deploy/release uden eksplicit beslutning og grønne gates.
