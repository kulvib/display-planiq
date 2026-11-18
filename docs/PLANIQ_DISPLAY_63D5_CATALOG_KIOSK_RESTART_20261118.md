# PlanIQ Display · Fase 63D-5 · sikker pilotkatalog-status og Genstart browser

Kilde: `main` SHA `9c72ed690d3b901ede99a8b7f41932f5b78305f8` fra 18. november 2026 kl. 12.42. Denne fase ændrer **ikke** den godkendte `1.3.45/1246` TAR, releasekataloget, produktionsmiljøvariabler eller aktive klienter.

## Releaseadministration, stadig lukket

- Releaseadministrationen anerkender kun **præcis** de to læsebare katalogtilstande: den uændrede stabile `1.3.44/1245`, eller det fulde validerede katalog med `1.3.44/1245` som stabil fresh-install-standard og `1.3.45/1246` som `supported`, `installable=false`, `in_place_update`-only pilot.
- Enhver uventet afvigelse, ekstra releasepost, forkert checksum, ændret notes/compatibility, ny standard eller forsøg på at åbne `cutover_enabled`, `fleet_open` eller `fresh_install_open` afvises. Den eksisterende databasepolitiks singleton binder fortsat godkendelse til `1.3.44/1245`.
- Readiness-status accepterer to poster **kun efter** eksakt katalogkontrol. `active_catalog_promoted=true` betyder alene, at update-only pilotkatalogfilen er aktiv, og er **aldrig** bevis på Render-lager, fysisk pilot eller deploymenttilladelse.
- Ingen frontendknap eller API i denne fase udfører promotion, installerer 1246 eller åbner for databasebaseret fleet-udrulning.

## Kiosk browser · Genstart

- Lille **Genstart**-chip ved siden af `KIOSK BROWSER`, synlig for `bruger`, `admin`, `superadmin` med deres eksisterende klient- og organisationsadgang.
- Visuel statusmatrix og backend afviser offline/ikke-godkendt klient, låst klient, opdatering, dvale, anden aktiv kommando, manglende URL og browser, der ikke kører. Chippen er nedtonet og deaktiveret når handlingen ikke er tilladt. Supportværktøjerne Remote Desktop og Terminal beholder deres eksisterende statusmatrix.
- Backend bruger **kun** de eksisterende `stop_browser` → `start_browser` kommandoer, der allerede understøttes af den godkendte 1246-runtime. `reset_browser` anvendes ikke: browserprofil, cookies og login nulstilles ikke bevidst.
- Når agenten autentificeret har kvitteret for en faktisk udført Stop, køes Start i den **samme database-transaktion**, så svigtet Stop, omkonfiguration, dvale, maskinstart/-stop eller aktiv deployment ikke udløser en utilsigtet Start.
- Den eksisterende Display-agent markerer manuelle browserhandlinger over for kalenderstyringen; den normale kalender-overstyringsregel kan derfor gælde frem til næste kalendergrænse. En genstart er ikke en ændring af selve kalenderplanen.
- Chrome starter med den konfigurerede kiosk-URL og indlæser websiden igen. Nye statiske assets hentes efter browserens normale HTTP-cachepolitik; knappen tømmer **ikke** cache og lover ikke at hente alle filer på ny.

## Forudsætninger, afprøvning og gates

1. Upload branch-pakken på en ny branch fra eksakt kilde-commit og kræv fuld GitHub CI, herunder Python SQLModel/HTTP-tests, frontend-test, source gate og PostgreSQL-sikkerhedstests.
2. Efter merge: verificér grøn Render-deploy, kontrol af releaseadministration i lukket tilstand og deaktiveret Genstart-chip ved offline, stoppet browser og deployment.
3. Foretag kun en fysisk Genstart-browser-test på en udtrykkeligt valgt testklient. Verificér at Chrome PID ændres, kiosk-URL bliver genindlæst, cookies forbliver, skærm/kalender reagerer normalt, og at andre klienter ikke påvirkes.
4. Publicering af 1246 til Render-release-lager, aktiv pilotkatalogændring, pilotmiljøvariabler og deployment er **separate**, endnu ikke udførte handlinger og kræver deres egne godkendelser og verifikationer.
5. Releaseretention bevarer de tre seneste godkendte releases. Ingen ny ClientFlow-build følger af denne frontend-/backend-fase.

**Begrænsning**: SQLModel/DB-integration og faktisk browsergenstart kan ikke verificeres på testklienten fra den lokale kildeinspektion alene. De skal verificeres i GitHub CI og fysisk på Viborg1 før produktionsaccept.
