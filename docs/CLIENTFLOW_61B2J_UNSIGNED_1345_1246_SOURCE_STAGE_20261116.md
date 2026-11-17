# ClientFlow 61B-2J · usigneret 1.3.45/1246-kildekandidat

## Grænse: kandidat er ikke release

Denne branch samler et fremrykket kildeversionsnummer, præcis release-sekvens,
streng ikke-publiceringsgate og opdatering af historiske regressionskontrakter.
**Intet kandidat-TAR, installationsarkiv, signatur, godkendelsesreference eller
fysisk deployment oprettes ved merge eller Render-deployment.**

- `client/VERSION`: **1.3.45** (kun kildeidentitet).
- `client/release/release-input.json`: **1246** (kun kilde-/byggeinput).
- Den aktive `backend/service1/clientflow_release_catalog.json`: fortsat **én
  stabil og installerbar 1.3.44/1245**, med uændret nøjagtigt godkendt R2-hash.
- `clientflow_pilot_1245_approval.json`: stadig det oprindeligt godkendte
  **1245**-artifact, ikke en signatur for 1246.
- `clientflow_1245_fleet_acceptance.json`: `physical_pilot_accepted=false`.
- DB 61A/B, Render- og ClientFlow miljøgates: ingen ændringer, ingen automatisk
  pilot, fleet, fresh-install eller cutover.
- Ingen klient kan hente 1246 via produktionskataloget, da det ikke er publiceret.

## Adskillelse mellem historiske og nye tests

De historiske 1235–1245-tests må gerne se en fremtidig **præcis 1246-kilde**,
men deres permanente katalog-, rollback- og 1245-approvalbeviser er fortsat
bundet til gamle releases. De gamle read-only preflights accepterer kun de to
konsistente kildepar `(1.3.44,1245)` og `(1.3.45,1246)`; de giver ingen
rettigheder til sidstnævnte. Mismatch og vilkårlige senere versioner afvises.

Release-source-gaten kræver nu også samme eksakte 1245-katalog, 1245-approval
og manglende fysisk accept. Manipuleret releasepolitik afvises selv ved
nyberegnet SHA256-manifest. Byggeegnethed må ikke bruges som bevis for
signering, releasepromotion, kiosk-/Wayland-accept eller fleet-autorisation.

## Krav før videre handling

1. Hele GitHub CI på præcis commit: PASS; eventuelle Ubuntu-skips begrundes.
2. Canonical reproducible **unsigned** candidate build på GitHub, med eksakte
   pinned runtime-inputs og to uafhængige byggere, SHA og kildeattestation.
   Ikke noget fysisk deployment i dette trin.
3. Manuel artefaktkontrol, separat signering og godkendelse efter eksisterende
   releaseprotokol. Der må ikke genbruges 1245-signatur eller approvalid.
4. Skrivebeskyttet Render/DB-/klient-preflight, eksakt fysisk pilotmål og
   udtrykkelig operatørgodkendelse før enhver klientinstallation.
5. Første fabriks-installation, preclaim→first-claim-vinduet, GNOME/Wayland
   fullscreen-handoff, reboot, recovery/rollback og browserstop testes på en
   udtrykkeligt udpeget *testklient*. Ingen auto-promotion ved PASS.

**Åbent STOP-krav:** Preclaim-vinduet mellem gennemført apt-check og erhvervelse
af `fresh_install`-låsen er fortsat en fail-closed race. Et konkurrerende
vedligeholdelsesforløb får installationen til at stoppe og kræver ny preflight;
vi hævder ikke at fysisk flerproceskoordination er afsluttet.
