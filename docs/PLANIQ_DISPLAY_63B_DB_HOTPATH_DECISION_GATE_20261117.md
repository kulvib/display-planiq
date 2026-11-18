# PlanIQ Display · Fase 63B · Målt databasebelastning før runtimeoptimering

**Dato:** 17. november 2026. **Kilde:** brugerens nye `display-planiq-main(20261117-164729).zip`. Dette er fortsættelsen af repoets Fase 63, **ikke** en ny deployment-/releasefase.

## Konklusion fra den leverede kildekode (ikke fra Render-produktion)

- Den lokale PostgreSQL 18 på den eksisterende Render-service og det persistente godkendte ClientFlow-lager forbliver autoritative. Den historiske `render.yaml` er ikke bevis for kørende driftstopologi.
- `backend/service1/db_hotpath_telemetry.py` registrerer faste, identitetsfrie 15-minutters SQL-/connection-pool-kategorier, inklusive WebSocket-revocation-rechecks. Selve instrumentation introducerer ikke SQL-kald.
- `scripts/display_63_cost_performance_baseline.py` kunne allerede måle HTTP-trafik, men medtog ikke `cursor_ms` og det oplyste samlede antal DB-vinduessekunder i sin JSON-rapport.
- `scripts/display_63_compare_baselines.py` kontrollerede HTTP-p95, HTTP-fejl, anmodninger pr. klient og størrelser på byggede statiske assets, men **sammenlignede ikke** SQL-statements og DB-pool-checkouts pr. operation. Man kunne derfor overse en databasebelastningsregression uden HTTP-trafikregression.
- I den faktiske frontend-kode har Control Room allerede adaptiv polling (typisk 60 sekunder, 10 sekunder ved aktiv handling) og afbryder databasebaseret polling på skjulte sider. Fase 63B må ikke genindføre dublerede loops.
- Den eksisterende isolerede `5/10/15`-fleet CI-test er **ikke** en dokumenteret belastningstest med 100 fysiske klienter.

## Hvad Fase 63B ændrer

Kun **offline-måleværktøjer, tests og denne dokumentation**:

1. Fase 63 baseline-JSON aggregerer nu målte DB-`cursor_ms` fra de faste whitelisted kategorier og tæller antal sekunder i de rapporterede DB-vinduer (sum, ikke unik vægtid). Ukendte kategorier og skadelige/ikke-endelige tal ignoreres.
2. Fase 63 før/efter-sammenligningen opdager **SQL-statements pr. operation** og **DB-checkouts pr. operation** som ekstra diagnosticerende regressionsindikatorer. En operation er en HTTP-request eller en WebSocket-revocation-recheck. Minimum: mindst 30 minutters HTTP-vindue, to DB-summaries i hver observation og mindst 20 DB-operationer i samme kategori på begge sider.
3. En ny sorteringsrapport `scripts/display_63b_hotpath_priorities.py` rangerer whitelisted DB-kategorier efter **observerede SQL-statements**, viser SELECTs/checkout/cursor-tid pr. operation samt fremhæver sikkerhedskritiske revocation-stier. Rækkefølgen er til **undersøgelse**, ikke autorisation til at fjerne databasekontroller.
4. Regresionsgrænser for DB er diagnostiske: statements/operation **over +20 % og +0,5**; checkouts/operation **over +25 % og +0,25**. Samme datakategori, sammenlignelige måleperioder og tilstrækkeligt antal observationer kræves. Værktøjet estimerer hverken pris, målbar speedup eller faktisk 100-klientkapacitet.

Ingen ændringer i backend/frontend runtime, klient-/factory-kode, schemas, logins, MFA, credentials, release-signering, ClientFlow-release-katalog, rollout- eller fresh-install-gates, miljøvariabler, Render-konfiguration eller produktionsdata. Ingen ny infrastrukturtjeneste, token eller periodisk polling introduceres.

## Driftsmåling (før/efter)

Kør i privat lokalt katalog. Rå Render-logs kan indeholde IP-adresser, klientidentiteter, URL-parametre og andre fortrolige oplysninger. **De må ikke uploades til GitHub eller indlejres i PR-artefakter.** Del kun analyserede, aggregerede rapporter.

```bash
# Efter en reel, sammenlignelig måling på Render:
python3 scripts/display_63_cost_performance_baseline.py \
  --input-file /private/render-before.ndjson \
  > /private/63-before.json

# Ranger de faktiske SQL-tunge kategorier – kan også bruges på after:
python3 scripts/display_63b_hotpath_priorities.py \
  --baseline /private/63-before.json \
  > /private/63b-priorities-before.json

# Kun efter målebevist, sikker runtimeændring i en senere branch:
python3 scripts/display_63_cost_performance_baseline.py \
  --input-file /private/render-after.ndjson \
  > /private/63-after.json
python3 scripts/display_63_compare_baselines.py \
  --before /private/63-before.json --after /private/63-after.json \
  --fail-on-indicator
```

Input må indeholde både Render-requestlogs (til HTTP/tid/klientrate) og `db_hotpath_summary`-applogs. Uden begge typer kan analysen ikke bevise, at databasebelastning falder samtidig med uændret HTTP-latens. Manglende DB-vinduer markeres eksplicit som **utilstrækkelig dækning**.

Supplér fra Render med faktisk CPU/RAM, latency (p50/p95), 502/503, tidsvindue, instans/plan og driftsomkostning. Baseline-loguttræk er ikke nødvendigvis komplette; `log_export_complete` forbliver `false`, indtil fuldstændighed er dokumenteret uden for disse værktøjer. Et enkelt klientspor og lineære 1/10/50/100-scenarier er ikke et kapacitetsbevis.

## Beslutningsgate før runtimeændring

- Prioritér de faktiske DB-kategorier efter totale SQL-statements og efter operationens statement-/checkout-tal. Kontrollér først om stor SQL-mængde skyldes mange legitime kald eller unødvendigt arbejde pr. kald.
- Kontrollér særskilt sikkerhedsfunktioner: Livestream-presence og WebSocket-revocation må ikke deaktiveres eller forsinkes for at opnå en besparelse. `/health` skal fortsat opdage offline netværk hurtigt og uden DB-arbejde; `/health/db` skal fortsat kontrollere DB/readiness.
- Først efter en dækkende før-måling udarbejdes en samlet, testbar performanceimplementering med uændret funktion, DB-gates og en tilstrækkelig realistisk efter-måling. Stop ved regression eller uklar dækning.

**Denne patch giver ikke i sig selv færre produktions-SQL-kald, lavere Render-regning eller en hurtigere frontend.** Den gør Fase 63B's næste beslutning mere målbar og beskytter imod at forveksle uændret requestantal med uændret databasebelastning.
