# PlanIQ Display · Fase 63D-4 · Approved 1246 pilot staging, fail-closed

**Kildegrundlag:** brugerens friske `display-planiq-main(20261118-115838).zip` fra 18. november 2026. Repositoryets originale `main`-revision: `bc7adef9fec4f4f4bc8382a5a9d212b71b9a9085`. Ingen ændringer i godkendt ClientFlow runtime, aktiv releasekatalog, Neon/Render-konfiguration eller klienter.

## Verificeret ekstern artifact-evidens (kilde fra GitHub Actions, ikke fra ny kode)

- Runtime input transport #34: GitHub run `44295653329`, PASS.
- Reproducerbart kandidat-build #52: GitHub run `44296249876`, PASS. Kandidat SHA256 `f36bcd0b9080b765838b2c2a3ae582a161346f23b3d0c0404683158cf55865e7`.
- Manuel release-artifact-godkendelse #34: GitHub run `44298267835`, PASS.
- Immutable GitHub archive #5: GitHub run `44298870994`, PASS, prerelease `clientflow-1.3.45-1246-approved-transport`.
- Approved TAR `clientflow-approved-1.3.45-1246.tar`; størrelse **223682560 bytes**; SHA256 `e37de3250d58d313d57ad7bcbf59682cee342f2727c6ad5b188c8782342d4c78`.
- Source commit `bc7adef9fec4f4f4bc8382a5a9d212b71b9a9085`; fresh installer SHA256 `7613a8d0fa2bf73a06ee3afb45d564d6831d4172c82f1dad336bc6e66049e488`.
- Godkendelsesreference `CF-1.3.45-1246-20261118-bc7adef-f36bcd0b`.
- GitHub asset: `https://github.com/kulvib/display-planiq/releases/download/clientflow-1.3.45-1246-approved-transport/clientflow-approved-1.3.45-1246.tar`.

**Godkendte GitHub-bytes er IKKE en Render release-store publication, aktivt katalog, pilotautorisation, fuld DB-cutover, fleet-adgang eller fysisk accept.** Der er endnu ikke dokumentation for, at Viborg1 har installeret 1.3.45/1246 eller at Render store indeholder den.

## Hvad koden gør

1. `clientflow_pilot_1246_approval.json` + `clientflow_pilot_1246.py` fastlåser *præcis* GitHub source, approval reference, kandidat-SHA, installer-SHA og godkendt TAR SHA/størrelse. Ingen værdi kan leveres dynamisk fra et miljøflag. Et afvigende/manglende/symlinket lock-dokument afvises.
2. Pilotselektoren i `routers/clientflow_deployments.py` genkender **1246 før** generisk stable-rollout. En ukendt, delvist aktiveret eller uautoriseret 1246 kan aldrig falde tilbage til fleet. Piloten kræver *to* fraværende-som-standard operatørflag, eksakt backend klient-ID **3**, aktivt releasekatalogs godkendte 1246 entry, frisk Status-version fra `1.3.43` eller `1.3.44`, ingen repair/downgrade og konkret superadmin-begrundelse. Samme identitet og publicerede bytes kontrolleres igen efter klientlås, før en deployment kan oprettes.
3. `clientflow_release_catalog_1246_pilot.stage.json` er **ikke** det aktive katalog. Det beskriver en *mulig fremtidig* update-only 1246-pilot, mens 1245 fortsat er eneste stabile version og fresh-install-standard, med 3-versioners arkivretention. Repositoryets katalogvalidator er udvidet med en snæver, fail-closed 1246-update-only-undtagelse og testet med både 1244 og 1245 som kilde; det aktive `clientflow_release_catalog.json` er stadig den gamle stabile 1245.
4. `clientflow_release_pilot_stage_1246.py` kontrollerer i en bounded, read-only funktion source lock, staged catalog og eksisterende låst aktivt 1245-katalog. Administrationen viser 1246 som godkendt **GitHub-arkiv**, men udsteder **ingen rettigheder**. Render-store og installation markeres som *ikke verificeret*, ikke som bevist fejlet eller fuldført.
5. `scripts/clientflow_63d4_verify_1246_archive.py` verificerer den *lokalt downloadede, eksakte TAR* offline. Kanonisk `open_verified_bundle` udfører dyb payload- og manifestverifikation og genberegner checksum; vores wrapper kontrollerer derefter udtrykkelig source, version, approval, installer, størrelse og SHA. Kommandoen downloader, publicerer, sletter eller installerer intet.

