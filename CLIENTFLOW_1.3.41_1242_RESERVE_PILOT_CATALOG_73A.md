# ClientFlow 1.3.41 / 1242 — reserveklient-pilot i katalog (73A)

**KATALOG- OG KODEGATE – IKKE FYSISK ACCEPT, IKKE KLINTUDRULNING.** Denne ændring er en særskilt efterfølger til den allerede godkendte og immutable source SHA `33fb7bafa9cd37b8ab3bebb437c1e4d81a50460d` samt offentliggjorte TAR. Ingen godkendte ClientFlow-binary bytes ændres. GitHub CI og Render-smoketest kræves før nogen pilot kan aktiveres.

## Verificeret immutable kilde og driftsdata

- Release: `clientflow-1.3.41-seq-1242`, Ubuntu 26.04/amd64, runtime Python 3.13.14.
- Approved SHA-256: `5b6603f9169870e867d340a567df1194c57dfb254b306328c07f1366023aabce`; størrelse `223610880` bytes.
- Approved source commit: `33fb7bafa9cd37b8ab3bebb437c1e4d81a50460d`.
- Candidate: `d240a32595d4d33f33bfbff39b071f2bb6fba3e98a281b8718b30c3b43ca8633`; reference: `CF-1.3.41-1242-PILOT-20261030`.
- GitHub approval og transport verified; Render artifact-store immutable publication/postflight PASS, fire validerede bundles og ingen automatisk sletning.

## Afgrænsning og sikkerhedsgrænser

- Katalogsekvens 1242; stadig `latest_stable=default_install_version=1.3.38`, én installérbar release, præcis 1.3.38 som fresh-install. 1.3.39 forbliver fraværende.
- 1.3.40/1241-piloten forbliver uændret som historisk katalogmedlem og særskilt guarded backend-gate; ingen ny Heidi1-autorisation.
- 1.3.41/1242 er `supported`, `installable=false`, kun `install_modes=[in_place_update]`, `update_allowed=true`, `rollback_allowed=false`, og kræver **præcis 1.3.38 som eksisterende version**. Ingen fresh-install, repair eller downgrade gennem update-API.
- Ny eksplicit `CLIENTFLOW_1242_PILOT_CLIENT_ID`: fraværende som standard; accepterer kun ét kanonisk positivt decimalt klient-ID større end 1 og højst PostgreSQL integer grænse. `1` (Heidi1), wildcard, flere IDs, ledende nuller, mellemrum og ikke-ASCII afvises.
- Før aktivering skal `CLIENTFLOW_1241_PILOT_CLIENT_ID` være deaktiveret/fjernet. Samtidige 1241- og 1242-pilotgates afvises.
- Autorisation kræver superadministrator, godkendt ikke-slettet klient, frisk autentisk runtime Status, kompatibel Ubuntu, begrundelse, korrekt release-ID og alle immutable TAR-checksums; gentages efter eksklusiv klientlås og inden deployment registreres. Ingen automatisk batchudrulning.
- Den immutable 1242-trust har manuel rollback **slået fra**. Automatisk fejlet aktiverings-recovery er uændret og skal fysisk verificeres før videre udrulning.

## Opsplitning i adskilte driftstilladelser

1. Flet kun ændrings-only branch efter **grøn GitHub CI** og verificeret frisk main ZIP; Render deploy/Smoke skal gennemføres separat med `CLIENTFLOW_1242_PILOT_CLIENT_ID` **fraværende**, og gamle pilot-flags slukket hvor relevant. Ingen klientinstallation under deploy.
2. Dokumentér én konkret dedikeret, fysisk tilgængelig reserveklient med Ubuntu 26.04 og en verificeret aktiv ClientFlow 1.3.38 før aktivering. Klienten må ikke være Heidi1, og må ikke have åbent deployment eller aktiv System-kommando. Klientens faktiske backend-ID fastlægges via sikker produktionsstatus; indtastes ikke som en gætteværdi.
3. Indhent særskilt godkendelse, sæt `CLIENTFLOW_1242_PILOT_CLIENT_ID=<verificeret reserveklient-id>` for denne ene klient, deploy, kontroller status uden installation, opret manuelt 1.3.41 deployment med årsag gennem superadmin API. Aldrig via `latest` eller `stable`.
4. Fysisk test: netværk Ethernet/WiFi og offline-gate, Wayland/Chrome/GUI, faktisk HLS første segment og afspilning, Remote Desktop auth/WebSocket/fallback, Control Room og Clientlist, kalender, kold genstart, stable systemd rapportering, deaktiveret manuel rollback og automatisk failed-activation recovery med lokal redningsadgang.
5. Deaktiver flag straks efter test, dokumentér faktisk outcome og eventuelle fejl uden at omskrive immutable release eller slække på sikkerhedsregler. Forbliver test-release indtil ny særskilt produktionsgodkendelse.

**Ingen Ed25519-privat rollbacknøgle behøves.** Ingen ændring af Python runtime, ClientFlow TAR, database-schema, signing, USB-installatør eller Heidi1 sker i denne branch.
