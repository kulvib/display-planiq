# PlanIQ Display – nyeste stabile release som standard, kontrolleret pilot og udrulning

**Status 14. november 2026: SOURCE ONLY / DISABLED.** Denne kodeændring godkender, publicerer, promoverer eller installerer **ingen** ClientFlow-release. Den gældende kildeidentitet er 1.3.44/1245 fra reproducible build på commit `06857104952ebb40bf1394c423c01332d28f8d5e`. De byte-identiske 1245-kandidatbytes ændres **ikke** ved denne backend-/policyændring.

## Besluttet model og sikkerhedsregler

1. **Kun stabilt promoverede releases er nyinstallationsstandard.** I det aktive katalog skal `latest_stable == default_install_version`, med præcis én stabil/fresh-installérbar release. Under pilot forbliver den tidligere stabile version standard. Katalogvalideringen afviser andre kombinationer.
2. **1245-pilot er eksakt og update-only.** Et *fremtidigt*, særskilt publiceret katalog kan indeholde 1244 stable/fresh-only og 1245 supported/update-only. Undtagelsen er præcist bundet til 1244 → 1245, uden rollback, repair, fresh-install, automatisk genstart eller generel aktivering. Nuværende katalog indeholder fortsat kun 1244.
3. **Kildekode og miljøvariabler er ikke releaseautorisation.** `clientflow_pilot_1245_approval.json` leveres med `approved:false`, og godkendt bundle-SHA/størrelse/reference er `null`. Pilot kræver senere et særskilt godkendt og revideret lock i kildekoden, den eksakte godkendte bundle publiceret i artifact-store og `CLIENTFLOW_1245_PILOT_CLIENT_ID=3`; alle tre gamle pilotflags skal være tomme.
4. **Klientidentitet:** Kun backend `client_id=3` (Viborg1), rapporteret nuværende 1.3.43, mål `clientflow-1.3.44-seq-1245`, eksplicit superadminhandling med begrundelse. Før og efter klientrække-lås valideres. Efter låsen sammenholdes publiceret bundle SHA256, størrelse, source commit, kandidat-SHA og approval-reference med den kilde-låste godkendelse.
5. **Efter succesfuld pilot kan der udarbejdes særskilt stabil katalogpromotion.** Den skal i **samme** validerede katalogændring pege `latest_stable` og `default_install_version` på 1245. En tidligere release må ikke stå som endnu en `stable`/fresh-installérbar version. Bevarede approved artefakter og recoveryhistorik ligger separat; højst tre versioner tillades som aktive katalogvalg, men der er ingen automatisk rollback. Promotion kræver fortsat separat menneskelig beslutning, dokumenteret fysisk accept og verificeret godkendt artifact.
6. **Kontrolleret stabil udrulning er selvstændig tilladelse.** Efter promotion kræver hver administrativ opdateringsordre `CLIENTFLOW_STABLE_ROLLOUT_ENABLED=1`, eksakt `CLIENTFLOW_STABLE_ROLLOUT_RELEASE_ID`, eksakt `CLIENTFLOW_STABLE_ROLLOUT_BUNDLE_SHA256` samt `CLIENTFLOW_STABLE_ROLLOUT_CLIENT_IDS` som kommasepareret liste med højst 25 unikke positive klient-ID'er. Ingen wildcard/`all`; ukendte, for gamle eller allerede opdaterede klienter afvises. Der er ingen automatisk push ved en ny standardversion.
7. **Klient-recovery og security kan ikke nedprioriteres.** Central min-safe-policy, rollback-trust, MFA/kiosk-adskillelse, gamle credentials-decommission, 1244 source/historik, 25s startup timeout og tekniske deployment-låse forbliver uændrede.
8. **Nyinstallationer er fortsat suspenderet i drift** (`CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1`) indtil særskilt verificeret ophævelse – også selv når en ny standardversion promoveres.

## Hvad denne ændring faktisk introducerer

- `backend/service1/clientflow_pilot_1245.py` og det deaktiverede approval-lock: præcis én klient, én kilde, én retning, én fremtidig godkendt bundle.
- `backend/service1/clientflow_releases.py`: den præcist afgrænsede 1245 pilotkatalog-undtagelse; i stabil fase håndhæves nyeste stabile = fresh default og nøjagtigt én stabil release.
- `backend/service1/clientflow_stable_rollout.py`: default-off release-/SHA-/klientbølgeautorisation til senere stabil udrulning; admin og artifact-reverification forbliver i eksisterende deployment-flow.
- `backend/service1/routers/clientflow_deployments.py`: vælg særskilt pilot- eller stable-rollout-guard, genkontrollér efter per-klient DB-lock, og journalfør korrekt flag.
- `scripts/clientflow_1245_pilot_policy_preflight.py`: skrivebeskyttet kildekontrol med 9 punkter, som fejler hvis 1245 aktiveres for tidligt.
- Negative regressionstests for alle afviste flag, klienter, versionskombinationer, katalognavne, artifacts og udrulningsbølger.

