# PlanIQ Display · Fase 63D-3 · Release-governance og bølgelivscyklus

**Kilde og base:** `display-planiq-main(20261118-104531).zip`, GitHub `main` `0b80502e5dd9b9ebd90af74a97955ef94f446ad8`.

**Sikkerhedsstatus:** Forberedelsesimplementering. **Ingen ny HTTP-route, ingen automatisk/manuel deploymentautorisation, ingen promotion, ingen signing, ingen installationsåbning og ingen Render-/DB-konfigurationsændring.** Den eksisterende gamle pilotautorisation forbliver den eneste live vej. En grøn CI eller et merge er ikke et cutover.

## Omfang – et større sammenhængende næste skridt

Efter 63D-2's transaktionelle forbrug skal en fremtidig releaseadministration kunne føre et sikkert revisionsspor fra *reelt signeret og publiceret release* over *fysisk accept* og *uafhængig menneskelig bølgegodkendelse* til pause, stop og registrering af resultat. Dette er nu implementeret som isolerede, endnu ikke routede transaktionsprimitiver:

- `clientflow_release_governance_policy.py`: dependency-free, deterministiske negative preconditions for revisioner, release/SHA, to uafhængige personer, referencer til pilot/recovery og bølgens tilladte livscyklus.
- `clientflow_release_governance.py`: `stage_physical_acceptance`, `stage_approve_controlled_wave`, `stage_control_wave` (pause/resume/stop) og `stage_reconcile_wave` (afslut/fail på faktisk deployment-resultat).
- Hver mutation låser singleton-releasepolitikken og derefter eventuelle wave-/target-rækker i fast orden, gentager eksakt revision og release/SHA-binding og skriver **kritisk audit i samme SQLModel-transaktion**. Der er **ingen intern commit**. Kaldende fremtidig admin-handler skal selv udføre step-up, rollback ved fejl og én samlet commit.
- Fysisk pilotaccept kræver to **forskellige aktive superadministratorer**, præcis signeret/publiceret artifact-binding, en frisk, credential-bundet canonical Status-version, et faktisk terminalt vellykket deployment for samme release/SHA uden uafklaret recovery-fejl og særskilte, afgrænsede pilot- og recoveryreferencer. Den bekræfter alene *menneskeligt dokumenteret* fysisk prøvning, ikke automatisk hardwarebevis.
- En virkelig bølgegodkendelse kræver en **tidligere gennemgået** kontrolleret plan, at godkenderen ikke er opretteren, friske online Status-credentials og uændret kildeversion for samtlige planmål, et entydigt positivt pilotaccept-bevis og signerede bytes. `draft`-targets bliver først `approved` i en staged transaktion. Den eksisterende produktionsrouter kalder **ikke** denne kode.
- Pause og stop kan gennemføres uden afhængighed af artifact-store, så en midlertidig store-fejl ikke blokerer en sikker nødhandling. Stop tilbagekalder alle endnu uforbrugte targets, men **annullerer aldrig allerede autoriserede deployments implicit**.
- Resume gentager kontrol af signeret artifact og pilotaccept. Reconcile lukker kun en wave som `completed`, når alle consumed deployments faktisk er `succeeded`, og sætter bølgen `failed`, hvis et forbrugt deployment har terminal fejl. Ingen implicit positiv accept fra statusflag alene.

## Vigtig grænse mod drift

Ingen produktionsroute importerer governance-modulet. Ingen DB-cutover-flag, `fleet_open`, `fresh_install_open` eller gammel pilotgodkendelse sættes her. Produktionsadministrationen (`_bound_control`) afviser stadig autoriserede rækker, indtil den særskilte migration/cutover er designet og godkendt. Modulernes navne begynder derfor med `stage_`; de er ikke klar til operativ brug blot fordi deres enhedstests er grønne.

Det aktuelle katalog har stadig **kun `1.3.44/1245` stable**. Kildekandidaten `1.3.45/1246` er **ikke godkendt, signeret eller fysisk accepteret**. Ingen test med syntetisk SHA/personer udgør en faktisk godkendelse.

## Testmatrix

1. Afvis forkert policyrevision, bølgerevision, release eller bundling-SHA; afvis udløb og ændrede/duplikerede targets.
2. Afvis samme opretter/godkender, samme testperson/reviewer, ikke-superadmin, ukendt eller inaktiv klient, manglende/frakendt Status-credential, ændret version og gammel Status.
3. Afvis manglende/uklar fysisk accept samt fejlagtige artifact-bindings; aldrig en implicit installationstilladelse.
4. Godkendelse → audit → rollback skal fjerne både DB-ændringer og audit; en commit skal bevare dem samlet.
5. Pause → resume → stop skal blokere nye grants og bevare allerede forbrugte deployments; stop må fungere ved udløbet bølge.
6. Reconcile skal forblive STOP ved verserende deployments, og kun afslutte korrekt ved faktiske terminale resultater.
7. To samtidige approve-forsøg på ægte **disposable PostgreSQL 18** skal give ét godkendt resultat og én afvisning efter row locks, præcis ét auditspor og fortsat lukkede flags.
8. Kildekontrakt bekræfter, at hverken almindelig administration eller deployrouter kan kalde den nye motor, og at gammel pilotguard er uændret.

## De resterende absolutte gates før ClientFlow Releases kan kaldes færdig

1. Reproducerbar `1.3.45/1246`-candidate via verificeret runtime-input-transport, kanonisk GitHub-release-build, signering og godkendte publicerede bytes.
2. En korrekt reauth-/step-up-beskyttet HTTP-administration, som med eksplicit uafhængig godkendelse forbinder de staged transaktioner til reelle brugere og atomiske kritiske audit events; sikkerhedsteamet skal kontrollere impersonation, session-revocation og dobbeltklik-/raceforløb.
3. Fysisk Viborg1-pilot: faktisk release, installer/recovery, Remote Desktop + Livestream samtidig, inputlatens, netværksafbrydelse og rollback. Referencer/evidence valideres af mennesker og bindes til den eksakte release+SHA.
4. Separat godkendt **dobbeltlås** gammel pilotpolicy + DB-autorisation, derefter eksplicit cutover i egen kontrollerede migration/policyændring. Ingen utilsigtet ændring ved Render deploy.
5. Fresh-install-/første aktiveringslås, OS-/firmware-/genstartsgates, rollbackretention (sidste 3), pause/stop af faktiske deployment-workflows og skaleringstest til mindst 100 klienter.

**STOP:** Fortsæt ikke til klientdeployment eller automatisk rollout alene efter 63D-3. Næste beslutningspunkt er, om vi først vil gennemføre usigneret kandidatbuild og fysisk test, og derefter koble den dokumenterede governance til live API under særskilt godkendelse.
