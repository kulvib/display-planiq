# Fase 63B – branch-upload fra frisk main 17. november 2026 kl. 16:47

**Branchforslag:** `feature/display-63b-db-hotpath-evidence-20261117`

**Autoritativ kilde:** `display-planiq-main(20261117-164729).zip` fra brugeren. Opret branchen fra GitHub `main` svarende til denne kilde; bekræft, at main ikke har ændret sig før upload. Ingen Git commit-ID er indeholdt i den uploadede ZIP, og denne fil opfinder ikke et.

Upload kun filerne i den medfølgende ændrings-ZIP med bevaret relativ mappestruktur:

- `scripts/display_63_cost_performance_baseline.py` (ændret)
- `scripts/display_63_compare_baselines.py` (ændret)
- `scripts/display_63b_hotpath_priorities.py` (ny)
- `scripts/tests/test_display_63_compare_baselines.py` (ændret eksisterende assertion)
- `scripts/tests/test_display_63b_hotpath_cost_comparison.py` (ny)
- `scripts/tests/test_display_63b_hotpath_priorities.py` (ny)
- `docs/PLANIQ_DISPLAY_63B_DB_HOTPATH_DECISION_GATE_20261117.md` (ny)
- `UPLOAD_PLANIQ_DISPLAY_63B_20261117.md` (ny)
- `SHA256SUMS.txt` (opdateret for disse filer)

Dette er **ikke** en ClientFlow-runtime-release. Ingen ændring i klientruntime, Release 1.3.43/1244, signeringsnøgler, DB-skema, frontend, Render eller auth.

## Validering

Den målrettede lokale pytest-testgruppe består af Fase 63 baseline/compare, Fase 63B DB-hotpath regression/priorities, eksisterende DB telemetry og frontend-observability-kontrakter.

```bash
python3 -m pytest -q \
  scripts/tests/test_display_63_cost_performance_baseline.py \
  scripts/tests/test_display_63_compare_baselines.py \
  scripts/tests/test_display_63b_hotpath_cost_comparison.py \
  scripts/tests/test_display_63b_hotpath_priorities.py \
  backend/tests/test_db_hotpath_telemetry.py \
  backend/tests/test_clientflow_performance_observability_source.py
python3 -m compileall -q scripts/display_63_cost_performance_baseline.py \
  scripts/display_63_compare_baselines.py scripts/display_63b_hotpath_priorities.py \
  scripts/tests/test_display_63b_hotpath_cost_comparison.py \
  scripts/tests/test_display_63b_hotpath_priorities.py
```

Kør som sædvanlig **alle** GitHub CI-checks. Lokalmiljøet for denne ZIP havde ikke alle komplette backend-/frontend-testdependencies (bl.a. `sqlmodel` og `ruff`); derfor erstatter de lokale tests ikke CI. Merge først ved grønne required checks. Ingen måling af faktiske Render-requestlogs er inkluderet i patchen, og ingen besparelse er påstået.
