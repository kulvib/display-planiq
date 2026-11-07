# ClientFlow 1.3.42/1243 — politikændring: tre seneste godkendte releases

**Kun repository-kode, dokumentation og tests. Ikke publicering, cleanup eller pilot.**

## Godkendt beslutning

Kun de seneste tre **godkendte, verificerede** release-TARs bevares i aktiv
Render release-store ved en fuldført rotation. Historiske metadata og
funktionel mulighed for fremtidig, sikker rollback er begrundelsen, men
ikke en selvstændig tilladelse til aktivere manuel rollback.

## Hvorfor den allerede godkendte 1.3.42 ikke kan publiceres direkte

- Store: fire gyldige, approved releases 1.3.38/1239 – 1.3.41/1242.
- 1.3.38/1239 er stadig eneste `latest_stable` og `default_install_version`, og
  Viborg2 testklient-ID 2 kører 1.3.38 efter den dokumenterede recovery.
- Den aktive katalogpin gør sletning af 1.3.38 forbudt. Oprydning må ikke
  springe 1.3.38 over og i stedet slette 1.3.39, da dette ville bryde reglen
  om præcis de seneste tre releases.
- 1.3.42/1243 er godkendt på source commit
  `b870cf8c3fa90286c6b4dccaae593eb8a0d57565`, SHA-256
  `ee35cc6caa9304bbc7ee4b1c763ecdeaf03d9d58a6c73cee943805251d8d6914`,
  men er endnu ikke publiceret. Den må ikke ændres, genbygges under samme
  identitet, deployes eller ophøjes til stable ved denne policyændring.
- GitHub `main` kan godt opdateres med denne særskilte operationsændring.
  Bevar de faktiske release-metadata fra den allerede byggede, godkendte 1243;
  kør ikke ny canonical release approval for ændrede kildebytes under samme
  ID. Fremtidige ændringer i klient/runtime skal have ny identitet og gate.

## Leverancens omfang

- `KEEP_LATEST_APPROVED=3`; audit og postflight er fail-closed ved 4+.
- `--require-three` er streng; gammel `--require-four` er kompatibilitetsalias
  der også kræver tre.
- Read-only oprydningsplan kan vurdere tre/four/five kontrollerede bundles;
  kun den **ældste** kan være kandidat. Fysisk sletning af katalogpinnede
  standard/fresh-install releases nægtes, også ved operatorbekræftelse.
- Prune bevarer directory flock, inode, SHA-256, no-follow og eksplicit
  dependency-attestation; ingen automatiske destruktive handlinger.
- Checks af allerede approved 1243, rollbacks, lokale installerede releases,
  backend deployments, CLI's aktive pilotflags og live Render env ændres ikke.

## Kontrol og næste driftsgate

1. Upload alene de tilhørende ændringsfiler i særskilt GitHub-branch, kør
   samtlige CI + smoke uden at ændre Render miljøvariabler.
2. Kør begge skrivebeskyttede scripts som `display_app`; forvent blokering af
   1.3.38 og ingen ændringer på disk.
3. Fastlæg en særskilt transition for active fresh-install/default og Viborg2,
   med ekstern verificeret arkivkopi og afhængighedskontrol.
4. Først efter en sikker, særskilt dokumenteret transition kan der roteres til
   lageret 1.3.40, 1.3.41, 1.3.42.
5. Manual rollback fortsat disabled; bevarelse af 3 TARs er ikke
   en fungerende rollback-test. Test isoleret failed-activation recovery og
   eventuel fremtidig manuel rollback som separate gates.

**Ingen produktion/klient er ændret af denne leverance.**
