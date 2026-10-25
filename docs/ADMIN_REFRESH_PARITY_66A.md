# PlanIQ Display – administrationsopdatering, fase 66A

## Kildegrundlag og ændringsgrænse

Denne fase tager udelukkende udgangspunkt i `display-planiq-main(20261025-144620).zip` (GitHub `main` efter PR #321, commit `c415818f12f99b60bfa61896f6339546dc16acdd`).

Audit-loggens eksisterende manuelle opdateringsknap er standarden: MUI `Button` med `variant="contained"`, ledende Refresh-ikon, startplaceret indlæsningsindikator og handling øverst til højre i sidens overskrift. Den komponent deles nu på syv administrationsundersider, Control Room/Client List og Kalender.

| Visning | Eksisterende opdateringsvej | Bevarede betingelser |
| --- | --- | --- |
| Audit-log | `setRefreshTick` | Deaktiveret under loading |
| Organisation | `fetchOrganizations` | Deaktiveret under loading; sæsonfiltre uændrede |
| Brugeradministration | `loadData` | Eksisterende liste og organisatorisk data; ingen ændring af brugerformularer |
| Driftsfejl | `reload` | Eksisterende fejl-, rapportdæknings- og historikopdatering |
| Installationskoder | `loadTokens` | Rettighedsmodel og oprettelse af koder uændret |
| Livestreamoversigt | `load` | Ingen ændring i transport eller 15-sekundersvarsling |
| Vedligeholdelse | `load` | Deaktiveret under saving; adgangskodebekræftet ændring uændret |
| Control Room/Client List | `handleRefresh` | Deaktiveret under sorteringslagring; klienter, papirkurv og organisationer opdateres samlet |
| Kalender | `fetchClients(true)` | Eksisterende opdatering af godkendte klienter, med `loadingClients`; markerede dage, sæsonfiltre og gemmeflow påvirkes ikke |

Det er en ren frontend-UX-ændring: ingen backend-, migrations-, klientruntime-, releasekatalog-, signerings-, token- eller streamingændringer.

## Accept og CI

- Alle inkluderede sider viser præcis én manuel Opdater-handling i højre del af den øverste overskrift, med samme visuelle komponent og statusafhængighed.
- Alle handlinger kalder den eksisterende indlæsningsfunktion og bevarer sine sikkerheds-/loading-betingelser.
- Regresionstests: `frontend/tests/adminRefreshParity66a.test.mjs` og opdateret kontrakt for Driftsfejl i `captureStartup15SecondAndRefreshChip.test.mjs`.
- Full frontend CI, lint og build er stadig obligatoriske. Lokalt er kildebaserede tests gennemført; 7 executable tests kræver installerede React/Vite-afhængigheder.

## Udrulning

Kun efter grøn GitHub CI og PR-review. Render frontend deployment og visuel kontrol på alle syv adminsektioner samt Control Room og Kalender er separat accept. Ingen klientrelease er nødvendig til denne UX-ændring.

## Ensartede hjørner og felter – Client List som reference

- **Almindelige inputfelter og valgfelter:** Repoets fælles MUI-tema bruger `MuiOutlinedInput` med `borderRadius: 10` (10 px). Det bruges allerede på Client List og Kalender og er bevaret uden en global stilændring.
- **Sektioner, kort og paneler:** Client List bruger `borderRadius: 2` i MUI `sx` (med temaets 10 px-faktor). De tre hidtil afvigende paneler i administrationsoversigten Livestreams er bragt til samme værdi.
- **Redigerbart inline-felt i Brugeradministration:** En særskilt `1.25`-værdi er normaliseret til `1`, så feltet matcher den globale MUI-inputradius.
- **Tilsigtede specialformer:** Runde kalenderdage, badges/chips, tabelrækker, ikoner og specialbetjeningsknapper bevarer deres form. Der ændres ikke globalt i komponenttemaet eller på klientdetaljer uden for dette scope.
- **Kalender:** Den eksisterende Opdater-handling (`fetchClients(true)`) genbruger nu `AdminRefreshButton` i headerens højre side. Ingen nye API-kald, ændringer i marked-days-hentning, autosave, gem-knapper, klientfilter eller sæsonvalg.

Kontrakterne i `frontend/tests/adminRefreshParity66a.test.mjs` dokumenterer radius-paritet og bevarer kalenderens oprindelige opdateringssemantik.
