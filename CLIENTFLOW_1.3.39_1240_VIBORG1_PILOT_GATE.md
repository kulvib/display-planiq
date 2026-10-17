# ClientFlow 1.3.39 / 1240 — afgrænset Viborg1-pilotgate

**Status: Udviklingsfase og kontrolleret fysisk pilottest — ikke produktionsudrulning. Pilotpolicy i kildekode, men FRAKOBLET som standard. Ingen klientopdatering eller rollback er udført/godkendt af denne PR.**

Render og de tilsluttede fysiske klienter bruges her som udviklings-/testmiljø. Korrekt hash, recovery og fail-closed autorisation er fortsat nødvendige, fordi testen påvirker rigtige installationer, men testforløbet skal ikke omtales eller behandles som en produktionslancering.

## Bekræftet myndighed og immutable bytes

- Pilot: **Viborg1** (`viborg1-NUC14MNK-B2`), `client_id=1`; fysisk maskine omtalt som Heidi1.
- Baseline: aktiv `clientflow-1.3.38-seq-1239`, SHA-256 `02c3d4261eabdac4b9967a3aad4419453f61ca483ef4eb34dacf284d3af16a11`; normal og verificeret canonical Status, aktiv updater.timer, ingen afventende aktivering.
- Godkendt mål: `clientflow-1.3.39-seq-1240`, immutable bundle SHA-256 `40fb64e3e8e38686f4b03ee8f66afc81fe7a03247ed723d8a6ce636aebbcb798`, størrelse **223498240**.
- Kildefrys: `820e605d2e30f8dfea2914d81a1c6ee87053b334`; kandidat SHA-256 `b083cb8e18e436e0b76cf66ac8cf1daee678dcdb9fb32b0760291d0944f9869a`.
- Approval-reference: `clientflow-1.3.39-seq-1240/b083cb8e18e436e0b76cf66ac8cf1daee678dcdb9fb32b0760291d0944f9869a`.
- GitHub: [godkendt transport](https://github.com/kulvib/display-planiq/releases/tag/clientflow-1.3.39-1240-approved-transport). Render release-store `RELEASE_1240_PUBLICATION=PASS` og `RELEASE_STORE_AUDIT=PASS` med **4** gyldige releases; ingen automatisk sletning.

## Implementeret adgangspolitik

- `latest_stable` og `default_install_version` forbliver **1.3.38**. Det er stadig *eneste* fresh-install mål.
- 1.3.39 er alene `supported`, `installable=false`, `install_modes=[in_place_update]`, `rollback_allowed=false`. Katalogets `update_allowed=true` betyder kun *versionskandidat* – **ikke** universel klientautorisation.
- Backend afslår **enhver** ny deployment, medmindre `CLIENTFLOW_1240_PILOT_CLIENT_ID` er sat til **præcis** teksten `1` i Render-miljøet, klient-ID er det præcise heltal `1`, canonical Status er frisk/online og rapporterer `1.3.38`, destination er præcis 1.3.39/1240, og superadministrator angiver en ikke-tom begrundelse.
- Ingen pre-first-activation repair, ingen downgrade, ingen same-version deployment, og ingen 1.3.39-fresh-install.
- Serveren låser klientrækken og genvaliderer status/pilotpolicy *efter* låsen. Den fastlåser også mål-bundlens SHA-256, størrelse, original kildecommit, kandidat-SHA og approval-reference; et ændret artifact afvises.
- 1.3.38 forbliver ikke-godkendt til **remote rollback** (`update_allowed=false`, `rollback_allowed=false`). Lokal automatisk recovery i den signede 1.3.39-udgivelse er en særskilt klientmekanisme. Fjernrollback kræver ny dokumenteret godkendelse og test.
- Pilotskiftet er en **backend-miljøindstilling**. Den må ikke ligge i kildekoden, frontend, Dockerfile eller et offentligt build. En allerede autoriseret igangværende transaktion kan stadig fortsætte, selv om flaget efterfølgende fjernes; brug det eksisterende cancel-/recovery-forløb og vurder transaktionsstadiet.

## Kontrolleret udviklings- og pilottest (kræver særskilt accept før fysisk opdatering)

1. PR/CI skal være grøn, inkl. schema/test/migrations, og Render skal redeployes med denne katalogpolicy. **Lad `CLIENTFLOW_1240_PILOT_CLIENT_ID` være UDEFINERET**, indtil live smoke og katalogkontrol er PASS.
2. Bekræft backup og diskreserve for både PostgreSQL og samtlige godkendte TAR-filer; fravær af defekte releasefiler og unverificerede artifacts. Kontroller igen, at fysiske Viborg1 er `client_id=1`, aktiv 1.3.38/1239, online status frisk, og ingen aktiv System-kommando eller anden deployment.
3. Gennemfør negative API-tests på Render-backenden i udviklingsmiljøet *uden* pilottilladelse; verificér 409 og ingen deploymentoprettelse. Samme gælder andre klient-ID'er. Dette er en releasegate, ikke en almindelig UI-kliktest.
4. Giv særskilt tilsagn til **præcis én** fysisk in-place opdatering fra 1.3.38 til 1.3.39 og overvåget aktiverings-/health-/auto-recovery-test. Først da sættes `CLIENTFLOW_1240_PILOT_CLIENT_ID=1` i Render Environment og deploy kontrolleres.
5. I Control Room: kun én superadmin-bestilt deployment mod klient 1, target `1.3.39`, med eksplicit årsag. Bekræft backendens godkendte SHA/size/source inden klienten accepterer ordren. Observer download → SHA/manifest → stage → activate → reboot/health → backend kvittering.
6. Fysisk acceptance: kiosk Chrome/Wayland, grafisk ClientFlow-GUI, clipboard, cookie-/popupguard uden flash, informationsskærm og URL-/refresh-semantik, status/realtime, Remote Desktop, Terminal, livestream, systemd-log, uptime, fejlfrihed; også offline/restart/recovery når det kan gøres forsvarligt.
7. Slå pilottilladelsen fra igen (fjern miljøvariablen), når transaktionen er afsluttet, og verificér 409 ved nye deploymentforsøg. Dokumentér den faktiske transaktionsstatus og evt. autoriseret recovery. **Ingen** bred installation på testflåden eller fjernrollback på baggrund af denne PR alene.

## CI-port

Kontrakttests skal fortsat verificere 1239-fresh-install, original immutable approval og historik, 1240-kandidatens specifikke tilladelser, env-default-deny, fejlagtige klient-ID'er/versioner, broadened release metadata, manglende begrundelse, repair/downgrade, manipulerede SHA/provenance og serverens anden kontrol efter klientsidelås. Test må ikke svækkes eller springes over for at få grøn CI.
