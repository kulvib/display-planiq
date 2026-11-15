# ClientFlow 1.3.44/1245 – én fælles stabil katalogversion med særskilte driftsgates

Dato: 15. november 2026. Denne ændring afløser den midlertidige todelte
1244-stable/1245-update-only-arkitektur. Den tidligere pilottilladelse og den
frosne 1244-baseline forbliver revisionsspor; de gamle katalogfiler er ikke
længere aktive standarder.

## Godkendt versionsmodel

Det **aktive** `clientflow_release_catalog.json` indeholder præcis én release:
`clientflow-1.3.44-seq-1245`, `status=stable`, `installable=true`,
`update_allowed=true`, med modes `fresh_install` og `in_place_update`.
`latest_stable=default_install_version=1.3.44`. Katalogsekvensen er `1245`.
1244 findes fortsat i det beskyttede Render-arkiv som recovery-baseline,
men kan ikke vælges som en alternativ installationsstandard eller udrulles
som manuel rollback via kataloget.

Det er samme godkendte R2-TAR, der anvendes i begge installationsveje:
- SHA256: `28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5`
- Størrelse: 223610880 bytes
- Kilde: `06857104952ebb40bf1394c423c01332d28f8d5e`
- Godkendelsesreference: `CF-1.3.44-1245-20261114-0685710-ffe58332-R2`

## Vigtige adskillelser: stabil versionsidentitet != udrulningstilladelse

**Fysisk Viborg1-pilot er IKKE gennemført eller accepteret ved denne merge.**
Viborg1 kører fortsat 1244. 1245 kan kun bestilles som en snæver,
kontrolleret pilot til backend klient-ID 3, nøjagtigt 1244 -> 1245, hvis
`CLIENTFLOW_1245_PILOT_CLIENT_ID=3` **og**
`CLIENTFLOW_1245_PILOT_ARM_REFERENCE` er sat til den eksakte godkendte R2-reference.
Begge flags er som udgangspunkt ikke sat. En delvis aktivering afviser anmodningen.
Der kræves lokal fysisk adgang, `cfadmin`, fungerende netværk, kendt recovery,
manuel superadmin-bestilling, opfølgningskontrol af livestream/remote desktop,
netværk og reboot. Fejl skal stoppe forsøget. Ingen automatisk klientopdatering.

**Alle andre in-place-opdateringer til 1245 er hard-blocked** af
`clientflow_1245_fleet_acceptance.json` med
`physical_pilot_accepted=false`, uanset hvilke
`CLIENTFLOW_STABLE_ROLLOUT_*`-værdier der måtte sættes.
Først efter særskilt godkendt fysisk accept kan denne fil ændres i
et senere, særskilt CI-gatet pull request; den eksisterende stabile
rollout-bølgebegrænsning på højest 25 eksplicitte klient-ID'er gælder fortsat.

**Nyinstallationer er ligeledes hard-blocked**, indtil positiv fysisk
accept findes i den samme reviewede fil **og**
`CLIENTFLOW_FRESH_INSTALL_SUSPENDED=0` er verificeret og bevidst frigivet.
Låsen kontrolleres selv hvis miljøflaget ved en fejl mangler.

Hverken merge af denne kode, en Render redeploy eller visning af `stable`
udløser installation. Rollback/downgrade må ikke manuelt aktiveres.
`rollback-trust.json` bevares deaktiveret. Det er stadig kun lokal
automatisk recovery inden for eksisterende klientkontrakt, der kan benyttes.

## Kontroller før fysisk pilot

1. Alle GitHub CI og single-node smoke-tests er grønne på den nye main.
2. Read-only Render store-audit bekræfter 1244 + 1245, uændrede SHA256 og
   retention (seneste tre godkendte, når de findes).
3. Render pilotflag er uaktiverede indtil udtrykkelig operatørbeslutning.
4. Viborg1 har lokal adgang via cfadmin, skærm/tastatur og 1244-baseline.
5. Pilot aktiveres snævert og efterfølges af fysisk/funktionel verifikation.
6. Accept af andre klienter og nyinstallationer kræver derefter særskilt
   godkendelse og ny CI-gated kodeændring.

Ingen sikkerhedstest må deaktiveres for at få dette igennem CI.
