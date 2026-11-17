# Uploadvejledning – PlanIQ Display fase 63

Opret branchen `feature/display-63-cost-performance-evidence-20261117` fra GitHub `main` på commit `759632d71fb9fd635285c06b756d2a89a74abc3d` (den friske repo-ZIP fra 13.31).

Upload de 6 filer i ZIP med deres **eksisterende mappestruktur**. Filerne er kun nye scripts/tests/dokumentation plus opdateret `SHA256SUMS.txt`; ingen ændringer i eksisterende runtime, CI-workflows, frontend, database eller klientruntime.

Kør ALLE GitHub CI-checks (inkl. Python Ruff, pytest og frontend build/bundle budget). Merge kun ved grønne krævede checks. Render auto-deployment kræver ingen separat manuel redeploy. Denne fase alene giver ingen dokumenteret driftsbesparelse, ingen faktisk 100-klient capacity proof og ingen godkendelse til at ændre pollingtider eller release-gates.

For at tage en sammenlignelig driftsmåling, følg `docs/PLANIQ_DISPLAY_63_COST_PERFORMANCE_BASELINE_20261117.md`. Rå logs kan indeholde personoplysninger og tokens; rapportscriptet kører offline og udskriver kun aggregerede tal. Gem ikke rå logs i GitHub/ChatGPT/CI-artefakter.

Ved CI-fejl: tilføj rettelser på samme branch og bevar alle tests. Det er ikke nødvendigt at oprette en ny branch for hver testrettelse.
