# PlanIQ Display – minimal dependency-sikkerhedsrettelse (2026-10-21)

## Baggrund

CI (på den igangværende Control Room genstartsbranch) fandt:

- `certifi==2026.7.22` – `PYSEC-2026-4320`, fixed i `2026.10.19`.
- `vite==8.1.4` – indirekte high advisories for dev-server/editor-integration; anvend sikkerhedspatchet `vite==8.1.6` indenfor samme minor-version.

## Ændringer

- `backend/requirements.txt`: eksplicit sikkerhedspin `certifi==2026.10.19`.
- Begge Python lockfiler: samme version med PyPI's verificerede SHA-256 for wheel og sdist.
- `frontend/package.json`, `frontend/package-lock.json`: `vite==8.1.6`. NPM SRI er verificeret mod flere uafhængige GitHub-låsefiler; Vite-dependency ranges (`postcss`, `rolldown`) er kontrolleret mod `vitejs/vite` tag `v8.1.6`. Nuværende låste transitive versioner opfylder disse ranges.
- `scripts/validate_dependency_contract.py` kræver fortsat eksakt Vite-version.
- Nye regresionstests verificerer begge hash-låste Python-grafer samt frontendens eksakte SRI, transitive versioner og tom audit-undtagelsesliste.

Der er **ikke** ændret i `npm audit`, `pip-audit`, undtagelseslisten, livestream, genstart eller ClientFlow-servicekode.

## Kilder (officielle)

- certifi sikkerhedsadvisory: https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2
- certifi 2026.10.19 wheel + sdist checksum: https://pypi.org/project/certifi/2026.10.19/
- Vite upstream 8.1.6: https://github.com/vitejs/vite/releases/tag/v8.1.6
- launch-editor: https://github.com/vitejs/launch-editor/security/advisories/GHSA-587h-7wmj-h5pm
- launch-editor: https://github.com/vitejs/launch-editor/security/advisories/GHSA-r825-w8mm-5pxw
- launch-editor: https://github.com/vitejs/launch-editor/security/advisories/GHSA-698v-4r3x-3vcv

## CI-gate

1. `python scripts/validate_dependency_contract.py`
2. `python -m pip_audit --disable-pip --no-deps --progress-spinner off -r backend/requirements.lock.txt`
3. `python -m pytest -q scripts/tests/test_dependency_security_20261021.py`
4. `cd frontend && npm ci && npm run audit:dependencies && npm run build`
5. **Hele** GitHub CI skal være grøn før merge; ingen audit-undtagelser.

Lokal CI-påstand: Kilde-/hash-/kontrakttests bestået. Netværksafhængig `npm ci`, pip-audit, frontend-build og integrationstest skal afgøres i GitHub CI.

Hvis denne PR merges, ændres repositoryets commitidentitet og ClientFlow 1.3.40 source-freeze skal ajourføres. Der må ikke publiceres med tidligere source-hash.
