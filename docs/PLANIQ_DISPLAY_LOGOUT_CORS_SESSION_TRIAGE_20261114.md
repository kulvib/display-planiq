# PlanIQ Display: automatisk logout, CORS og API-livscyklus

## Reproduceret symptom (konsollog, 14. november 2026)

- Ved sessionudløb ser administratoren gentagne HTTP 401 på kalender og HLS-media health.
- `/api/maintenance/status` sender request-header `Cache-Control: no-store` og udløser browserpreflight.
- `/health` er et simpelt GET uden brugerheaders og får alligevel manglende `Access-Control-Allow-Origin` i den observerede fejl.

## Afgrænset patch

1. Maintenance GET beholder browserens `cache: no-store` samt serverens `Cache-Control: no-store`, men undgår en ekstra, unødvendig CORS-preflight. Statuskontrollen er stadig offentlig, fail-closed og anvender eksisterende maintenance-gate.
2. Beskyttede API-requests bruger både komponentens AbortSignal og login-sessionens AbortSignal. Sessionen afsluttes ved logout: in-flight fetch annulleres, og nye kald uden token afvises lokalt med `AbortError`. Ingen ændring af tokenvarighed, serverauth eller 401-autoritet.
3. Den centrale API-klient får samme session-binding og respekterer fortsat caller-signal og refreshpolitik.

## Ikke løst eller dokumenteret endnu

En `/health`-respons uden CORS-header kan stamme fra CDN, reverse proxy, timeout eller en HTTP-fejl inden FastAPI. FastAPI har allerede `https://display.planiq.dk` i sin allowliste. Vi har ikke kunnet observere den faktiske respons på det konkrete tidspunkt. Derfor ændres ikke CORS allowliste, auth-cookie eller infrastructure-routing uden evidens.

## Skrivebeskyttet diagnose ved næste forekomst – fra lokal Mac (ingen credentials)

```bash
curl --silent --show-error --include --max-time 15 \
  -H 'Origin: https://display.planiq.dk' \
  https://api.display.planiq.dk/health

curl --silent --show-error --include --max-time 15 \
  -X OPTIONS https://api.display.planiq.dk/api/maintenance/status \
  -H 'Origin: https://display.planiq.dk' \
  -H 'Access-Control-Request-Method: GET' \
  -H 'Access-Control-Request-Headers: cache-control'
```

Forventet: `/health` giver HTTP 200 med `Access-Control-Allow-Origin: https://display.planiq.dk`; preflight giver HTTP 200 med CORS-headers fra FastAPI. 502/503 uden ACAO peger typisk mod et mellemled, ikke nødvendigvis FastAPI. Del HTTP-status og sikkerhedsheaderne, men ikke cookies/tokenoplysninger.

## Gates

- GitHub CI: komplet frontend lint, API executable tests, backend CORS/maintenance tests.
- Browserpilot: idle 30m, absolut 6t, sessionforlængelse, cross-tab logout og login igen.
- Bevis at offentligt maintenance-status fortsat fail-closed ved backend-503/networkfail.
- Verificér at 401 på HLS capability ikke automatisk logger hele brugersessionen ud.
