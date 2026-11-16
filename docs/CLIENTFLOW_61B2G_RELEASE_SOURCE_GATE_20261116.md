# PlanIQ Display 61B-2G — samlet, skrivebeskyttet release-/pilotklargøring

Kildegrundlag: `display-planiq-main(20261116-163837).zip`, GitHub `main` `b891cd68d08acc6811456043e50a5151fe15511b`. Denne levering er **kun offline kildekontrol, tests og dokumentation**. Den ændrer ikke en installeret klient, releasecontroller, OS-/firmwarebroker, signatur, backend, miljøvariable eller DB-spærringer. Ingen ny release er bygget, signeret, godkendt eller publiceret.

## Hvad kontrollen beviser

`python scripts/clientflow_61b2g_release_source_gate.py --repo-root . --source-only`:

- Kontrollér alle poster i den kanoniske `SHA256SUMS.txt` uden at følge symlinks på filniveau, og afvis dubletter, path traversal, manglende kritiske filposter og hash-mismatch.
- Kræv ens kilde i de to installer-koordinatorimplementationer, tilstedeværelse af integrationspunkter i releasecontroller, direkte rollback og systembroker, den signerede host-service, beskyttet GTK4-screen og korrekt payload-/wheel-bygning.
- Kræv, at release-build workflowet indeholder kilde-SHA, separat runtimekontrol og reproducerbarhedsbevis, og at release-approve workflowet kræver eksplicit godkendelse af både bundle- og installer-hash.
- Kontrollér versionsmyndighederne `client/VERSION` og `client/release/release-input.json`.
- Foretag **ingen netværks-, disk-skrivnings-, sudo-, systemd-, DB-, Render- eller GitHub-operationer**. Ingen miljøhemmeligheder læses. Rapporten indeholder aldrig deployment- eller pilotgodkendelse.

`python scripts/clientflow_61b2g_release_source_gate.py --repo-root .` **skal give STOP (exit 2) på denne `main`**, selvom kildeintegriteten er OK, fordi kildens identitet stadig er 1.3.44/1245. En ny candidate kræver både versionsnummer og release-sekvens **strengt over** den stabile baseline. Den første mulige identitet er 1.3.45/1246, men denne levering træffer **ingen beslutning om** kandidatidentitet eller signering.

Ved en ny source-kandidat kan kontrollen højst give `READY_FOR_UNSIGNED_CANDIDATE_BUILD`; det er **aldrig** tegn på en signeret, godkendt eller fysisk prøvet release.

## Hvad kildekontrollen IKKE beviser

- Fuld runtime-input transport, den reproducerbare GitHub kandidatbygning, faktisk attestation, signerede bytes, godkendelse, produceret installer eller promovering. Disse kræver eksisterende separate `release-build.yml`, `release-approve.yml`, klientruntime-test og efterfølgende explicit operatorgodkendelse.
- Reelle DB-flags, antal deployment-targets, installerede klientversioner, fysisk GNOME/Wayland fullscreen, boot-ID, genstart, strømudfald eller tilbageføring.
- At **første factory/fresh-install** kan køre samtidig med OS-/firmwareopdatering: 61B-2F beskriver fortsat dette som en særskilt STOP-gate. Ny-installation skal forblive suspenderet, og en fremtidig factory-lock-integration må aldrig slette `/var/lib/clientflow/install-coordinator` som sideeffekt af 4xx-preclaim-oprydning.
- Kontrol af journal-locks efter reboot eller recovery; det kræver en faktisk udpeget maskine og separat read-only 61B-2F pilot-preflight.

## Foreslået samlet næste arbejdspakke, efter kildekontrol

1. Verificér 6/6 CI på eksakt GitHub commit og `source-only` PASS. Hold produktionens fire gates lukkede. Før udpegning af fysisk testklient: læs faktisk status og version, ikke alene den planlagte version.
2. Forbered en **ny selvstændig kandidat**, først efter godkendelse af målversion/sequence og en kilde-/testopdatering, der ikke ødelægger historiske 1245-policies. Bevar 1.3.44/1245 immutable; ingen omsignering af dens bytes.
3. Kør eksisterende workflow `release-build.yml` med eksakt kilde-SHA og hash-pinnet runtime-input transport; kræv to byte-identiske uafhængige builds samt Ubuntu 26.04 executable proof og attestationsbevis.
4. Kør releasegodkendelse **særskilt** med manuel reference, bundle-/installer-SHA og uændrede godkendelses- og anti-rollback-regler. Et build er ikke en autorisation til at deploye.
5. Opdater kun den **fysisk bemandede** testklient efter separat pilotaccept og dokumenteret rollback-/recoveryplan. First-update og subsequent-swap er to forskellige accepteringsforløb; test host-screen, lås, browserstop, boot-ID, netværk, Control Room-status, return-to-kiosk og fejlet rollback.
6. Fleet, ny-installation, DB-cutover og andre klienter forbliver blokerede, indtil der findes særskilt godkendt fysisk dokumentation. Ingen automatiske deployment- eller installationskald fra denne pakke.

## Tests og upload

`PYTHONPATH=backend:backend/tests:client/release/lib:client/runtime python -m pytest -q backend/tests/test_clientflow_61b2g_release_source_gate.py`.

Ny branch fra kilden: `feature/display-61b2g-release-source-readiness-20261116`. Upload kildefiler i deres mapper og kør alle seks GitHub CI-jobs. **Ingen merge eller Render-deployment før CI er grøn**. Selve fysisk pilot er stadig STOP.
