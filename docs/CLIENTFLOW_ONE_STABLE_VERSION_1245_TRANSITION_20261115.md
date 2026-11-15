> **OPDATERET STATUS 15.11.2026:** Dette dokument beskriver den tidligere to-fasede implementeringsplan og er bevaret som historisk begrundelse. Den valgte plan er nu gennemført i den nye *kodekandidat*: Det aktive katalog har én stabil 1245-release til både nyinstallation og opdatering, men fysisk pilot og almindelig installation er fortsat spærret af særskilte låse. Se `docs/CLIENTFLOW_1245_ONE_STABLE_VERSION_ACTIVE_GATED_20261115.md` for den gældende tekniske kontrakt. Intet er aktiveret i produktion alene ved at oprette kildekandidaten.

# PlanIQ Display – én stabil ClientFlow-version til nyinstallation og opdatering

**Designbeslutning 2026-11-15:** Der skal være **præcis én gældende stabil ClientFlow-version** på tværs af nyinstallationer og kontrollerede opdateringer. En midlertidig pilot er ikke en anden standardversion. Eksisterende klienter kan fortsat køre en tidligere installeret version, indtil deres eksplicit godkendte opdatering er gennemført.

## Verificeret releaseidentitet – ingen ny klientbuild

Den samme, manuelt godkendte, immutabelt arkiverede R2-TAR understøtter **begge** installationsformer i sit eget `manifest.json`: `fresh_install` og `in_place_update`. Det er verificeret ved direkte gennemlæsning af den vedhæftede, godkendte ClientFlow-TAR.

| Felt | 1.3.44/1245 R2 |
|---|---|
| Release ID | `clientflow-1.3.44-seq-1245` |
| Source commit | `06857104952ebb40bf1394c423c01332d28f8d5e` |
| Kandidat-SHA256 | `ffe58332c8e3b263e00f299e363dc95ecb9ac7e0176fd51888be98fecad9bd97` |
| Fresh-installer-SHA256 | `fc843b6b37772996ecbfa67ff08a0e6f372443bf7d6104ca28d616855bc5737a` |
| Godkendt TAR-SHA256 | `28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5` |
| Godkendt størrelse | `223610880` bytes |
| Godkendelsesreference | `CF-1.3.44-1245-20261114-0685710-ffe58332-R2` |
| Godkendelsesrun | `43640050058` |

Den godkendte TAR er allerede arkiveret på GitHub og publiceret i Render release-store. **Denne kildeændring må aldrig ændre releasepakken, rebygge dens klientruntime eller genbruge en anden SHA256 under samme release-ID.**

## Fase A – kontrolleret fysisk pilot (denne GitHub-branch)

- Aktivt `clientflow_release_catalog.json` indeholder **1244 stable/fresh-only** og **1245 supported/update-only**. Der er stadig kun én stabil version: `latest_stable = default_install_version = 1.3.43`.
- 1245 er kun en afgrænset opdateringskandidat fra 1244 til 1245 på **Viborg1, backend klient-ID 3**. Ikke en ekstra stabil version og ikke en nyinstallationsstandard.
- Releasegodkendelseslåsen i kildekoden er bundet til R2-bytes (`approved: true`), men backend afviser alle pilotordrer, indtil **begge**, præcise og separat besluttede Render-operatørflag er sat:
  - `CLIENTFLOW_1245_PILOT_CLIENT_ID=3`
  - `CLIENTFLOW_1245_PILOT_ARM_REFERENCE=CF-1.3.44-1245-20261114-0685710-ffe58332-R2`
- Disse flag sættes **ikke** ved merge eller redeploy. De må først ændres efter særskilt operatørgodkendelse, ny physical preflight og recoveryplan.
- Kun superadministrator kan afgive manuel deploymentordre med begrundelse; backend kontrollerer eksakt klient, current-version, source/target, publikeret SHA256 og godkendelsesreference både før og efter klientens databaserækkelås.
- `CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1` beholdes indtil separat fresh-install-accept. Ingen automatisk rollout, manuel rollback, downgrade eller fjernelse af dekommissionerede identiteter.
- Fysisk skærm/tastatur og lokalt `cfadmin`-login på Viborg1 er bekræftet. Skrivebeskyttet 1244 recovery-baseline bestod 7/7. **En fejlinduceret, fysisk recoverytest er endnu ikke dokumenteret som bestået.**

