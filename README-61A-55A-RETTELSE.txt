PlanIQ Display - rettelse af CI-fejl i 55A source-kontrakttest (15-11-2026)

Kilde: Brugers vedhaeftede branch-ZIP: display-planiq-feature-clientflow-release-admin-db-foundation-61a-20261115.zip,
med tidligere 61A CI-rettelser fra samtalen anvendt.
Branch: feature/clientflow-release-admin-db-foundation-61a-20261115

Ændringer:
- scripts/tests/test_clientflow_code_only_fresh_install.py
- SHA256SUMS.txt

Fejl: source-kontrakttesten forventede head -> 59A, men migrationsrunneren
håndhæver den aktuelle kæde 58A -> 59A -> 60A -> 61A.
Testen kontrollerer nu begge efterfølgende overgange: 59A -> 60A og 60A -> 61A.
Manifestet opdateres kun for ovenstående testfil. Alle 583 hashposter er kontrolleret.

Pak ZIP ud og kopiér filerne til tilsvarende stier på den navngivne branch.
Bevar tidligere CI-rettelser. Kør fuld GitHub CI før merge til main/Render.
Fuld CI er ikke kørt her: de låste Python-afhængigheder mangler lokalt.
