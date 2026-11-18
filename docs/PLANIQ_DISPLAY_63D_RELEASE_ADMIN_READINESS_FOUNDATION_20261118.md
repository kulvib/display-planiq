# PlanIQ Display · Fase 63D-1 · Releaseadministration og DB-cutover readiness

**Kilde:** `display-planiq-main(20261118-094207).zip`, GitHub `main` = `88ce022c904ace9e0d21c914d509e563a17438e8`.

## Resultat af kodekontrol

Release-build, runtime-input-transport, kandidatverifikation, manuel godkendelse,
publication, release-store og rollback findes allerede. Men release-UI er stadig
**inaktiv kladdeplanlægning**, og installations-/deploy-controlleren anvender
separat, default-off pilot-/fleet-policy. **Fysisk pilotaccept er ikke dokumenteret**, og
DB-control-tabellerne er endnu ikke autoritativ deployment-gate.

Der er ingen forsvarlig teknisk genvej fra en godkendt kladde til en fysisk
opdatering. At implementere "approval" som en UI-knap uden låst forbrug i
client deployment-transaktionen ville være en autorisationsfejl.

## Dette trin er implementeret

1. `clientflow_release_readiness.py`: deterministisk, read-only readiness-matrix
   for den aktive katalog-/SHA-binding og syv separate release-gates. Alle
   installations- og fleet-autorisationer rapporteres eksplicit som `false`.
2. Releaseadministrationens eksisterende, eksplicit superadmin-GET indeholder
   nu `release_readiness` uden yderligere databaseopslag eller ændret kiosk-
   hotpath. Godkendelser, klientopdateringer, DB-cutover og nyinstallation åbnes
   **ikke**.
3. Frontend validerer version 1 af matrixkontrakten, eksakt SHA-binding, policy-
   revision og at samtlige fysiske/deployment-gates er lukkede. Ukendt,
   modstridende eller manglende status ⇒ hård stop for administration.
4. Et isoleret, endnu ikke tilsluttet `assess_future_db_wave` opstiller negative
   minimumsgates for fremtidig kontrolleret fleet-autorisation. Det kontrollerer
   release-id, SHA256, approved artifact, fysisk accept bundet til samme
   release, klokkeslæt, klient, credential, kildeversion og uforbrugt target.
   **Metoden er en precondition-evaluator, ikke tilladelse til deployment.**
5. Negative Python-/frontend-tests bekræfter, at status aldrig udsteder
   autorisation, og at ingen fremtidige DB-wave-kald er koblet ind i den
   eksisterende klientdeploy-router.

## Hvad dette trin IKKE implementerer

- Ingen ændring af 61A-migration/DB-schema, `clientflow_release_control` eller
  dens eksisterende `fresh_install_open=false`, `fleet_open=false`,
  `cutover_enabled=false`.
- Ingen ny release eller godkendelse, ingen signering, ingen installer, ingen
  runtime-input-hentning, ingen ændring af klientrelease `1.3.45/1246`.
- Ingen deployment `create_authorized_deployment` via DB-bølger, ingen
  "approval"/"consume" endpoint, ingen opdateringer af godkendelsesrækker.
- Ingen fysisk simultantest af livestream/Remote Desktop, recovery eller
  nyinstallations-/OS-/firmwarelåse. Render-deploy er ikke et fysisk pilotbevis.
- Ingen fjernelse af gamle Render-/env-autorisationer. Ingen opgraderinger af
  Render/Neon eller ændringer af sikkerhedschecks.

## Obligatorisk næste, sammenhængende implementering før cutover

1. Byg den eksakte 1.3.45/1246-kandidat reproducerbart på GitHub, med verificeret
   runtime-input-transport og CI på samme kilde. Buildet er *usigneret* indtil
   særskilt menneskelig godkendelse.
2. Bind signed/published release til DB-policy med transaktionel, revisionslåst
   promotion og revisionslog. Uforandret 1245 R2 skal stadig kunne verificeres.
3. Tilføj stærk reauth, klientbundne, tidsbegrænsede pilot-/bølgegodkendelser
   og en separat positiv fysisk accept med verificerbar evidence (inklusive
   recovery). En reviewed plan giver aldrig alene tilladelse.
4. Integrér DB-wave-forbrug og immutable artifact snapshot i samme
   `lock_system_client`-transaktion som `create_authorized_deployment`, med
   negativt testede race conditions, rollback og identitetskontrol.
5. Kør først *dobbeltlås* (gammel policy + DB), dernæst særskilt godkendt
   DB-cutover efter fysisk Viborg1-accept. Default-off ved deploy og DB-migration.
6. Integrér fresh-install authorization og første-aktiverings-/OS-/firmware-
   låsen under samme sikkerhedskontrakt, samt retention på sidste tre releases.
7. Test rollout 1 → lille bølge → stop/pausér/genoptag → rollback/recovery
   på fysisk testklient og under load. Dokumentér forventet skalering til
   100+ klienter og verificér at antallet af databasekald ikke stiger ved
   almindelige Status/Display-kald.

**STOP:** Indtil ovenstående er verificeret er den gamle, låste, eksplicitte
release-pilot den eneste mulige deploymentvej. Intet i 63D-1 ændrer den.
