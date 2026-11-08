# ClientFlow 1.3.43/1244 — kildeforberedelse og fremtidig tre-release-politik

**STAGED SOURCE IDENTITY ONLY — NOT approved, NOT published, NOT catalog-promoted, NOT installed.**

## Beslutning og ændringsgrænse

- `client/VERSION=1.3.43`, `release-input.json` sekvens `1244`, Ubuntu 26.04/amd64 og runtime Python 3.13.14. Dette giver **ingen** releasegodkendelse.
- Denne source inkluderer rettelsen fra hændelsen 2026-11-08, hvor Viborg2 på ClientFlow 1.3.42 fejlede i APT/dracut under `ProtectKernelModules=yes`. Package-service isolationen er korrigeret, men en virkelig fuld APT/dpkg- og dracut-accepttest på isoleret Ubuntu 26.04 er stadig påkrævet.
- Det **eksisterende** production backend-katalog forbliver nøjagtig `catalog_sequence=1243`, `latest_stable=default_install_version=1.3.38`, og 1.3.42 forbliver godkendt men kun scoped pilot; pilotflag skal forblive **fjernet**.
- `CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1` forbliver aktivt i Render indtil den nye godkendte installer er publiceret og fysisk testet.
- Ingen 1244-bundlebytes, kildecommit, candidate SHA-256, installer SHA-256 eller approval reference kan påstås på source-stage. De findes først efter bygge- og godkendelsesworkflow.
- Manuel (manual) rollback er stadig **disabled**. Durabel failed-activation recovery bevares, men må ikke erklæres fysisk bestået alene ud fra kode/regressionstests.

## Den nye permanente politik

**Efter særskilt 1244-katalogpromovering** må backend-kataloget kun indeholde gældende releaser fra sekvens 1244 og opefter, i strengt stigende release-sekvens og maks. tre i alt. Kun den nyeste kan være stable/default for fresh install; de øvrige må være eksplicit godkendte, kompatibilitetsbegrænsede update-kandidater. Et releasenavn i en dropdown er ikke en automatisk downgrade-/rollback-tilladelse.

| Efter godkendt publicering | Tilladte kandidatidentiteter |
| --- | --- |
| 1.3.43/1244 | Kun 1.3.43 |
| 1.3.44/1245 | 1.3.43, 1.3.44 |
| 1.3.45/1246 | 1.3.43, 1.3.44, 1.3.45 |
| 1.3.46/1247 | 1.3.44, 1.3.45, 1.3.46 |

Catalog-validatoren forberedes nu med `max_selectable_versions=3`, `max_installable_versions=1` og `keep_blocked_metadata=false`, **men kun når catalog_sequence>=1244**. Den nuværende 1243-katalogadfærd bevares frem til en sikker overgang.

Den aktive Render-store indeholder i dag en **midlertidig fem-release-overgang** 1.3.38–1.3.42. Denne source-stage hverken opretter eller sletter godkendte bundles. Retention-prune skal fortsat nægte en rydning, så længe catalog/default, lokale aktiverede klienter, credential-bindings, deployment/recovery, eller installationskoder afhænger af ældre bytes. Tre-release-politikken efter nulstilling betyder maks. tre godkendte, valgbar releases; den skal ikke forveksles med det antal bundles, der sikkert kan fjernes *i øjeblikket*.

## Gated rækkefølge

1. Merge kun ændringsfiler efter fuld grøn CI og smoke test. Kør `python scripts/clientflow_1244_source_preflight.py` (read-only) og kræv `source_stage_ready=true`, alle autorisationsfelter `false`.
2. Fastfrys præcis main commit. Byg via `.github/workflows/release-build.yml`, med eksakt SHA og SHA-verificeret runtime-input transport; kræv to byte-identiske candidates, Ubuntu 26.04 host-executable gate og audit.
3. Separat menneskelig godkendelse via `.github/workflows/release-approve.yml` baseret på eksakte candidate- og installer-SHA256. Gem efterprøvet godkendelsesreference. Den godkendte TAR må **ikke** bygges om under samme release-ID.
4. Særskilt transition-plan for Render-store: permanent policy max tre, men **ingen prune** før verificeret ekstern recoverykopi, slut på gamle klientafhængigheder og eksplicit godkendt staging/rotation. Den nuværende fem-pakke store kræver en selvstændigt revideret transition; ingen `--confirm-prune` eller tilbageførsel af security gate i denne fase.
5. Først efter godkendt immutable 1244-TAR og sikkert publiceret kopi: nyt katalog med **kun** 1.3.43 som stable/default, `catalog_sequence=1244`, ny retention metadata og en kontrolleret afvikling af fresh-install-pausen. Ingen katalogpromovering uden 1244-bundle på disk eller vedvarende valid SHA-kontrol.
6. På Viborg2 (testklient) gennemfør ren Ubuntu 26.04 install, med kontrolleret identitets-/token-rotation, derefter fresh-install af eksakt godkendt 1244. Verificér kiosk, Wayland/Chrome, System, kalender, Livestream første HLS-segment, Remote Desktop, admin-terminal, normal Ubuntu APT/dpkg/dracut-update, genstart/reconnect og efter-boot services.
7. Først efter grøn fysisk Viborg2-accept gentages ren Ubuntu 26.04 installation på Heidi1. Begge er **testklienter**, ikke produktionsblokerende deployment-kandidater.
8. **Efter** begge testklienter er fri af 1239–1243, ingen aktive ældre deployments/token-bindings/fresh-installs/recovery, og alle historiske oplysninger er bevaret: godkend særskilt sletning af gamle **aktive** TAR-bundles. Sletning er irreversibel og udføres ikke i source-stage.
9. Fremtidige 1245+ releases kræver altid selvstændig build/approval/physical-or-isolated-test og rotation af den ældste, **kun** når afhængigheds- og auditkontrollerne passer. Nye friske klienter installerer altid den seneste stable.

**Ingen dele af denne branch geninstallerer Viborg2 eller Heidi1, ændrer Render-flag, sletter pakker eller foretager ændringer i produktion.**
