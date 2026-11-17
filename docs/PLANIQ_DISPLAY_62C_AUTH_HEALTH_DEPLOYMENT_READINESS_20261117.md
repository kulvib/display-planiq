# PlanIQ Display 62C – samlet sessions-, health- og driftsberedskab

Baseline: frisk main-ZIP `display-planiq-main(20261117-113750).zip` (GitHub SHA `0df746e53fdec5beb439c6f8b06fa82341f2fbde`).

## Scope (én samlet, ikke-destruktiv kodeleverance)

- `HEAD /health` giver HTTP 200, uden databaseforespørgsel, for allerede installerede klienters HTTPS-kontrol. `GET /health/db` er fortsat Render readiness og må ikke forveksles med endpointet.
- Login, refresh og impersonation sender stabilt session-id (`sid`, random UUID4-hex) retur. Kun en sessionidentifikator – aldrig credential. ID følger eksisterende refresh-tokenfamilie; ved ny login eller impersonation fås korrekt ny binding. Refresh-cookie forbliver `HttpOnly` same-origin.
- Cross-tab aktivitet og logout accepteres kun for den aktuelle session med gyldigt sessions-id, kilde og frisk tidsstempel. En forsinket gammel logout-besked må ikke logge en ny session ud.
- Logout er bundet til signeret (eventuelt kortvarigt udløbet) bearer-token; en gammel fane kan ikke slette/revokere en nyere delt cookie. Cookie-only API-brug for eksisterende kompatible klienter bevares. Revocation commit fejler lukket med HTTP 503; backend må ikke sende falsk 200, og cookies slettes først efter commit.
- API-transport fornyer access-token tæt på udløb ved den **næste beskyttede request**, ikke på timer. Begge transportsystemer deler refresh single-flight og fortsat 401 -> refresh -> engangsretry. Kan reducere forventede `401` fra kalenderens `/api/calendar/season` og `/api/calendar/seasons`, men ægte ugyldig session giver fortsat 401.
- Frontendens boot håndterer midlertidig 5xx/netværksfejl som **utilgængelig** og viser ikke beskyttede sider; kun verificeret 401/403 behandles som ugyldig session. Retry-knap uden auto-gentagelse af login.
- Fysisk ClientFlow release, installationsgates, signerede artefakter, PostgreSQL-disk, schema og migrationsrevisioner ændres ikke.

## CI og releasekrav

- Kør fuld GitHub CI (backend, migrations, frontend lint/build, alle frontend source tests), og udfør regressionstests for logout-cookiefencing, backend rollback ved commit-fejl, HEAD /health, cross-tab late logout, udløbet token og kalender-401.
- Kontrollér i produktion: ved normal login, refresh, inaktivt logout og flere faner. Forvent 200 på HEAD /health fra allerede installeret klient; `GET /health/db` stadig 200; browserens Network skal vise ingen gentagne kalender-401 efter 15 minutters access-token levetid (bortset fra ægte auth-revocation).
- Test Render-deployment med risiko for HTTP 502 i begrænset vindue. Den eksisterende persistente disk gør zero-downtime-deployment urealistisk i denne arkitektur; 62C ændrer **håndtering og symptom**, ikke availability-garantien.
- Den samlede 62B kode er en syntetisk CI-backup/restore plus operatørstyret værktøj; det er **ikke** et bevis på recovery af produktionsdatabasen. Ingen migration før en rigtig, krypteret ekstern backup og isoleret recoverytest er godkendt.

## Kriterier for fremtidig datamigration (IKKE udført her)

1. Vælg eksternt PostgreSQL og objektlager, og beregn omkostning, responstid, overførsel og ændringsrisiko for >=100 kiosker. Overvej også single-node med vedligeholdelsesvindue som alternativ.
2. Frisk krypteret produktionsbackup med signeret/integritetskontrolleret manifest og adskilt opbevaring. Isoleret restore med et godkendt, anonymiseret kontrolgrundlag, dokumenteret RPO/RTO.
3. Gennemgå alle nuværende releasepakker inklusive mindst tre historiske rollback-kandidater, SHA256 og ikke-destruktiv kopiering; produktionsdata og signeringsnøgler må ikke logges.
4. Separat pilotdeployment, cutover/rollback-gate og godkendelse. Ingen implicit aktivering af ClientFlow fresh install/fleet/pilot/DB-cutover.

## Kendt begrænsning

Hvis Render er helt nede på det tidspunkt, hvor et menneske logger ud, kan frontend kun afslutte sin lokale session. Backend-kvittering 503 giver ingen sikker server-revocation. Det kræver særskilt tilgængelighed/operatørhåndtering, før man kan love bekræftet server-logout under et totalt outage. En gammel fane må aldrig få lov at slette en ny sessions cookie som nødløsning.
