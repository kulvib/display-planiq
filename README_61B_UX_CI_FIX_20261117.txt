PlanIQ Display – samlet CI-rettelse – 17. november 2026

Base: original branch-pakke planiq-display-clientflow-release-ux-login-502-safe-20261117.zip
Branch: feature/display-release-admin-ux-login-502-20261117

FILER
- frontend/src/pages/adminpages/ClientFlowReleaseAdministration.jsx
- backend/tests/test_clientflow_release_admin_61a_http.py
- SHA256SUMS.txt

Rettelser
1. Stabil EMPTY_CLIENTS-konstant i ClientFlowReleaseAdministration. React useMemo-dependencies får ikke et nyt fallback-array på hver render. Ingen ændring i releasehandlinger eller klientvalg.
2. HTTP-testens fiktive organisationsnavn ændret fra et udfaset produktnavn til "PlanIQ Testorganisation" i både fixture og assertion. Samme testning og sikkerhedskontrol.
3. SHA256SUMS.txt opdateret for kun de to ændrede filer, øvrige poster uændrede.

KONTROLLER
- node --test frontend/tests/clientflowReleaseAdministrationUX.test.mjs frontend/tests/maintenanceGatewayAvailability.test.mjs : 6 PASS
- PYTHONPATH=backend python -m pytest -q scripts/tests/test_display_branding_identity.py : 3 PASS (lokalt git-indeks oprettet alene til testen)
- PYTHONPATH=backend python -m pytest -q backend/tests/test_clientflow_release_admin_61a_source.py backend/tests/test_clientflow_release_admin_61b_source.py : se lokal rapport
- sha256sum -c SHA256SUMS.txt : 636/636 PASS
- Fuld npm run lint, fuld CI og backend HTTP-integration skal fortsat udføres på GitHub (låst Node 24/npm 11 + backendafhængigheder ikke installeret her).

ANVENDELSE
Upload de tre filer til samme eksisterende branch oven på den oprindelige 13-filers ændring. Opdater ikke main eller Render før CI er fuldt grøn. Bevar alle release- og klientgates lukkede. Ingen produktionskald, opdateringer eller DB-migrationer.
