# Upload til GitHub · Fase 63D-1

**Opret ny branch fra:** `main` ved kilde-SHA `88ce022c904ace9e0d21c914d509e563a17438e8`

**Branchnavn:** `feature/display-63d-release-readiness-safety-20261118`

Dette er en **sikker forberedelsesleverance**, ikke den endelige DB-cutover.

## Vigtigt
- Upload filerne fra denne ZIP med præcis samme relative stier.
- `.github/workflows/` og de kryptografiske 1245-R2-approval-/katalogfiler
  skal forblive uændrede.
- Merge kun efter fuld CI. Ingen aktivering af nye pilot-, fleet-, fresh-install
  eller DB-cutover-tilladelser ved merge.
- Frontend skal vise en særskilt readiness-matrix med STOP-gates under
  Administration → ClientFlow Releases.
- Backend og frontend kan redeployes uden at opdatere Viborg1.
- Forsøg **ikke** at køre 1.3.45/1246 som en godkendt release på baggrund af
  denne branch.

## Lokale målrettede tests

```
PYTHONPATH=backend python -m pytest -q \
  backend/tests/test_clientflow_release_readiness_63d.py \
  backend/tests/test_clientflow_release_admin_61a_source.py \
  backend/tests/test_clientflow_release_admin_61b_source.py
node --test frontend/tests/clientflowReleaseAdministrationUX.test.mjs
python scripts/clientflow_61b2g_release_source_gate.py --repo-root .
```

Yderligere GitHub CI, single-node smoke og migreringskontrol er den endelige gate.
