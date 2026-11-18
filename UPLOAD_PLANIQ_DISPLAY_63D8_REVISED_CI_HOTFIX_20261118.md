# PlanIQ Display · Fase 63D-8 revideret · CI-hotfix · 18. november 2026

**Målbranch:** `feature/display-63d8-revised-media-hotpath-deployment-status-20261118`

Dette er en **komplet erstatning for ZIP-pakken til den reviderede Fase 63D-8**. Upload filerne med bevaret stistruktur til **samme eksisterende branch**, ikke `main`. Den gamle og forkastede `feature/display-63d8-deployment-status-media-balance-20261118` må ikke bruges.

## Hvad er rettet?

1. `RemoteDesktop.jsx`: Den eksisterende `connect`-callback erklærer nu begge anvendte, stabile hook-afhængigheder (`framePainter` og `paintLatestFrame`). Ingen ESLint-undtagelse eller deaktivering af `react-hooks/exhaustive-deps`.
2. `test_clientflow_release_admin_61a_http.py`: Den isolerede SQLite-testfixture opretter også den **eksisterende** `clientflow_deployment`-tabel, som den nye, begrænsede og skrivebeskyttede historik læser. Produktionsskema og API-sikkerhedspolitik ændres ikke.
3. `remote_desktop_v2.py`: Videresendte JPEG-frames får altid browser-sessionens validerede geometri. Ugyldige værdier fra agenten kan ikke længere fastholdes af `dict.setdefault()` efter det enlige, begrænsede opslag.
4. Regressionstests verificerer, at fallback-geometrien bruges konsekvent, at senere ugyldige frames ikke overskriver tidligere gyldig opløsning, og at en tom deploymenthistorik forbliver en tom liste i administrator-API'et.
5. `SHA256SUMS.txt` opdateres og verificeres på tværs af hele kildepakken.

## Lokale kontroller

- Python-kildekontrakter: 4 bestået.
- Node-test for bounded frame painting, HTTPS-fallback/inputrækkefølge og historik: 12 bestået.
- Python-syntaks/manifest/ZIP-integritet: gennemføres før udlevering.
- **GitHub CI er endelig gate**: SQLModel/PostgreSQL-integration og fuld ESLint-kørsel kunne ikke afvikles lokalt på dette miljø uden alle projektafhaengigheder.

## Uændrede gates

- Ingen ændringer i Render Environment eller Neon-skema.
- Ingen nye pollere, databasekald i remote-frame-hotpath eller udrulningsrettigheder.
- Ingen ændringer af ClientFlow 1.3.45/1246 eller release-artifacts.
- 1246 forbliver fysisk pilot; rollback og fleet-udrulning er fortsat spærret.

**Vigtigt:** Merge og Render-redeploy først når **alle GitHub CI-checks er grønne**.