**STOP hvis:** CI er rød, Render deploy er i gang/fejlet, en pilot/maintenance env-gate har ukendt værdi, 1244-baseline afviger, SHA256 ikke matcher, pending activation er sat, remote desktop/livestream bliver utilgængeligt eller lokal fallback ikke er klar.

## Fase B – efter en **bestået** fysisk 1245-pilot (kræver NY branch/CI/approval)

En **allerede testet, men inaktiv** kandidat ligger i `backend/service1/clientflow_release_catalog_1245_stable.stage.json`. Den er **ikke** runtimekataloget og må ikke kopieres til `clientflow_release_catalog.json`, før der foreligger en særskilt, dokumenteret promotion-beslutning.

Efter godkendelse skal den aktive releasekatalogpolitik **atomisk** ændres til:

- **Kun én aktiv releasepost:** 1.3.44/1245, `status=stable`.
- `latest_stable = default_install_version = 1.3.44`.
- `installable=true`, `update_allowed=true`, `install_modes=["fresh_install", "in_place_update"]`.
- Hver opdateringsordre forbliver eksplicit med release-ID, begrundelse og en afgrænset operatørgodkendt klientbølge (`CLIENTFLOW_STABLE_ROLLOUT_*`, maks. 25 klienter pr. bølge). Ingen automatisk opdatering.
- Den stabiliserede kode kontrollerer, at opdateringens R2-SHA256, størrelse, kildecommit, kandidat-SHA og godkendelsesreference **matcher den fysiske pilots godkendte release**.
- **1244 opbevares uændret i den beskyttede godkendte Render-store**, men bliver ikke endnu en valgbar standard i aktivt katalog. De sidste tre godkendte artifacts bevares i store, efterhånden som releases tilføjes; ingen automatisk sletning og ingen uautoriseret downgrade.
- **Nyinstallationer** peger først på 1245, når promotion har bestået og den særskilte suspensions-gate er ophævet efter en supervised fresh-install acceptance. Promotion alene ophæver ikke vedligeholdelsesspærren.

**Bemærk:** Selv efter promotion kan en tidligere installeret klient stå på 1244 indtil manuel opdatering. Det ændrer ikke ved, at der kun findes én gældende, godkendt *målversion*.

## Hvad denne branch leverer

- Fuld, eksakt Viborg1-pilotkode med begge **default-off** operatørflag, ingen automatisk klientopdatering.
- Read-only stable-promotion-template med én aktiv stabil 1245-release til **begge** installationsformer, men **ikke** anvendt i produktion.
- Hård catalog-validator: 1245 stable kan **kun** være en enkelt releasepost med begge install-modes; pilotfasen er den eneste særskilte update-only-undtagelse.
- Hård stable-rollout-regel: 1245 kan **kun** autoriseres med samme R2-approved SHA256, størrelse, kildecommit, candidate og reference som Viborg1-piloten.
- Regressionstest for både faser, negative varianter, historisk 1244 og checkout/release-retention.

## Read-only gates

```bash
python scripts/clientflow_1245_source_preflight.py --repo-root .
python scripts/clientflow_1245_pilot_policy_preflight.py --repo-root .
python scripts/clientflow_1245_r2_pilot_preflight.py --repo-root .
python scripts/clientflow_1245_unified_version_preflight.py --repo-root .
PYTHONPATH=backend:client/release/lib:. python -m pytest -q \
  scripts/tests/test_clientflow_1245_unified_version.py \
  backend/tests/test_clientflow_stable_rollout_policy.py \
  backend/tests/test_clientflow_1245_exact_single_client_pilot.py
sha256sum --check --strict SHA256SUMS.txt
```

## Release/beslutningsstatus

**Denne kildekandidat er ingen tilladelse til fysisk installation og ingen stable promotion.** GitHub CI og særskilt operatørbeslutning skal bestås før merge. Efter en kontrolleret backend-redeploy må ingen pilotoperatørflag aktiveres uden en ny, separat fysisk go/no-go. Ved første pilotfejl: stop bølgen, bevar logs og 1244-data, og følg den godkendte recovery-procedure – ikke ad hoc rollback.
