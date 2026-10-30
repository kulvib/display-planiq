# ClientFlow 71A – behold den eksisterende GitHub-releaseproces

## Godkendt beslutning og teknisk konsekvens

Operatøren ønsker samme arbejdsgang som tidligere: GitHub CI, to uafhængige byte-identiske builds, eksplicit godkendelse af eksakt source SHA og artifact SHA-256, uændrede katalog- og publiceringsgates og fysisk accept før produktion. **Ingen privat Ed25519-rollbacknøgle skal håndteres i den normale proces.**

For ClientFlow **1.3.41 / sekvens 1242** vælges checked-in `client/release/rollback-trust.json` i den nuværende eksplicitte tilstand `enabled=false`, `keys=[]`. Release-builderens 1242-gate accepterer netop dette som *manuel rollback deaktiveret* og validerer stadig den centrale sikkerhedspolitik. Clientens immutable `rollback_verifier._trust()` for sekvens 1242+ **afviser enhver manuel rollback** ved denne tilstand. Der findes ingen fallback til usigneret root-rollback, heller ikke med `--permit-file`. Manglende, ødelagt eller inkonsistent trust skal fejle lukket både under build og ved manuel rollback. Backend-signering forbliver deaktiveret.

**Der ændres ikke på historiske udgivelser**, herunder 1.3.40/1241, eller på deres hidtidige lokale manuelle rollbackregler. Nye 1242+-klienter kan ikke bruge manuel rollback uden en fremtidig separat godkendt signeringsimplementering. **Automatisk gendannelse efter fejlslagen aktivering/opdatering** bruger fortsat sin egen transaktion og er ikke afhængig af manuel rollback-permit. Fysisk test er stadig nødvendig.

## 71A-leverancens grænse

Dette er en **kildesikkerhedsændring**, ikke en bygget, signeret eller publiceret release. `client/VERSION` forbliver `1.3.40`, release-sekvensen forbliver `1241`, og både katalog, policy og rollback-trust JSON er uændrede. Der oprettes ingen nøgle, nye Render-secrets eller ændringer på Heidi1. De eksisterende GitHub CI- og releasegodkendelses-workflows er uændrede.

Efter grøn CI på denne branch kan den særskilte 1.3.41/1242 source-identitet stages med samme keyless releaseprocedure, hvorpå fuldt CI, Ubuntu 26.04 build, exact-source reproducibility, sikkerhedskontrakter og fysisk pilot skal bestås. Livestream og Remote Desktop må ikke påstås rettet uden faktiske klientlogs og fysisk bevis. Produktionspublikation kræver selvstændig accept.

## Kontroller og test

- Builderen afviser manglende/ugyldig trust eller policy, inkonsistent disabled+keys, ugyldig Ed25519-trust og forsøg på at genbruge sekvens 1241 til version 1.3.41.
- Builderen accepterer 1242 med eksplicit disabled+no-keys, uden at springe standard releasekontroller over.
- En 1242-kilde med disabled+no-keys afviser lokale manuelle rollbackforsøg, også hvis en permit-sti er angivet; manglende fil afvises ligeledes.
- En historisk 1241-kilde beholder sin hidtidige rollbackadfærd.
- Den skrivebeskyttede preflight angiver manual_rollback_mode=disabled, afviser forkert releaseidentitet og godkender aldrig publikation eller aktivering.
