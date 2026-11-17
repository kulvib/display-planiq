# PlanIQ Display – ClientFlow Releases UX + login/502-håndtering, 17. november 2026

## Godkendt baseline og afgrænsning

Kilde: `display-planiq-main(20261117-095043).zip` (GitHub main `45e39d14801872db97af18c168ba0adb3d0ee3f7`). Dette er kun en ny UI/API-læsekontrakt for **inaktiv planlægning** plus frontend-fejlhåndtering. Ingen ændringer i produktionsgates, signed releases, 1.3.44/1245 godkendelsesgrundlag, 1.3.45/1246-kandidat, migrations, installation, rollout eller rollback. Ingen nye plan-state transitions.

## 1. ClientFlow Releases, best-practice for de nuværende tilladelser

- Vis stabil release fra den låste DB/katalogautoritet. **Ingen versioner skal skrives manuelt.** Kun den ene faktisk godkendte 1.3.44/1245 kan vises som klar release; usignerede kandidater vises ikke som valgbare.
- Vis kun aktive/godkendte, ikke-slettede klienter. Serveren svarer med et begrænset inventory (id, navn, placering, organisationsnavn, senest rapporteret versionsnummer og rapporteringstid), uden loginoplysninger eller klienthemmeligheder. Ét eksplicit GET og ingen baggrundspolling.
- Vælg kildeversionsgruppe, filtrer organisation og klientnavn, afkryds én eller op til 25 enheder. Klienter med ukendt version eller nyere version end målrelease kan ikke planlægges som opdateringsklienter. Dette er en planoplysning, ikke fysisk verifikation.
- Pilot vs kontrolleret bølge bestemmes ud fra antal (1 eller flere); Type-dropdown er fjernet. Begrundelse er ikke længere et fritekstfelt på planformularen, men en **automatisk audittekst** oprettes stadig og håndhæves fortsat af backend. Reelle deployments beholder eksplicit auditbegrundelse i deres eksisterende særskilte flow.
- Adgangskodebekræftelse i modal før både kladdeoprettelse og alle planændringer. Revision-check, RBAC, rate-limit og audit bevares. Planen er altid inaktiv og skaber ingen deploymentautorisation.
- Udrulning, nyinstallation og rollback vises som **spærrede fremtidige handlinger**. Disse fungerer IKKE fra den nye side endnu. Separat signering, godkendelse, fysisk pilot, gate-policy og implementering kræves før det kan åbnes; bulk-udrulning er ikke en sideeffekt af dette PR.
- Inventory er begrænset til 1000 klienter; over grænsen returnerer serveren `client_inventory_complete: false`, og UI fejler lukket. Minimums-skalamål på 100 klienter understøttes.

## 2. Login efter automatisk logout / Render 502 / CORS

- Status GET ændret fra cross-origin til same-origin `/api/maintenance/status`, gennem eksisterende frontend `render.yaml` rewrite. Browseren vil dermed ikke fortolke en Render-proxygenereret 502 som cross-origin CORS fejl. En 502 kan fortsat opstå og bliver korrekt behandlet som backend/transportutilgængelighed.
- På fejl må vedligeholdelses-gaten ikke fortsætte ud fra en gammel `enabled=false`-status. Den fejler lukket, giver en menneskelig fejlbesked og automatisk begrænset retry med 5–60 sekunder backoff. Normalt 15s polling ved aktiv maintenance deaktiveres, mens der er fejl.
- Login skelner 5xx fra 401/403. 5xx vises som midlertidigt utilgængelig backend og må ikke rapporteres som forkert password eller automatisk gensende login/password (risiko for lockout). HttpOnly first-party auth rewrite `/api/auth/*` forbliver uændret.
- Bemærk: `502` fra Render edge/proxy kan ikke repareres med applikationens CORS headers. Kontrollér upstream-health, proxy-tilgængelighed, deploy-event og gateway-status. Backend `CORSMiddleware` findes allerede for egentlige API-svar. Gentagne redeploys af en enkelt backendinstans kan midlertidigt give 502; dette skal måles i produktion, ikke antages løst af UI.

## Verifikation og STOP-gates

- Lokalt: målrettede frontendtests + 6 backend sourcekontrakttests bestået. In-process HTTP-test kræver `sqlmodel` og er ikke udført lokalt. Frontend-fuld suite kræver låst Node 24.21.0, npm 11.19.0 og `npm ci`: ikke installerbart offline i denne sandbox. Løb ikke uden om CI.
- GitHub: alle CI-jobs inklusive backend HTTP, frontend build og Render smoke skal bestå, før merge/deploy.
- Efter deploy: (1) release-siden viser kun 1.3.44 stabil; (2) søg/filtrer/marker en eller flere reelle klienter, uden at bestille installation; (3) kladde/historik og audit; (4) 401/403 og 502 vises korrekt; (5) efter autologout ses ingen misvisende CORS på maintenance status; (6) det faktiske `/api/auth/token` og `/health/db` må svare, samt Render-loggen uden vedvarende 502; (7) alle pilot/fleet/fresh-install/cutover gates stadig lukkede.

**Ingen fysisk klientopdatering, release-promovering eller ændringer af miljøvariabler er en del af pakken.**
