# PlanIQ Display – central driftsfejlhistorik (Step 60A)

## Formål og afgrænsning

Superadministratorens **Administration → Driftsfejl** viser fejlforløb observeret i de
**centrale, autentificerede** Status-, Display- og System-domæners persistente
statusrapporter. Første registrering starter **efter 60A-migration og deployment**;
historik bagud i tid kan ikke rekonstrueres uden eksisterende bevisdata.

Den centrale scanner bruger **ingen ekstra netværksrequests fra ClientFlow-klienter**.
Ét backend-job pr. 60 sekunder læser batchvis den seneste, højst 180 sekunder gamle,
server-tidsstemplede status for godkendte, ikke-slettede klienter. PostgreSQLs
transaktionslåste advisory lock sikrer ét writer-forløb på tværs af webworkers.
Kun transitions medfører nye hændelsesrækker. Vedvarende fejl opdateres højst
hvert femte minut. Genstarter tilføjes som særskilte observationer.

## Fejl som klassificeres

- **Status:** Fejl i de navngivne ClientFlow-services; NTP eksplicit frakoblet
  eller usynkroniseret.
- **Display:** Runtime `failed/error` og kiosk-lockdown `failed/error/rollback`.
  Browserens tilsigtede `waiting_internet` er **ikke** en fejl.
- **System:** Rapporteret manglende broker-socket og firmwareopdatering med
  eksplicit fejlstatus.

Der anvendes en **fast whitelist** af koder/titler. Frie agent-fejltekster,
terminaloutput, WiFi-profiler/SSID, nøgler, URL'er og JWT'er gemmes aldrig i
denne journal. Hver åbnet fejl får ét incident-ID. Ved gentagelse efter
dokumenteret løsning oprettes en *ny episode* i stedet for at overskrive
historikken.

## Hvad "løst" betyder

En fejl markeres **kun** som observeret løst, hvis en nyere frisk, komplet
rapport fra *samme domæne* eksplicit viser, at fejltilstanden er væk.
Manglende status, manglende felter eller offlineforbindelse kan **ikke** lukke
en aktiv fejl. UI markerer sådanne forløb som **ikke aktuelt bekræftet** efter
180 sekunder. Nye boot-ID'er journalføres separat – også hvis fejlen fortsætter.
En løsning observeret efter genstart betyder **ikke**, at genstarten forårsagede
løsningen.

## Sikkerhed og database

- Ny Alembic-revision: `20261024_60a_incidents` (direkte efter historisk 59A).
- To tabeller: `operational_incident`, `operational_incident_event`, unikt
  *aktivt* forløb pr. klient/domæne/kode via partial index.
- Klient-FK `ON DELETE CASCADE`: ved permanent klientsletning slettes også
  klientens hændelser; ingen orphaned PII.
- Eksakt PostgreSQL-kontrakt/fingerprint og SHA-256-pin på 60A-migrationen.
- Runnerens frosne 58A/39A-legacy sammenligning ophæver præcist 60A og 59A i
  omvendt rækkefølge. Ingen historisk migration er omskrevet.
- Ingen rollback/downgrade-sletning af incident-data.
- API er **superadministrator-only**, read-only, `no-store`, begrænset til
  100 rows pr. side og 500 hændelser pr. forløb.
- `OPERATIONAL_INCIDENT_RETENTION_DAYS` standard 365 (min. 90, maks. 3650).
  Kun *løste* episoder slettes efter udløb; aktive fejl bevares.

## Åbne dækningsområder – ikke falsk lovet

Dette er en hændelsesjournal for **statusbaserede ClientFlow-fejl** – ikke endnu en
komplet opsamling af alle backend-exceptions, GitHub CI, Render-systemlogs
eller databasehændelser. En **separat read-only adapter** viser de seneste
90 dages afsluttede ClientFlow deployments og signerede rollbackresultater
direkte fra deres eksisterende autoritative tabeller. Deres beviser duplikeres
ikke, og en vellykket handling lukker ikke historiske, fejlede handlinger.
Ligeledes kan fejl af kortere varighed end scanningsintervallet overses, hvis
deres eneste bevis er en overskrevet statusrapport. Den begrænsning skal
fremgå ved fysisk/prod accept, indtil en autoritativ hændelseskilde dækker dem.

## Godkendelsesrækkefølge

1. CI: schema-contrakt/fingerprint, tom PostgreSQL-migration, idempotens,
   historisk baseline/legacy, auth, schema-revision og source-integritet grøn.
2. Render deployment med særskilt godkendelse. Observer scanner-log samt
   read-only endpoint som superadmin/ikke-superadmin.
3. Fysisk pilot Heidi1: simuler servicesvigt og verificer ny fejl, fortsat
   fejl efter genstart, recovery kun efter frisk status, tilbagevendende fejl,
   offline-tilstand og at følsomme payloadfelter ikke lagres.
4. Valider faktisk write volume ved 15 og 100 klienter før bred udrulning.

Der er **ingen** ændringer i ClientFlow releasekatalog eller signeringsnøgler.
