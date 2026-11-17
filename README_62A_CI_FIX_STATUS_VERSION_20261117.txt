PlanIQ Display 62A – CI-rettelse (Status-agent-fixture)
Dato: 2026-11-17
Branch: feature/display-62a-storage-readonly-release-preview-ux-20261117

Fejl: test_default_closed_status_and_draft_does_not_create_deployment
forventede reported_version/version_reported_at = None, men 62A-fixturen
indsætter nu gyldig og aktiv Status-agent status for Viborg1 med version 1.3.43.
Det forventede JSON er opdateret til den faktisk indlagte fixture.

Upload alene de to filer med deres stier:
  backend/tests/test_clientflow_release_admin_61a_http.py
  SHA256SUMS.txt

Dette er en ren testrettelse. Der er INGEN ændringer i produktionskode,
Status-agent, API, migrations, godkendelsesmodel eller installationsgates.
Kør fuld GitHub CI (herunder backendtest med sqlmodel) før merge.
Der må ikke udføres fysisk klientinstallation eller Render-deployment før CI er grøn.

Lokalt kontrolleret: Python AST, SHA256 641/641, ZIP-integritet.
HTTP-integrationstesten kræver sqlmodel og blev ikke kørt lokalt.
