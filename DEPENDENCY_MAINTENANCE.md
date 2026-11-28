# Dependency- og runtimevedligeholdelse – PlanIQ Display

## Fastlåste runtimes

- Backend/CI Python: `3.13.16`
- Node.js: `24.21.0` LTS
- npm: `11.19.0`
- ClientFlow 1.3.30/1231 embedded runtime Python: `3.13.14` (compatibility boundary; intentionally unchanged until an authentic physical in-place runtime bridge is proven)
- pip i Render/CI: `26.1.2`

Render, GitHub Actions, `backend/.python-version`, `frontend/package.json` og lockfilerne skal ændres samlet for backend/frontend toolchains.

ClientFlow release-artifact production is a separate compatibility boundary. The 1.3.30/1231 release line remains on embedded Python `3.13.14` until an authentic physical in-place runtime bridge has been proven; the general backend/CI runtime does not share that freeze. Both backend and embedded-runtime PyJWT remain pinned to `2.15.1`. The deterministic Python `3.13.15` embedded-runtime candidate remains historical/candidate evidence and is not adopted by 1.3.30/1231.

## Python

`backend/requirements.txt` indeholder eksakte direkte produktionsafhængigheder. `backend/requirements.lock.txt` og `requirements-ci.lock.txt` indeholder den fulde resolverede graf med SHA-256-hashes.
Backendens `cryptography`-pin er `50.0.2`; lockfilerne indeholder kun godkendte SHA-256-hashes for den resolverede artifact-kæde.

Installation og kontrol:

```bash
python -m pip install --upgrade pip==26.1.2
python -m pip install --require-hashes -r requirements-ci.lock.txt
python -m pip check
python -m pip_audit --disable-pip --no-deps --progress-spinner off -r backend/requirements.lock.txt
python scripts/validate_dependency_contract.py
python -m pytest -q backend/tests scripts/tests
```

Lockfiler skal genereres fra rene Python 3.13-miljøer og må ikke indeholde interne index-URL'er eller credentials.

## ClientFlow release-build toolchain

Release artifact production has its own narrower deterministic toolchain contract in `client/release/release-build-toolchain.json`. The canonical workflow pins Python `3.13.14`, pip `26.1.2`, and setuptools `83.0.0`; the setuptools wheel is installed with hashes from `client/release/release-build-requirements.lock.txt`. `client/runtime/pyproject.toml` must declare the same setuptools build backend version.

Changing this toolchain is a release-format/build-input change: update the toolchain contract, hash lock, pyproject build requirement and release-build tests together, then prove two-runner byte-for-byte reproducibility before approving a candidate.

## Frontend

`npm ci` er den eneste installation i CI og Render. `frontend/package-lock.json` er source of truth.

```bash
cd frontend
npm ci
npm run audit:dependencies
npm run test:dependency-runtime
npm run lint
npm run test:api-error
npm run test:remote-desktop-urls
npm run build
```

Audit-undtagelser skal være specifikke, tidsbegrænsede og dokumenterede i `frontend/dependency-audit-allowlist.json`. Nye eller udløbne advisories blokerer CI.

Status 2026-10-14: Den sidste midlertidige `brace-expansion` 1.1.21-undtagelse er fjernet efter at GitHub CI (`npm audit`) rapporterede **0 sårbarheder / 0 undtagelser**. De tre dokumenterede GitHub-advisories (`GHSA-q2hr-2g5m-vwhr`, `GHSA-qhr7-859c-m2p7`, `GHSA-6j4f-fj2g-mc7p`) angiver alle den låste version 1.1.21 som rettet. `npm audit` kører uændret og må ikke omgås; nye advisories skal behandles som fejl indtil separat verificeret.


## Produktspecifik status

Display bevarer HLS-, WebSocket-, ClientFlow- og Remote Desktop-afhængighederne. Dependency-opdateringer må ikke kombineres med produktændringer.

