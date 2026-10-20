# Control Room P3 – UI-forenkling og accept

Kilde: frisk `display-planiq-main(20261020-165309).zip`.

## Afgrænsning

- Topbjælke fremhæver nu kun forbindelse, ikke-normal aktuel handling, aktuel browserstatus, eventuel ikke-verificeret kalendergenstart og netværksfejl. Vellykkede boot-/genstartshændelser bevares i Diagnostik → Tekniske detaljer → Lifecycle / strøm.
- Browser-ukendt er neutral; kun dokumenteret browser-OK må blive grønt.
- Diagnostik begynder med aktuel status og problemer eller ubekræftede felter. Gentagne driftsoversigter og alle rå felter forbliver tilgængelige som eksplicit fold-ud med `aria-expanded`.
- Diagnostics-adgangens hjælpetekst følger gældende `superadmin || viewer` uden at ændre RBAC.
- Mobil: bedre chip-ombrydning og tydelig vejledning for vandret rulning i klientlisten.
- Ingen backend, database, installer, klientrelease, Render-konfiguration eller statustransport er ændret.

## Accept (GitHub CI og live efter deploy)

1. Desktop og 320/375px mobil + liggende mobil: ingen sidebredde-overflow; chips kan læses, knapper betjenes med tastatur og touch.
2. Online normal klient: ikke redundant `normal`- og vellykket genstartchip i topbjælken; browser ukendt neutral, fejl rød.
3. Afventende genstart og kalenderfejl forbliver synlige som aktive hændelser.
4. Historiske genstarter og kalenderstatus findes i tekniske Lifecycle-detaljer, selv hvis de ikke vises øverst.
5. Diagnostik: fejl og ubekræftede services øverst; alle tekniske sektioner tilgængelige via fold-ud.
6. Viewer kan stadig se Diagnostik; andre roller har uændrede rettigheder.
7. Ingen ekstra databaseforespørgsler, pollingændringer eller client-release promotion.

Production UI-accept er ikke gennemført af denne kildekodeleverance.
