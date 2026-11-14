# PlanIQ Display – ClientFlow 1.3.44 / 1245: kildefrysning og releaseforberedelse

**Status: SOURCE STAGE ONLY.** Dette dokument og den tilhørende kode er **ikke** en godkendt, bygget, publiceret eller installerbar release. Ingen ændringer er udført i Render, release-store, klientdatabase eller Viborg1 under stagingen.

## 1. Kildefrysning og sikkerhedsgrænse

- Ny kildeidentitet: `client/VERSION = 1.3.44` og `release_sequence = 1245`.
- Den aktuelt installerede og eneste katalogvalgbare release er fortsat **1.3.43/1244**. Dens tidligere godkendte og publicerede bundle (SHA256 `d3fdae8fb2a93f74431780f4aadde21625d10917e99cfbe6095ff2394e1e856b`) må **aldrig** overskrives med ny source.
- Live-katalog, deploymentregler, rollback-tilladelser, central release-sikkerhedspolitik og tidligere identitets-decommission **forbliver uændrede**. Den gamle katalogpost er fortsat `fresh_install`-only, `update_allowed: false` og `rollback_allowed: false`. `CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1` bevares i drift.
- Ny kilde må **ikke** udløse en ny fresh install, in-place update eller automatisk Genstart.
- Opdateringsvejen **fra den faktiske 1244-klient** kræver separat afprøvning og præcis godkendelse. Dette stages ikke ved at omskrive den historiske 1244-autorisation.
- Den eksisterende lock for Python 3.13.14 og tredjeparts-wheels, herunder patched PyJWT 2.15.1, fastholdes.

## 2. Samlet scope for den kommende runtime

Runtime-koden indeholder de tidligere implementerede ændringer fra seneste main: Browser Guard/cookie-refresh, WiFi-hjælpere og danske vejledninger, Livestream HLS-watchdog, Mutter/PipeWire-startupstage, kontrolleret retry-backoff, samt Remote Desktop-transportdiagnostik. Ingen af disse kildeændringer er bevist installeret på Viborg1 endnu.

**Uafklaret:** Den fysiske årsag til Mutter/PipeWire `source_buffers=0` er ikke dokumenteret løst. Backoff og logning forbedrer fejlhåndtering; reelt billedflow skal verificeres under pilot. Den periodiske Render-502-episode kræver separat driftskorrelation ved gentagelse.

## 3. Read-only preflight og tests

Kør fra projektets rod efter staging og CI-checkout:

```bash
python scripts/clientflow_1245_source_preflight.py --repo-root .
python -m pytest -q scripts/tests/test_clientflow_1245_source_stage.py scripts/tests/test_clientflow_1244_source_stage.py backend/tests/test_clientflow_release_identity_51f.py backend/tests/test_clientflow_1244_release_window.py
```

Preflight **afviser** forkert sourceversion, ændret katalog, åbnet in-place-update/rollback, ændret sikkerhedspolitik, ændret Python-lock og svækket keyless-releaseworkflow. Den producerer kun kontrolresultater og muterer intet.

## 4. Nødvendige adskilte gates – ingen må springes over

1. Grøn GitHub CI **push** på eksakt ny main SHA, med test, Ruff, frontend, dependency-audit og sikkerhed.
2. Byg nyt, deterministisk runtime-input-transport for **samme** kilde-SHA; brug den eksisterende SHA-lock. Transport-URL og SHA256 er input, ikke godkendelse.
3. Kør **release-build.yml** med eksakt full 40-tegns source SHA, runtime-inputs URL/SHA; kræv to byte-identiske uafhængige builds samt Ubuntu 26.04 executable gate. Handoff forbliver **unapproved**.
4. Foretag sikkerhedsgennemgang af manifest, install-mode, source-proveniens, kompatibilitet og pilot/rollbackplan. Først derefter særskilt manuel release-approval, med eksakt candidate-, installer- og source-SHA samt godkendelsesreference.
5. Publicér godkendte bytes med no-replace i 51M artifact-store. Verificer eksakt SHA/size samt tidligere 1244-artifact og policy for maksimalt tre valgbare releases.
6. En fremtidig **separat katalogpromovering** må kun vælge 1245, efter artifact-store har den korrekte godkendte bundle, og 1244 → 1245-in-place-kompatibilitet er bekræftet. Indtil da forbliver 1244 den eneste katalogvalgbare release.
7. **Ingen deployment på Viborg1** uden eksplicit operatørgodkendelse, fysisk fallback og sikker rollback. Bevar klientidentitet, browseropsætning, MFA-adskillelse og historisk decommission. Test både Livestream alene/med Remote Desktop, gentaget nul-buffer-opstart, stop under backoff, HLS-stall, WiFi-rollback, cookie-refresh, genstart og fysisk kiosk.

## 5. Stop-kriterier

Stop ved enhver CI-fejl, checksumdrift, manglende reproducerbarhed, manglende source-bindingsbevis, uverificeret release-metadata, utilsigtet åbning af 1244-deployment, fejlet in-place-kompatibilitet eller en usikker recovery/rollbackplan. Der må ikke erstattes gamle releasebytes eller ryddes op i store uden separat, eksplicit autorisation.
