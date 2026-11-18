# Fase 63D-6 · 1246 update-only katalogpromovering

- **Baseline**: frisk `main` ZIP fra 18. november 2026 kl. 13.53; GitHub commit `fce653fdce286bc9b65ffd380f5a9acdc84304fb`.
- **Branch**: `feature/display-63d6-1246-update-only-catalog-20261118`.
- **Godkendt artifact**: `clientflow-1.3.45-seq-1246` TAR SHA256 `e37de3250d58d313d57ad7bcbf59682cee342f2727c6ad5b188c8782342d4c78`, 223682560 bytes, approval `CF-1.3.45-1246-20261118-bc7adef-f36bcd0b`.
- **Render-store gate**: brugerens preflight/publicering/audit PASS; 3 beskyttede releases 1246, 1245 og 1244. Ingen automatisk sletning eller rollback.
- **Aktivt katalog**: 1245 `stable` fortsat `latest_stable` og `default_install_version`, 1246 `supported`, `update_allowed=true`, `installable=false`, `install_modes=[in_place_update]`, kun kilder 1.3.43–1.3.44.
- **Beskyttelse**: kataloget er en selector, ikke klientdeploymentautorisation. De allerede indførte 1246-operatorflag kræves stadig separat, præcist til Viborg1 client ID 3, og per-klient dobbelt gate under lås. Historiske pilot/fleet-konflikter afvises.
- **Database**: `cutover_enabled=false`, `fleet_open=false`, `fresh_install_open=false` og 1245 som singleton-stabil; branch ændrer ingen DB-migration eller miljøvariabel.
- **Kiosk**: funktionerne Genstart, fullscreen-polling og eventuelle Neon-DB-kald er ikke ændret. Statuslatens er observeret og udskudt til efter den fysiske 1246-pilot.
- **Vigtigt**: `STAGE ONLY` i katalogets immutable notes er historisk kildetekst fra den verificerede staging-record. Aktiv tilstand bestemmes af de faktiske katalogfelter, ikke noteprosa. Ingen promotion til stable/fleet/fresh-install er foretaget.
- **Fysisk pilot**: Viborg1 (ID 3) er i førkontrollen online/approved på Ubuntu 26.04 med ClientFlow 1.3.43/1244, ingen aktiv deployment eller recoveryfejl. Næste handling EFTER grøn GitHub CI + Render-deploy: uafhængig ny preflight og særskilt godkendelse af 1246-operatorflag, manuelt styret pilot, Livestream/Remote Desktop og recoverytest.
- ZIP er en delta-pakke. Upload med sti-hierarki til egen GitHub-branch, kør alle CI-gates, merge først ved fuld grøn CI og verificeret deploy. Ingen automatisk klientopdatering.
