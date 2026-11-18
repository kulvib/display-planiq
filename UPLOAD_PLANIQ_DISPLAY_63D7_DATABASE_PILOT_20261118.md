# PlanIQ Display · Fase 63D-7 · databasebaseret 1246-pilot

Kilde: `main` fra 18. november 2026, commit `dcf99c89690f6b8b31816a918055510b52765f9e`.

## Omfang

En særskilt, **aktiv** 1246-pilotformular i `Administration → ClientFlow Releases` kan autorisere **præcis én** fysisk, kontrolleret opdatering af `Viborg1` (client ID `3`) fra `1.3.43` eller `1.3.44` til `1.3.45/1246`. Dette er **ikke** generel fleet-autorisation. Den gamle flerklient-planlægning er fortsat inert.

Knappen hedder **Autoriser og start pilot**: Den bestiller faktisk en deployment, som klientens updater kan begynde at udføre. **Tryk ikke** på knappen, før fysisk beredskab/recovery er bekræftet. Der er ingen automatisk rollback eller nedgradering. Uanset udfald kan samme version/klient ikke bestilles en gang til gennem denne pilots autorisation uden en ny gennemgået ændring.

Serveren kræver superadministrator uden impersonation, adgangskodegenbekræftelse med eksisterende rate limit, begrundelse, en bevidst bekræftelse, uændret kontrolrevision, låst klient, godkendt online Status credential nyere end 90 sekunder, en aktiv unik Update credential, intet aktivt System-arbejde eller deployment, ingen ukvitteret recoveryfejl, kataloget eksakt som den kildelåste 1246-pilot, centralt tilladt 1246 og de **fysisk publicerede** immutable bytes (SHA256 + størrelse + approvallås).

Autorisation og deployment-event samt audit udføres i **samme transaktion**. Samtidige request serialiseres gennem klientens FOR UPDATE-lås og den eksisterende unikhedsconstraint. Ingen migrationsændringer og ingen databasepolling.

Det eksisterende `clientflow_deployments` endpoint og tidligere environment-baserede pilotnødgates ændres ikke; de er fortsat lukkede, når de tilhørende historiske flag ikke er aktiverede. Den nye databaseautorisation afviser eksplicit aktive historiske pilot-/fleet-flag, så autoriteterne aldrig blandes.

## Render Environment – handling

| Handling | Navn | Begrundelse |
|---|---|---|
| Behold | `CLIENTFLOW_RELEASE_ARTIFACT_DIR` | Uændret beskyttet release-lager |
| Behold | `CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1` | Nyinstallation fortsat suspenderet |
| **Tilføj ikke** | `CLIENTFLOW_1246_PILOT_CLIENT_ID` | Brugervalg/pilotautorisation foregår i backend/database |
| **Tilføj ikke** | `CLIENTFLOW_1246_PILOT_ARM_REFERENCE` | Ingen Render redeploy per klient |
| Ændr | **Ingen** | Eksisterende drift, nøgler, database, sessioner og medier uændret |
| Slet | **Ingen** | Gamle sikkerhedsgates fjernes ikke blindt; oprydning kan komme særskilt |

**Der er ingen ny miljøvariabel** i denne fase, og der skal ikke kopieres eller uploades følsomme nøgler. Hvis reelle secrets tidligere er delt ved en fejl, skal de roteres i en særskilt sikkerhedshandling.

## CI-gates og driftsforløb

- Alle GitHub CI-jobs, inkl. den hash-låste SQLModel/Postgres integration, skal bestå **før** merge.
- Efter merge/redeploy: grønt production smoke, releasecatalog/status check, kontrol af Update credential, fysisk recoveryparathed og **en udtrykkelig manuel pilotbestilling**.
- Efter piloten: status/version, Livestream, Remote Desktop, reboot/recovery, rollback *manual recovery* og sessionadfærd dokumenteres før næste release- eller fleetfase.
- Ingen ændringer i Chrome-fullscreen-check, agent-/frontend-polling, Neon hotpath-forespørgsler eller 1.3.45/1246 artifact.

## Begrænsning

Dette er en klientbundet **første pilot**, ikke allerede en generel valgfri klientliste til deployment og slet ikke en implementeret rollbackknap. De funktioner kræver en efterfølgende, særskilt revisionssikker governance/cutover-fase, så vi kan skalere kontrolleret til 100+ klienter.
