# PlanIQ Display – isoleret ClientFlow-flådeprøve (16. oktober 2026)

## Formål og sikkerhedsgrænse

**Kun GitHub CI og lokal PostgreSQL.** Den automatiske prøve kan ikke rettes mod Neon, Render eller nogen ekstern database: den kræver `GITHUB_ACTIONS=true`, `ENVIRONMENT=development`, PostgreSQL på `localhost/127.0.0.1:5432` og database `planiq_ci`. Den opretter et unikt `fleet_ci_<tilfældigt>`-schema, kører mod schema-kvalificerede SQLModel-tabeller og sletter udelukkende dette schema ved oprydning. Ingen testklienter, tokens eller commands oprettes i produktion.

## Omfang

- **5, 10 og 15** samtidigt aktive, individuelle virtuelle klienter på én delt backend og ét lokalt test-Postgres.
- Hver testklient har særskilte, bcrypt-verificerede credentials i domænerne **Status, Display, System, Livestream, Terminal og Remote Desktop**. Tokens udstedes gennem de eksisterende HTTP-endpoints – aldrig ved at springe autentificeringen over.
- I hvert trin sendes **to runder med elleve HTTP-kald pr. klient**: fire presence, fire statusrapporteringer samt Display-, System- og Livestream-command claim. Requests fra klienterne overlapper via FastAPI/ASGI/asyncio; databasen deles mellem dem med samme poolbudget som backend-default (**5 forbindelser + 2 overflow**, 20 sekunders timeout).
- Kontroller: HTTP 200 på alle normale kald, tom command-kø, ingen oprettede falske commands, krydsklient-token afvist, efterfølgende credential-tilbagekaldelse håndhævet, Terminal-credential kan ikke bruges som Status-credential.
- Output til GitHub Actions-logs under `FLEET_CI_RESULT`: `clients`, `rounds`, `requests`, `errors`, `p50_ms`, `p95_ms`, `sql_statements`, `select_statements`, `sql_checkouts`, `elapsed_seconds`.
- CI-gate: alle tre størrelser skal have nul HTTP-fejl; sikkerhedsafvisninger skal bestå; ingen vilkårlige p95-tidsgrænser svækker pålideligheden.

## Begrænsninger – vigtigt

Dette er en **kort, in-process, isoleret HTTP-belastningsprøve** mod GitHub Actions' delte Postgres-service. Den kan afsløre funktionelle regressioner, DB/SQL-skalering i testmiljøet og fejl ved samtidighed. Den må **ikke** kaldes en certificering af 15 fysiske Ubuntu-klienter eller en prognose for Neons faktisk fakturerede CU-timer.

Prøven dækker ikke den lange updater-DPoP/replay-kæde, Livestream-upload/HLS, WebSocket- og HTTP-relay-ventetid, autentificerede browsersessioner eller en komplet 24-timers klientdrift. De er allerede særskilt dækket af andre kontrakttests, men kræver yderligere fokuseret kapacitetsprøvning, før vi hævder fuld paritet. **Ingen credentials, SQL-parametre eller database-URL skrives til resultaterne.**

## Efter grøn CI

1. Gem de tre `FLEET_CI_RESULT`-linjer fra GitHub Actions. Sammenlign normaliserede SQL-kald pr. klientrunde og p95-svartider uden at forveksle CI-maskinens svartider med produktion.
2. Sammenhold med 24-timersmålingen på den rigtige onlineklient med Neon **0,25–2 CU** og Render Starter; observer fejl, Neon-computeaktivitet og ressourcetrend.
3. Kun hvis tallene berettiger det, gennemføres en særskilt godkendt, lavintensiv **produktionsprøve** med rigtige, separat installerede klienter – ikke syntetiske credentials i produktionsdatabasen.
4. Budgettér omkostninger efter Neons dokumenterede CU-forbrug samt Renders faktiske trafik og serverplan, ikke ved simpel lineær opskalering af requests.

## Kørselskommando i CI

```bash
python -m pytest -s -q backend/tests/test_clientflow_fleet_capacity_ci.py
```

GitHub CI's eksisterende PostgreSQL-service og hash-låste Python-afhængigheder benyttes. Ingen nye betalte services.
