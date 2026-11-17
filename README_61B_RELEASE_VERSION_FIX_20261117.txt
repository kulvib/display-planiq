PlanIQ Display — ClientFlow Releases: rettelse af manglende klientversion
Dato: 17. november 2026

Udgangspunkt: display-planiq-main(20261117-102055).zip

Fejl: Releases-siden læste legacy Client.client_version; klienternes seneste version findes i den autoritative client_domain_status (domain=status).

Rettelse:
- Versionsopslag nu i ét begrænset, skrivebeskyttet inventory-SELECT med outer joins til aktiv Status-credential.
- Ingen ekstra polling, ingen database-migration, ingen ændringer til klientagenten eller deploymentmotoren.
- Accepterer kun korrekt semver og tilhørende aktiv credential, kan normalisere v1.3.43.
- Udvider HTTP-regressionstest: mismatchede legacy-værdier, gyldig status, tilbagekaldt status og read-only kontrol.
- Alle eksisterende release-, pilot-, fleet-, nyinstallations- og cutover-gates forbliver lukkede.

INSTALLATION
1. Fortsæt fra aktuel main. Opret branch feature/display-release-canonical-version-inventory-20261117.
2. Upload præcis de tre filer fra denne ZIP med samme sti. Bevar øvrige filer.
3. Kør fuld GitHub CI. Merge og Render-deploy først efter grøn CI.
4. Åbn Administration → ClientFlow Releases og opdatér. Viborg1 (klient 3) bør fremgå med Status-agentens senest rapporterede version, hvis der findes en aktiv Status-credential og en gyldig versionsrapport.
5. Bekræft: ingen plan blev oprettet automatisk, ingen deployment startet, alle 4 gates lukkede.

LOKALE KONTROLLER
- SHA256SUMS.txt: 636/636 passer
- Python compileall: PASS
- 6 isolerede kildefunktionskontroller + kontrol af canonical source: PASS
- HTTP pytest: SKIPPED lokalt pga. manglende sqlmodel. GitHub CI er afgørende.

STOP: Hvis version stadig mangler efter deploy, skal den kanoniske Status-domænerapport for klient 3 undersøges skrivebeskyttet. Opfind ikke en version og åbn ikke en udrulningsgate.
