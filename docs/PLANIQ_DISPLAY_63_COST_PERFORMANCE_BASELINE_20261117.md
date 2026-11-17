# PlanIQ Display · Fase 63 · Lav driftspris uden langsommere backend/frontend

**Dato:** 17. november 2026. **Kilde:** frisk `display-planiq-main(20261117-133139).zip`, GitHub `main` `759632d71fb9fd635285c06b756d2a89a74abc3d`. Dette er en ikke-destruktiv, målingsorienteret fase uden ny infrastruktur.

## Arkitekturbeslutning

Vi bevarer den aktive Render-webservice, dens lokale PostgreSQL 18 og det persistente ClientFlow-release-lager. **Viborg1 er en testklient.** Midlertidig nedetid og tab af almindelige testdata er acceptabelt, men administratoradgange, credential-hemmeligheder, signeringsnøgler, tidligere signerede releasebytes og lukkede rollout-/fresh-install-gates må ikke ændres af denne fase.

Der oprettes **ingen** Neon-/Render-databaser, objektlagre, crons, ekstra services, aktører, tokens eller automatisk datamigration. `render.yaml` er ikke en pålidelig repræsentation af den allerede kørende single-node-service.

## Faktisk fund i den friske kode

1. Status-, display- og system-agenters **presence** bruger signerede wake-tokens og en proceslokal livenessstruktur; intet databasekald eller databasewrite pr. pulse. Status/checkpoints og de nødvendige autoritative kontroller bevares.
2. Delte command-waits er async og proceslokale; de ligger ikke og holder en SQL-connection under long-poll.
3. Databaseinstrumentering tæller statements/checkouts og logfører faste 15-minutters hotpath-kategorier uden SQL-tekst, parametre eller klientidentitet. Den må ikke deaktiveres for at spare omkostninger.
4. Render readiness bruger `GET /health/db`, som verificerer DB og Alembic revision; installeret klient bruger `HEAD /health` uden database. Denne adskillelse bevares.
5. Livestream presence bruger en autoritativ databasekontrol ved hver livenesspuls; **det er et bevidst revocation/sikkerhedsvalg**, som ikke skal fjernes uden sikkerhedsmodel, test og målebevis.
6. Frontend har allerede `scripts/checkBundleBudget.mjs` indbygget i `npm run build`. Fase 63 sammenholder desuden de byggede JS/CSS/HTML-bytes; dette er **ikke** en måling af browserens indlæsningstid.

**Observeret, ikke endnu bevist:** Tidligere Render-log viste en testklients `HEAD /health` omkring hvert 10. sekund og mange status-/presence-kald. Det beviser hverken fuld døgntrafik, databasens CPU/RAM, billingsatsen eller 100 samtidige klienters ydeevne. Vi ændrer derfor ikke pollingperioder eller DB-poolstørrelser endnu.

## Fase 63 · Én samlet rapport- og regressionstoolchain

`python3 scripts/display_63_cost_performance_baseline.py --input-file /secure/local/render-request-logs.ndjson`

Understøttede kilder: en lokal Render JSON-export (`{"logs": [...]}` eller array), NDJSON med Render-labels, eller timestampede Uvicorn HTTP-linjer. Output er en JSON-rapport på stdout, som kan gemmes til en lokal fil. **Inddata** kan indeholde IP-adresser, klient-id'er, user agent, URL-parametre og request-ID'er; brug derfor lokale, adgangsbegrænsede inputfiler. **Output** indeholder kun faste endpoint-kategorier, antal, HTTP-fejl, målte p50/p95-svartider, antal observerede klient-ID'er og simple scenarier.

Eksempel (fra repoets rod, i et sikkert, privat arbejdskatalog):

```bash
python3 scripts/display_63_cost_performance_baseline.py \
  --input-file /secure/local/render-before.ndjson \
  > /secure/local/63-before.json

# Når frontend/build har oprettet dist, kan den eksisterende byggestørrelse også inkluderes:
python3 scripts/display_63_cost_performance_baseline.py \
  --input-file /secure/local/render-after.ndjson \
  --frontend-dist frontend/dist \
  > /secure/local/63-after.json

python3 scripts/display_63_compare_baselines.py \
  --before /secure/local/63-before.json \
  --after /secure/local/63-after.json \
  --fail-on-indicator
```

