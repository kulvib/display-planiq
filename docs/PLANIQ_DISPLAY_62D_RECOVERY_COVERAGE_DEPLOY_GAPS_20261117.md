# PlanIQ Display · 62D · Recoverydækning og observerede deploymentafbrydelser

**Grundlag:** frisk `main`-ZIP `display-planiq-main(20261117-125020).zip`, GitHub `main` commit `24ec1b602a569ced88e064870607068847be9e9e`. Dato: 17. november 2026.

## Resultat: ét samlet beslutningsgrundlag, ingen migration

62C er kode-/CI-godkendt, men den fysiske produktionssmoke for automatisk logout, flere faner og kalenderen efter ca. 15 minutters access-tokenlevetid er fortsat en særskilt acceptkontrol. Render-loggen efter 62C viser, at `HEAD /health` nu giver HTTP 200, mens 502 stadig forekom omkring en Render-redeploy. Ændring af login-håndtering kan ikke afskaffe en serverafbrydelse med persistent disk.

62D samler **to manglende driftsbeviser i én ikke-destruktiv kodeleverance**:

1. `scripts/display_62d_recovery_coverage.py` validerer SHA256-/størrelsesdækning af den eksisterende 62B-staging **og de beskyttede historiske releases**, som kan ligge i et andet arkiv. Scriptet verificerer først 62B-manifestets database- og TAR-checksums; derefter kræves præcise SHA256/størrelser for de **tre seneste** godkendte releaseidentiteter `1.3.42/1243`, `1.3.43/1244` og `1.3.44/1245`. En tidligere release kan enten ligge i det verificerede stage eller i en særskilt privat offline recovery-arkivmappe. STOP ved manglende, udskiftet, redirectet, usikkert eller korrupt materiale. Source-lock af 1243 gælder kun **bytes til recovery**, ikke godkendelse af gamle credentials eller installation. Der tilføjes ikke en alternativ release til kataloget.
2. `scripts/display_62d_deploy_gap_report.py` laver en **lokal, offline opsummering** af tidstemplet Render access-log eksport: antal 200, 401, 405, 500, 502 og 503 samt 502/503-observationsvinduer, uden at kopiere IP-adresser, request-ID, URL-parametre eller øvrig råtrafik til output. Ingen netværksadgang eller automatiske databasekald. En observeret fejlrække er ikke en eksakt uptime- eller RTO-måling; logudsnit kan være ufuldstændige.

Begge scripts er operatørværktøjer, ikke backend-endpoints; ingen ændringer i runtime, DB-skema, miljøvariabler, releases, klienter, login, MFA eller klientudrulningsgates. Fuld GitHub CI og de eksisterende Docker/PG18-restore-tests er stadig obligatoriske. Scripts udfører **ingen** produktionseksport og kan aldrig godkende migration eller rollback.

## Source-lock på de tre beskyttede TAR-identiteter

| Version | Release-ID | Forventet SHA256 | Størrelse |
| --- | --- | --- | ---: |
| 1.3.42 / 1243 | `clientflow-1.3.42-seq-1243` | `ee35cc6caa9304bbc7ee4b1c763ecdeaf03d9d58a6c73cee943805251d8d6914` | 223610880 |
| 1.3.43 / 1244 | `clientflow-1.3.43-seq-1244` | `d3fdae8fb2a93f74431780f4aadde21625d10917e99cfbe6095ff2394e1e856b` | 223610880 |
| 1.3.44 / 1245 | `clientflow-1.3.44-seq-1245` | `28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5` | 223610880 |

Kilderne til releaseidentiteter er eksisterende verificerede katalog-/godkendelseshistorikker i repoet; de erstattes ikke af ukontrollerede klientrapporter. SHA256 beviser en filidentitet, **ikke** udstedersignatur, offsite-holdbarhed eller gendannelsesevne. Faktisk operatørbackup kan i dag mangle 1243 og 1244, fordi 62B indlæser det aktive `store/` og ikke nødvendigvis et separat recoveryarkiv. Det gør ikke backupværktøjet destruktivt, men betyder, at databasedump + aktiv TAR ikke må kaldes en komplet recoverypakke.

## Operatørprocedure – først efter særskilt godkendelse til håndtering af følsomme data

