# PlanIQ Display — tre seneste godkendte ClientFlow-releases (7. november 2026)

**Aktuel politik: præcis de tre nyeste godkendte ClientFlow TAR-bundles skal
bevares i den aktive immutable Render release-store efter hver fuldført
release-rotation.** Historiske versionsnumre, approval-referencer, hashes,
deployments og fejlhændelser må ikke omskrives eller slettes. Denne beslutning
afløser fire-bundle-politikken i
`CLIENTFLOW_1340_FOUR_RELEASE_RETENTION_AND_ROLLBACK_TEST_PLAN.md`, som fortsat
ligger som historisk dokumentation, ikke som gældende driftsprocedure.

## Udtrykkelig sikkerhedsafgrænsning

- Antallet **3** gælder verificerede godkendte `.tar`-filer fysisk i Render
  `/var/data/clientflow-release-artifacts/store`, sorteret på monoton
  release-sekvens — ikke antal poster i kataloget eller lokale releases.
- `scripts/audit_clientflow_release_retention.py` rapporterer den faktiske
  tilstand skrivebeskyttet. `--require-three` kræver præcis 3. Den historiske
  `--require-four` accepteres af CLI af hensyn til kompatibilitet, men kræver
  **også tre** og kan ikke omgå den nye sikkerhedsgrænse.
- En ny release publiceres **aldrig som nummer fire**, heller ikke midlertidigt.
  Når tre er til stede, skal en selvstændigt godkendt oprydning frigøre én plads
  (tre til to), og den verificerede nye release kan derefter publiceres (to til
  tre). Fejler publiceringen, bliver processen stoppet; den må ikke overskride
  grænsen eller indsætte uverificerede bytes.
- `scripts/prune_clientflow_release_retention.py` er **read-only som standard**.
  Den vælger kun det ældste verificerede bundle. Den kan trinvis korrigere
  en eksisterende 4- eller 5-bundle-overgang, men *springer aldrig* et ældre
  pinned bundle over for at slette en nyere vilkårlig release.
- Oprydningsværktøjet læser det **aktive kildekatalog** og afviser altid
  faktisk sletning af den angivne `latest_stable`, `default_install_version`
  eller anden `installable` release. Katalogfejl afvises fail-closed. Disse
  kontroller gælder også, hvis begge manuelle bekræftelsesflag er angivet.
- Det er ikke nok, at en release er gammel eller at klienterne er testklienter.
  Operatøren skal uafhængigt kontrollere aktive og offline klienter, åbne
  deployments, downloads, recovery-behov, enrollment-koder og en verificeret
  arkiveret kopi efter den gældende releaseprocedure **før** vedkommende
  må attestere `--confirm-no-dependencies`. Koden kan ikke bevise fraværet
  af offline afhængigheder og automatiserer derfor aldrig denne bekræftelse.
- Sletning kræver fortsat eksakt release-ID, SHA-256 og **to særskilte,
  udtrykkelige operatorbekræftelser**. Samme katalog-lås og fd/inode/hash
  kontrol som før bevares. Ingen automatisk sletning tilføjes.
- En bundle på Render giver *ikke* i sig selv autorisation til rollback.
  `rollback-trust.json` har stadig `enabled=false`; almindelig manuel
  rollback/downgrade er deaktiveret. Lokal automatisk recovery efter en fejlet
  aktivering er en selvstændig funktion, der ikke må svækkes. En eventuel
  særskilt, sikker rollback-funktion kræver egen godkendelse, ny releaseidentitet
  hvis klientbinarier skal ændres, og fysisk isoleret accepttest.

## Helt konkret: 1.3.42/1243

Render indeholder aktuelt **fire** verificerede bundles: 1.3.38/1239,
1.3.39/1240, 1.3.40/1241 og 1.3.41/1242. Det aktive katalog er 1242 med
`latest_stable=default_install_version=1.3.38`. Den godkendte 1.3.42/1243
(SHA-256 `ee35cc6caa9304bbc7ee4b1c763ecdeaf03d9d58a6c73cee943805251d8d6914`,
223610880 bytes, approval `CF-1.3.42-1243-VIBORG2-PILOT-20261107`, source
`b870cf8c3fa90286c6b4dccaae593eb8a0d57565`) er **ikke** publiceret.

Den første mulige oprydningskandidat er 1.3.38/1239, men den er **pinned**
via det aktive standard/fresh-install-katalog. Den må derfor ikke slettes,
selv om man kun bruger testklienter. Intet katalog må pege på en release som
ikke længere findes. Retention-scriptet skal derfor melde `catalog_pin_blocks_cleanup=true`
og afvise destructive run. Den tilladte vej frem er en særskilt, gennemprøvet
overgang for fresh-install/default og pilot på Viborg2, eller en eksplicit
godkendt anden storage-/stagingløsning der fastholder alle sikkerhedsgates.
**Det er ikke lovligt at ophøje 1.3.42 til stable eller installere den på
Viborg2 for blot at få plads i store.**

Hvis en senere *separat godkendt* transition gør 1.3.38 uafhængig, kan
releases frigøres én ad gangen efter dokumenteret ekstern arkivering og
dependency review. Et sikkert fuldført lager efter 1.3.42-publicering består
præcis af **1.3.40/1241, 1.3.41/1242 og 1.3.42/1243**. Ingen af disse
roller giver automatisk adgang til nye klientsystemer.

## Skrivbeskyttet driftstest på Render

Kør som `display_app`, **ikke** som root (som vil se ejerskabet som fremmed):

```bash
gosu display_app env PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/opt/display/backend:/opt/display \
  python3 /opt/display/scripts/audit_clientflow_release_retention.py \
  --artifact-dir /var/data/clientflow-release-artifacts/store

gosu display_app env PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/opt/display/backend:/opt/display \
  python3 /opt/display/scripts/prune_clientflow_release_retention.py \
  --artifact-dir /var/data/clientflow-release-artifacts/store
```

Begge kommandoer er ikke-destruktive. På den aktuelle fire-release store
skal audit rapportere `approved_count=4`, `approved_limit=3`,
`within_approved_limit=false`, og cleanup skal rapportere pinned 1.3.38.
**Kør ikke de destruktive flag, før både kildekatalog/klientafhængigheder og
arkiveringen er særskilt godkendt.**
