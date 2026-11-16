# PlanIQ Display 61B-2A – kontrolleret OS-/firmwarevedligeholdelse (kildestaging)

**Dato:** 16. november 2026  
**Basis:** frisk `display-planiq-main(20261116-082716).zip`  
**Status:** Ny kildebranch til CI og isolerede tests; **ingen aktivering eller fysisk pilot**.

## Formål og grænse

Denne ændring etablerer en snæver vedligeholdelseslås mellem ClientFlows eksisterende, root-ejede System-broker og den uprivilegerede Display-runtime **før** APT/dpkg og fwupd kan ændre systemet. Låsen anvender den eksisterende System-kommando og det eksisterende boot-ID-/idempotensjournal; ingen nye fjernkommandoer, credentials eller database-migrationer. `update-os` og `update-firmware` har fortsat præcis deres eksisterende autorisation og ikke-fjernende opdateringspolitik.

Releases 1.3.44/1245, SHA256, releasecatalog, godkendelsesdokumenter, migreringskæde, rollback og 61A/61B-1-gates ændres **ikke**. Denne branch opretter ingen klientdeployment. Klientkoden træder først i kraft på en særskilt **ny, signeret og fysisk pilottestet** ClientFlow-release. De gamle Render-spærringer og DB-gates forbliver lukkede.

## Kontrakt

1. Root broker opretter et atomisk, ikke-hemmeligt statusobjekt i `/var/lib/clientflow/update-maintenance/state.json` under root-ejet 0755-mappe, 0644-fil. Kun System-broker skriver; status-agent, lokal GTK-GUI og Display-runtime læser. Symlink, ugyldig tilstand eller utilgængelig status afviser browserstart (fail closed).
2. Broker sætter `browser_stopping` **før** en ændring, beder Display-runtime stoppe Chrome via eksisterende lokale socket og verificerer `status.pid == null`. Manglende stop/status: ingen installationshelper køres, journal og status går i tvivl/recovery.
3. `installing`: APT/dpkg eller fwupd køres som før. Kioskens kalender-, backend- og manuelle Start-kommandoer respekterer samme lokale browserlås. Browseren forsøger højst hvert 15. sekund at genstarte efter låsning, så status ikke opdateres hvert sekund.
4. Hvis der **ikke** kræves reboot, markeres *installationen* fuldført, og den eksisterende Display-runtime kan selv genåbne browseren efter internet-/kalenderregler. Den lokale installation og en visuelt verificeret kiosk er forskellige acceptkriterier.
5. Ved krævet reboot markeres `rebooting`, og System-broker journalfører `reboot_requested` før den eksisterende kontrollerede genstart. Ved samme boot-ID er resultatet fortsat usikkert. Efter *ny* boot og samme kommando-ID kræves Display-, Status-, System-agent- og Browser-Guard-services i `active`-tilstand, før vedligeholdelseslåsen frigives. Fejl giver `recovery_required`, ikke succes eller automatisk gentagen reboot.
6. `needs-shutdown` fra fwupd afvises fortsat uden automatisk nedlukning. Ved andre fejl bevares markeringen til kontrolleret recovery. Vi opfinder ikke en manuel emergency-bypass i webadministrationen.
7. Status-agenten sender det sanerede `update_maintenance`-objekt med den eksisterende status-heartbeat. Backend projicerer det på eksisterende klient- og hot-read-responser **uden nye DB-kolonner eller ekstra polling**. Local-GUI viser status og spærrer Start/Stop under vedligeholdelse. Software-siden i Control Room viser samme seneste rapporterede status og advarer, når klienten er offline. Der vises **ingen opdigtet procent eller ETA**.

## Afgrænsede udeståender – må ikke fejlagtigt markeres som færdige

- Denne kode ændrer **ikke** ClientFlows signerede releaseaktivering eller kæden fra 1.3.43 til 1.3.44; den eksisterende controller har sin egen staging-, health- og rebootgate. En fremtidig fælles statuskontrakt skal integrere dens release-tilstande uden at omgå autorisationen.
- Den lokale GTK-GUI får en tydelig statusrække, men der etableres **endnu ikke** en separat fullscreen-vedligeholdelsesskærm. Dette kræver fysisk Wayland/GTK-pilot på et kontrolleret testapparat. Garanter ikke en separat fuldskærmsvisning uden en sådan prøve.
- `completed` betyder, at System-brokerens OS-/firmwareinstallationskontrakt er afsluttet. Faktisk kioskdrift skal stadig verificeres særskilt (internet, kalender, Chrome fuldskærm, aktiv version, skærmindhold). UI påstår ikke fysisk pilotaccept.
- Der er endnu ingen produktionssmoketest af 61B-2 på hardware, signeret ny release, Render-cutover eller tilladelse til fleet/nyinstallation.

## CI og sikkerhedstest

- Validér at en klient uden maintenance-marker fungerer som før.
- Markér `browser_stopping`; alle adgangsveje til Chrome (kalender, backend, lokal GUI, reset, bootretry) skal afvise start.
- Bekræft at broker aldrig kører apt/fwupd, hvis `stop_browser` eller kontrol af PID ikke lykkes.
- Afvis symlink, korrupt status og forkert command-id, og blokér samtidige opdateringer.
- Reproducer reboot med samme boot-ID (STOP), med ny boot og alle kritiske services OK (PASS) samt med uklar service-tilstand (STOP).
- Test at rapporteringsfrekvensen for statusagenten ikke forøges, og at offline-status ikke præsenteres som aktuel.
- Kør eksisterende signatur-/release-, migrations-, browser-, fwupd-, OS- og recoverytests. GitHub CI er endelig gate.

## Før fysisk 61B-2-godkendelse

Særskilt signeret release med kontrol af fuld byggemanifest/artefakt. Pilottest på **fysisk tilgængelig** testklient efter eksplicit operatørgodkendelse. Test både ingen opdateringer, en opdatering uden genstart, kernelopdatering med genstart, firmware `needs-reboot`, firmware `needs-shutdown`, brudt internet, udløbet strømbillede og rollback/recovery. Kontrollér at login/GUI/kiosk automatisk vender tilbage kun under de aftalte netværks- og driftspolitikker, og at ingen anden klient opdateres.