For ClientFlow 1.3.30/1231 er `hls.js` eksplicit release-fastlåst til `1.6.16`, som allerede er den resolverede og testede runtime-version i lockfilen. Den må ikke løftes som del af den sidste pre-freeze closure. Nyere HLS.js skal vurderes særskilt efter 1.3.30 med den fysiske Livestream-regressionssuite og målte startup/reconnect/live-edge-resultater, før en ny version kan accepteres. Dette er en release-risiko-disposition, ikke en security-undtagelse.

## Midlertidig spærring i upstream: picomatch GHSA-fc5q-39xc-vjpf (18. november 2026)

GitHubs gennemgåede advisory (opdateret 17. november 2026) markerer **picomatch <=4.0.7** som påvirket af ReDoS og oplyser **ingen patchet version**. PlanIQ Display har picomatch 4.0.5 **udelukkende i frontendens development/build-kæde**, transitivt via Vite/tinyglobby/fdir. Disse pakker leveres ikke til browserens produktionsbundle eller backendens Python-runtime. Advisory: https://github.com/advisories/GHSA-fc5q-39xc-vjpf

Kun den eksakte GHSA, den eksakte låste version `picomatch@4.0.5` og `dev-only` er accepteret frem til og med **2026-11-25**. Metafund på `fdir`, `tinyglobby`, `vite` og `@vitejs/plugin-react` accepteres *kun*, hvis hver eneste arvede afhængighed faktisk peger på dette ene accepterede fund, og alle trin er dokumenteret i `package-lock.json` som `dev=true`. Der findes **ingen generel Vite-undtagelse**. Enhver direkte Vite-advisory, ny GHSA, ekstra årsag, ulåst version, ændret produktionsscope, overskredet dato, ukendt ID eller manglende auditrapport medfører CI FAIL. `npm audit --json` kører uændret.

Remediation: Ved første officielle patched picomatch-udgivelse regenereres den eksakte npm-lock (under pinnen Node 24.21.0 / npm 11.19.0), der køres den komplette CI- og build-gate, undtagelsen fjernes, og dev-dependencies gennemgås samlet. Dette er en begrænset, risikovurderet beslutning for at holde CI operationel, ikke en erklæring om, at sårbarheden er løst. Indtil da bør Vites udviklingsserver kun bruges lokalt, og der må ikke accepteres brugerleverede glob-mønstre i buildværktøjerne.

## Lukket: picomatch GHSA-fc5q-39xc-vjpf (26. november 2026)

Den ovenstående disposition er historisk. GitHub trak advisoryen officielt tilbage 18. november 2026, fordi forholdet ikke længere klassificeres som et sikkerhedsproblem (opdateret 19. november): https://github.com/advisories/GHSA-fc5q-39xc-vjpf. CI 45790259057 rapporterede 0 sårbarheder under npm ci, men den tidligere undtagelse udløb 25. november og blokerede begge dependency-gates. Den aktive allowlist er nu tom; den særlige dormant-waiver er fjernet. Der er ikke tale om en ny patchet picomatch-version: package.json og package-lock.json er uændrede. Nye eller genindførte advisories, udløbne undtagelser og mangelfulde auditrapporter blokerer fortsat CI. Den fulde npm audit og regression skal bestå før merge. Fortsat kun betroede glob-mønstre i buildværktøjer.

## Afsluttet engangsopgradering (68N-C3)

Den tidligere `.github/workflows/dependency-maintenance-candidate.yml` var en specifik, allerede gennemført versionsmigration, ikke en generel løbende opdateringsmekanisme. Workflowet pensioneres. Nye opdateringer skal fortsat ske i en isoleret kandidat med eksplicit gennemgåede versionsmål, hash-fastlåste lockfiler, dependency-kontrakt, sikkerhedsaudit og fuld CI før merge. Hvis en ny opskrift genintroduceres under samme filnavn, kontrolleres dens Python-toolchain fortsat. Produktionens read-only smoke-test og alle faste dependency-gates bevares.
