PlanIQ Display 61a – CI-fix for Starlette TestClient / httpx2
Kilde: Den uploadede ZIP display-planiq-feature-clientflow-release-admin-db-foundation-61a-20261115.zip
Branch: feature/clientflow-release-admin-db-foundation-61a-20261115

ÆNDRET FIL:
backend/tests/test_clientflow_release_admin_61a_http.py

FEJLÅRSAG:
Testfilen importerede fastapi.testclient.TestClient. Repositoryets låste
CI-afhængigheder indeholder ikke pakken httpx2, som den valgte Starlette-version
kræver ved import af testklienten.

RETTELSE:
Erstat Starlette/FastAPI TestClient i denne ene test med samme dependency-frie
in-process ASGI-mønster, som allerede findes i:
  backend/tests/test_clientflow_operational_http_integration.py

De oprindelige fire 61a HTTP-tests er bevaret. Ingen produktionskilde,
migrationer, databasekontrakter, testudeladelser, afhængighedsfiler
eller CI-workflows er ændret.

INSTALLATION:
1. Pak denne ZIP ud.
2. Upload/erstat backend/tests/test_clientflow_release_admin_61a_http.py
   på ovenstående feature-branch med samme mappestruktur.
3. Kør branchens fulde GitHub CI. Vent med merge og deployment til alle gates er grønne.

UDFØRTE KONTROLLER:
- Python-syntakskontrol af rettet testfil: BESTÅET
- Repoets validate_dependency_contract.py: BESTÅET
- Isoleret FastAPI/ASGI-smoketest: GET 200, POST 201, GET 404, POST 422: BESTÅET
- Kontrol: fire eksisterende 61a tests bevaret og max_length=36-fix stadig i source: BESTÅET
- Komplet 61a-test-suite/GitHub CI: IKKE KØRT. Korrekt versionslåst testmiljø
  kunne ikke installeres lokalt pga. manglende netværks-/pakkeadgang.