**Må aldrig udføres blindt i produktion.** 62B produktions-`--capture` kræver på forhånd godkendt, krypteret, adgangsbegrænset separat backupdestination, plads nok, opbevaringspolitik og plan for revisionsspor. Produktionens dump og releasefiler må aldrig uploades til GitHub, ChatGPT, almindelig fildeling eller CI.

På en separat **offline** maskine med en lovligt overført, beskyttet 62B-stage og særskilt verifieret recoveryarkiv:

```bash
# 1. Tjek ALLE byte-kopier, inklusive de tre historiske releases.
python3 scripts/display_62d_recovery_coverage.py \
  --verified-stage /secure/private-offline-copy/planiq-display-62b-... \
  --offline-recovery-archive /secure/private-offline-recovery-tars

# 2. Selve databaserestoren er ET ANDET bevis og kræver den isolerede
#    offline PostgreSQL-18-container, ikke produktion.
bash scripts/display_62b_offline_restore.sh \
  --verified-stage /secure/private-offline-copy/planiq-display-62b-...
```

Hvis alle tre TAR allerede er inkluderet og hashtjekket i 62B-stage, kan `--offline-recovery-archive` udelades. Hvis bare én mangler, stopper 62D. Denne kontrol kontrollerer ikke materialets kryptografiske udstedersignatur eller afprøver fysisk klientrollback. Den isolerede restore skal desuden efterkontrollere en sikker, afstemt udgave af PostgreSQL-data, migrationshoved, klient-/organisationsrelationer og de lukkede releasegates. Først derefter kan en menneskelig operatør udstede en separat recoveryattestation.

## Måling af Render 502-vinduer uden følsomme detaljer i resultatet

```bash
python3 scripts/display_62d_deploy_gap_report.py --input-file /secure/local/render-access-log.txt
```

Resultatet indeholder **kun** tællinger og tidsvinduer. Råloggen må ikke deles eller vedhæftes ukontrolleret; den kan indeholde persondata, IP-adresser, URL-parametre og andre følsomme detaljer. Ingen fremtidig alarm, automatisk redeploy eller loadtest udføres i 62D.

For reelle uptime-/kapacitetsmål på 100+ klienter kræves et fuldstændigt, sammenligneligt tidsvindue, klientfordeling, kontrolleret belastning, tilgængelighed fra eksternt probe, en rigtig recoverytest og verificerede Render-omkostninger. Fejlobservationer alene kan ikke bruges som RTO/RPO- eller omkostningsgaranti.

## Sikker beslutning efter 62D

| Arkitektur | Mulig gevinst | Kendt blokering |
| --- | --- | --- |
| Behold single-node med disk | Lavere kompleksitet og muligvis lavere faste udgifter | Backend-genstart og deployment giver fortsat en kort afbrydelse; kortere nedetid kræver realistisk accepteret vedligeholdelsesvindue og færre unødige deployments |
| Ekstern managed PostgreSQL + privat immutable object storage + stateless API | Mulighed for redundant API og normalt zero-downtime deployment | Kræver ny fakturerbar drift, genoprettet releaseautoritet, backup/restore og cutover/rollback-procedure; der foreligger **ingen** autoriseret pris-/ydeevnesammenligning eller fuldstændig produktions-recoveryattestation |

**STOP-kriterier:** Manglende 1243/1244/1245 bytehistorik, ufuldstændig offsite-backup, utilstrækkelig disk/kvote, uvist RPO/RTO, manglende isoleret restore, forskellige signerede katalog-/releaseidentiteter, uafklaret secret/MFA-migration eller ukendt klientreconnect. Alle `fresh_install`, `fleet`, `physical_pilot_accepted` og `db_cutover` forbliver false. Der gennemføres ingen DB-migration og ingen fysisk pilot i dette repo-trin.

**Vigtig driftsdisciplin:** Backend har auto-deploy på `main`. En ekstra manuel deploy af samme commit genstarter den diskbundne tjeneste igen og kan give et ekstra 502-vindue. Brug kun manuel redeploy med konkret driftbegrundelse. Fuld CI og syntetisk Docker-restore er nødvendige, men erstatter ikke en reel offsite backup- og restoreøvelse.
