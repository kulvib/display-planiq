# ClientFlow – transaktionshjælperens filrettigheder

## Verificeret fund, Heidi1 – 22. oktober 2026

Den fysiske 1.3.38 → 1.3.40 → 1.3.38 → 1.3.40-accepttest lykkedes,
men den installerede `release/bin/clientflow-release-transaction` var ikke
kørbar direkte. Repo/ZIP-kilden har mode `0644`, hvilket tidligere gav
payload-medlemmet mode `0644` og efter immutable sealing mode `0444`.
En autoriseret, manuel release-transaktion måtte derfor midlertidigt
startes via den bundlede Python-runtime og wrapperens script-sti.

## Ændring

`client/release/lib/clientflow_release/builder.py` klassificerer fremover
`release/bin/clientflow-release-transaction` eksplicit som direct-exec-payload:

- Tar-medlem: `0755`, uafhængigt af Git-/ZIP-kildemode.
- Installeret og immutable-sealed: `0555`, således at wrapperen kan
  anvendes direkte med sin eksisterende shebang.
- Almindelige datafiler bibeholder uændrede rettigheder.

`test_clientflow_transaction_wrapper_executable.py` verificerer både
ZIP-lignende kildemode, det faktiske tar-medlem og immutable sealing. Testen
kører under den eksisterende Python-testgate i CI.

## Release- og sikkerhedsgrænse

Denne kodeændring reparerer **kun fremtidigt byggede bundler**. Den ændrer
ikke allerede godkendte, immutable 1.3.38/1.3.40-artifacts eller installerede
releasekataloger. Den ændrer heller ikke release-version, sequence,
release-katalog, godkendelsesreferencer eller runtime-autorisation.

Central autorisation/audit for manuelle rollbacks, tilbagekaldelse af
kompromitterede releases og fleet-udrulning skal designes og testes separat.
Ingen eksisterende succesfuld lokal rollback er et bevis for, at disse
centrale sikkerhedskrav er opfyldt.
