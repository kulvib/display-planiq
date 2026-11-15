PlanIQ Display – rettelse af CI-schemafejl for migration 61a

Kilde: kulvib/display-planiq
Branch: feature/clientflow-release-admin-db-foundation-61a-20261115
Fil: backend/service1/clientflow_release_admin_models.py

Denne ZIP indeholder KUN den rettede fil, ikke hele repositoryet.

Rettelse:
- Tilføj max_length=36 til ClientFlowRolloutTarget.consumed_deployment_id.
- Matcher den eksisterende migration 61a og skemakontrakt VARCHAR(36).
- Ingen andre kodeændringer, databasemigrationer eller konfigurationsændringer.

Sådan anvendes filen:
1. Pak ZIP'en ud.
2. Gå til den nævnte branch i GitHub.
3. Udskift backend/service1/clientflow_release_admin_models.py med filen herfra.
4. Commit ændringen til branchen, og lad GitHub Actions køre alle CI-tests.
5. Merge/deploy først, når alle obligatoriske kontroller er grønne.

Kontrol: Python-syntaks er kompileret lokalt; hele projektets CI er ikke kørt lokalt.