### Eksempel – senere, read-only verifikation efter en særskilt downloaded TAR

```bash
python3 scripts/clientflow_63d4_verify_1246_archive.py \
  --approved-tar /ABSOLUT/STI/clientflow-approved-1.3.45-1246.tar
```

Forventet slutlinje: `CLIENTFLOW_1246_ARCHIVE_PREFLIGHT=PASS`. Beviset er kun for *lokale, signerede bytes*, ikke for katalog eller installation.

## Kodebase, der bevidst ikke ændres

- Ingen ændringer i det aktive `backend/service1/clientflow_release_catalog.json`, gamle 1245-godkendelse eller 1245-pilotflags.
- Ingen ændringer i `client/runtime`, `client/release`, `client/VERSION`, `client/release/release-input.json`, installationslås eller klientens recovery.
- Ingen ændring i DB-modeller, migration, `clientflow_release_governance.py`, `_bound_control` eller dets låste flag.
- Ingen signering, GitHub workflow-dispatch, Render release-publication, databasedeployment, klientændring eller cleanup.
- Fysisk pilotaccept, to-personers udrulningsgodkendelse, normal fleet og DB-cutover er fortsat særskilte gates.

## Hvad mangler, og hvorfor det ikke kan udføres automatisk

1. **Offsite/kildearkiv:** Kontrollér/download TAR, genberegn SHA256, kør offline preflight. Dette er kun muligt med faktiske GitHub-bytes, ikke ved blot at stole på et grøn workflow.
2. **Render release-store:** Kontroller uforanderlighed og fri diskplads; udfør separat autoriseret **no-replace** publication af præcis godkendt TAR; verificér efter-publication hash og behold tre godkendte releases til recovery. Ingen implicit promotion.
3. **Fysisk Viborg1-pilot:** Verificér klient-ID, nuværende Status-release, backup/recovery og ingen aktive deployments; få eksplicit operatørgodkendelse til den særskilte katalog-/pilotflags-transition, **før** bestilling af én manuel deployment.
4. **Faktiske tests:** Test Remote Desktop og Livestream sammen, inputlatens, skærmoptagelsens recovery, netværksafbrydelse, reboot og rollback. Ingen begrundelse for at kalde Mutter/PipeWire-incident løst uden målinger.
5. **Governance & cutover:** Efter fysisk pilot og to-personers accept kobles staged transaktioner til *beskyttede* HTTP-adminhandlinger og DB-grants, med gammel pilotguard stadig som uafhængig dobbeltlås. Må ikke gennemføres bare fordi CI er grøn.

## Regres­sions­gates

- Eksakt kilde- og bundling-binding; negative tests af klient-ID, gamle/samtidige pilotflag, alle felter i releaseidentitet, rollback, repair, ændret Status og mismatched publiceret artifact.
- Stagekatalog valideres med repositoryets kanoniske validator for både 1.3.43 og 1.3.44 på Ubuntu 26.04; negative tests afviser 1246 som fresh-install, stable eller implicit default.
- Read-only adminrespons og frontend afviser falske deployment- eller cutoverpåstande.
- Offline TAR-preflight bliver testet syntetisk, med fejlsimulering af ændret source, manifest, SHA, installer, størrelse, path og afbrudt signaturvalidering. **Ægte 223 MB TAR er ikke blevet hentet i dette kodearbejde.**
- Python unit-test og frontend node-test skal være grønne lokalt og derefter i GitHub CI; 63D-4 kan ikke erstatte en fysisk pilot eller release-store postflight.