## Fortsat påkrævede gates (i denne rækkefølge)

**A – Nu:** GitHub CI af denne policy-branch, dansk dokumentation og sikkerhedsreview. **Ingen ændring på Viborg1.**

**B – Releaseartefakt:** Særskilt manuel `release-approve.yml` efter godkendelse, med de verificerede uforanderlige SHA-værdier fra den eksisterende reproducerbare 1245-build. Godkendt TAR publiceres efter no-replace/attestation og genverificering i artifact-store. Dette må ikke ske implicit fra denne kodepakke.

**C – Pilotforberedelse:** Integritetsattest af lokalt installeret 1244 (kendt release-ID, godkendt SHA `d3fdae8fb2a93f74431780f4aadde21625d10917e99cfbe6095ff2394e1e856b`, aktivt symlink, ingen aktiveringsintent, friske services), fysisk `cfadmin`-adgang, transport/Internet, strøm og dokumenteret recovery ved mislykket aktivering. Den tidligere read-only statuskontrol på Viborg1 viste klient-ID 3, version 1.3.43/1244, korrekt symlink og ingen aktiveringsintent; fysisk fallback er dog endnu ikke attesteret.

**D – Pilotautorisation:** Først efter eksplicit godkendelse: gennemgå eksakt approved bundle, commit, kandidat og installer, udfyld låsen fra den ægte approval-record, og lav separat, auditeret, update-only katalogændring. Aktiver piloten **kun** for klient-ID 3 og med superadmin-begrundelse. Ingen global defaultændring endnu.

**E – Fysisk pilotaccept:** Kontroller i den grafiske Ubuntu 26.04-session minimum: billede i Livestream og stigende source-/encoded-buffers, første og løbende HLS-segmenter, samtidig Remote Desktop, stop/retry/backoff, netværksfald/retur, browser-refresh og cookie-guard, klientidentitet/status, ingen rettigheds- eller credentialsregression, reboot og ingen `NeedDaemonReload`. Observer både teknik og funktion. **Stop ved nul-buffer, manglende recovery eller fjernstyringsfejl**. Den gamle nul-buffer-grundårsag er ikke dokumenteret løst.

**F – Stabil promotion:** Separat dokumenteret accept og kode-/katalogreview. Nyeste stabile (1245) bliver atomisk ny `latest_stable` **og** `default_install_version`. For at bevare kun én aktiv fresh-install-standard må 1244 ikke samtidigt stå som en anden installérbar standard i kataloget. Bevar tidligere godkendte bytes i historik/recovery-arkiv uden at åbne automatisk rollback.

**G – Bølgevis udrulning:** Særskilt, præcis release-SHA og klient-ID-liste (maks. 25 pr. bølge), admin-ordrer per klient, målt success/error-rate og automatisk stop ved fejl. Kun når det er sikkert ophæves eventuel fresh-install-suspension særskilt. Udrulning udløses ikke af promotion alene.

### Sikkerhedsstop

STOP ved mislykket CI, forkert kilde/SHA, ændret 1244 release, ny status `stable` før fysisk pilot, bredere pilotflag, uventet rolloutgruppe, ukendt godkendelsesrecord, uafklaret fysisk nul-buffer, manglende 1244 recovery eller konflikt mellem de nyeste/default versionsfelter. Katalogvalidering er en schema-gate, ikke bevis for fysisk accept; den menneskelige beslutning og artefaktattesteringen er ufravigelige.

## Lokal skrivebeskyttet kontrol

```bash
python scripts/clientflow_1245_source_preflight.py --repo-root .
python scripts/clientflow_1245_pilot_policy_preflight.py --repo-root .
python -m pytest -q \
  backend/tests/test_clientflow_1245_exact_single_client_pilot.py \
  backend/tests/test_clientflow_stable_rollout_policy.py \
  backend/tests/test_clientflow_1244_release_window.py \
  scripts/tests/test_clientflow_1245_pilot_policy_preflight.py
sha256sum --check --strict SHA256SUMS.txt
```

**NB:** Preflightens `PASS` er alene grønt lys for kilde- og CI-staging, aldrig for artifact approval, katalogændring eller fysisk deployment.
