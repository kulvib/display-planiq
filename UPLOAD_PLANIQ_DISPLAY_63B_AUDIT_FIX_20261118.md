# PlanIQ Display · Fase 63B · Frontend dependency audit (18. november 2026)

## Placering
Upload **indholdet** fra denne ZIP til den **eksisterende** Fase 63B-featurebranch (ikke direkte til `main`). Behold mappestrukturen. ZIP'en er en **delta-pakke**, ikke et komplet repo. Upload den oprindelige Fase 63B-pakke først, hvis branchen endnu ikke indeholder den.

## Årsag
CI `npm run audit:dependencies` fandt fem high-poster: `picomatch` (GHSA-fc5q-39xc-vjpf), `fdir`, `tinyglobby`, `vite` og `@vitejs/plugin-react`. De sidste fire er npm-metafund, fordi buildværktøjerne arver sårbarheden i picomatch. GitHub Advisory Database angiver endnu **ingen officiel rettet picomatch-version** pr. 18. november 2026: https://github.com/advisories/GHSA-fc5q-39xc-vjpf

## Ændringer
- Fastholder den eksisterende, deterministiske `frontend/package-lock.json` uden fremmedgenererede integritetshashes.
- Tidsbegrænset, præcis undtagelse **kun** for `picomatch@4.0.5`, GHSA-fc5q-39xc-vjpf, `dev-only`, med automatisk udløb efter 25. november 2026.
- Ny fail-closed policy analyserer direkte advisories adskilt fra arvede npm-metafund; arvede pakker er kun accepteret, hvis *alle* årsager er præcist verificeret i dependency/peerDependency-grafen, og alle berørte pakker er development-only i npm-lockfilen.
- Ny, uafhængig Vite-sårbarhed, ukendt advisory-ID, ændret version, produktionsafhængighed, ugyldig auditrapport og udløbet undtagelse medfører fortsat FAIL.
- 14 målrettede nye Node-regressionstests samt tilpasset Python-security-regression; checksums genberegnet for alle ændrede og nye kildefiler.

## Kontrol i GitHub Actions
1. Kør **hele** CI på featurebranchen; ikke kun frontend audit.
2. Kontroller især `npm run audit:dependencies`, `node --test tests/*.test.mjs`, `python scripts/validate_dependency_contract.py`, source-checksum-gaten og frontend build.
3. Merge ikke til `main`, før alle påkrævede CI-checks er grønne. Render redeploy og smoke-test følger almindelig procedure.

## Forbehold
Lokalt kan npm-registry ikke tilgås, og det eksakte CI-miljø (Node 24.21.0/npm 11.19.0) er ikke tilgængeligt. Derfor er **den live npm-audit på GitHub ikke verificeret her**. De lokale tests validerer policyen med præcise syntetiske rapporter og fail-closed-forløb; de kan ikke erstatte GitHubs live-audit. Der er ingen ændring i produktionsfrontend, backend, database eller ClientFlow runtime.

## Efterbehandling
Undtagelsen skal fjernes, når en patchet picomatch-version findes, og inden den udløber. Opgrader Vite/plugin-react og regenerér npm-lock med godkendt npm-version; test bundling, performance og security gates samlet.