`--fail-on-indicator` returnerer 1 ved observeret regression, 2 ved ugyldigt input og ellers 0. **Returkode 0 er ikke et bevis for uændret performance**, især ikke ved korte eller ikke-sammenlignelige logudsnit.

### Forudsætninger for brugbare målinger

- Indsaml sammenlignelige tidsvinduer **før og efter** den samme type belastning; mindst 30 minutters observation anbefales, gerne hele dage, og tilstrækkelig p95-stikprøve pr. kategori.
- Inkludér både HTTP-request logs og relevante `db_hotpath_summary` app-logs. Uden sidste del kan scriptet ikke henføre SQL-statementantal til agentkategorier. I rapporten markeres manglende data; der gættes ikke et databaseforbrug.
- Sammenhold Render CPU, RAM, disk, abonnementspris og faktisk 502/503-hyppighed separat i Render. Tilsvarende frontend-browsertest for faktisk LCP/INP og caching efter deployment.
- **1, 10, 50 og 100-klienttal er kun lineære trafikscenarier.** De inkluderer ikke køeffekter, låse, indbyrdes samtidighed, WebSocket-tryk, videotransport, databasepoolens mætning eller Render-fakturering. De er aldrig "100 klienter bestået".
- Udfør en særskilt isoleret belastningstest på synthetic test-clients, før en samlet 100-klienters skalering kan godkendes. Brug ikke 100 ekstra klient-login eller stress på den kørende Render-instans uden en aftalt prøve.

### Regressionstærskler – indikatorer, ikke autorisationsgates

- p95: højere end både **+15 %** og **+10 ms**, på kategorier med mindst 20 tidsmålte requests i hver sammenlignelig periode.
- 5xx-andel: stigning på mere end **2 procentpoint** og **1,5×** i samme kategori.
- Kald pr. klient pr. time: over **+20 %**, normaliseret efter observerede unikke klient-ID'er og varighed.
- Komprimeret JS/CSS: over **+5 %** i det byggede output.
- For requests/latens skal de to vinduer være mindst 30 minutter; manglende data rapporteres eksplicit. Sammenligningsrapporten indeholder hverken rå URL'er, IP'er eller klientidentiteter.

## Økonomisk prioriteret beslutningsmatrix

| Kandidat | Mulig gevinst | Risiko for lavere hastighed eller funktionalitet | Beslutning i denne fase |
|---|---|---|---|
| Reducér unødige status-writes, hvis de kan påvises | Færre writes / DB-CPU | Forsinket status; fejl i revisions- og command-flow | Ingen ændring uden dokumentation |
| Tuning af SQL-pool/queries efter p95 og checkout-count | Mindre pooltryk og latens | Timeout/revocation/lock-konkurrence | Mål først |
| Dæmp polling på skjulte admin-sider | Færre HTTP-kald | Forsinkede live-statusser og fejl i kontrolrum | Mål og design først |
| Reducér `HEAD /health` interval | Færre netværkskald | Langsommere offline-/internetdetektion | **Ikke tilladt** uden lige hurtig alternativ detektion |
| Fjern livestream revocation-kontrol | Færre DB-reads | Uautoriseret adgang kan fortsætte | **Ikke tilladt** |
| Indfør Neon/objektlager/ekstra Render-service | Eventuelt anden driftstopologi | Ekstra omkostning og kompleksitet | **Ikke nu** |
| Bundle-size- og render-p95 før/efter-regression | Objektivt stop ved forringelse | Ingen runtime-omkostninger | **Indført i 63** |

## Accept og afgrænsninger

Denne fase ændrer **ikke** runtime, produktion, data, skema, auth/MFA, releasekatalog, signering, client factory, rollout flags, Render-miljøvariabler eller eksisterende readiness. Den tilføjer alene to standardbiblioteksbaserede, offline analyseskipter og fuldt dækkende regressionstests. Ingen ekstra API-kald eller databaseforbindelser fra denne fase.

CI skal fortsat omfatte eksisterende Python/JS-tests, frontend build/bundle budget, PyJWT- og dependency-audits, Postgres18-isoleret restore samt sikkerheds-/release-gates. Først med en sammenlignelig, sanitiseret baseline kan vi beslutte og implementere optimeringer i endnu en **stor, sammenhængende kodebatch** – uden spekulative ændringer, der giver langsommere system.
