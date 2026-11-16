# PlanIQ Display 61B-2C – sikker status fra ClientFlow-releasecontroller

**Grundlag:** `display-planiq-main(20261116-151123).zip` fra 16.11.2026. **Leverance:** kildekode/tests til isoleret GitHub-branch. **Ingen** ny signeret release, ingen ændringer i Render-miljøvariabler eller på fysiske klienter.

## Formål og afgrænsning

ClientFlows eksisterende update-controller og release-transaktion er fortsat **eneautoritet** for deploymentbinding, godkendelse, staging, aktivering, health-check, automatisk rollback og recovery. Den nye 61B-2C-status er **advisory-only**: fejlet eller blokeret visning ændrer aldrig disse transaktioners resultat. Der findes ingen nye start/stop/reboot/approve-API'er.

En ny, ikke-følsom lokal marker ` /var/lib/clientflow/release-status/state.json` skrives atomisk af root-controlleren; directory = `0755`, fil = `0644`. Forlader kun en reduceret, verificerbar visning af deployment UUID, release-ID, fase, revision og seneste ændringstid. **Ingen** autentifikationstoken, DPoP-nøgle, kandidat-hash, approval-reference, kommandoargument eller interne fejlspor udstilles. Root-ownership/symlink/mode/size kontrolleres af læseren. Korrupt/usikker/forældet aktiv status vises som en advarsel; aldrig som succes.

Markerens faser: `preparing`, `staging`, `activating`, `post_activation_check`, `rolling_back`, `recovery_required`, `completed`, `rolled_back`, `cancelled`. `completed` udledes kun, når den lokale controller har **durabelt** `activation_succeeded` **og** backend-/controllerflowet returnerer `succeeded`. Det er ikke en påstand om verificeret fysisk kioskoplevelse eller genstart af Ubuntu.

## GUI og drift

- Statusagentens **eksisterende** `update_maintenance`-felt og status heartbeat genbruges. Ingen ny polling og ingen nye Neon-tabeller eller normal-sti-queries.
- Ubuntu/firmware-status har forrang. Observeres to samtidige aktive maintenance-kontrakter, vises `recovery_required` som en tydelig konflikt – **selve opdateringslåsen ændres ikke** i dette trin.
- Lokal tekniker-GUI og Software i Control Room skelner ClientFlow fra Ubuntu/firmware, viser kun statiske, ikke-følsomme beskeder og skelner rollback fra succes. `updated_at`/revision ændres kun ved ændring af fase/operation, så samme phase gentaget ikke giver unødige statusdataskrivninger.
- En statusfil uden root-ejerskab, med symlink, world/group-write, ugyldig JSON eller længerevarende forældelse må ikke fremstå som et gennemført deployment.
- Hvis den offentlige statusmarkør ikke kan skrives, fortsætter den **eksisterende** privilegerede transaktion uændret og rapporterer problemet i systemd-journalen. Mangel på visning må aldrig fremkalde en rollback eller ny aktivering.

## Kritisk begrænsning: fullscreen på tværs af release-swap

61B-2B's fullscreen-GTK-proces er ejet af `clientflow-display-runtime.service`, som standses under `_quiesce_runtime` ved selve ClientFlow-aktiveringen. **61B-2C gør ikke krav på, at denne GTK-proces kan forblive synlig kontinuerligt gennem systemd-unit-/symlink-handoffet.** Der ændres bevidst ikke på `transaction.py`, `_health_check`, rollback-låsen eller systemd-targetets opstartsafhængigheder. En eventuel *uafbrudt* release-overgangsskærm kræver et særskilt, uafhængigt, fysisk testet host-supervisor-design. Til dette tidspunkt vises release-faser i lokale/centrale statusflader, hvor runtime er oppe.

Tilsvarende er en **tværgående** eksklusiv OS/firmware/ClientFlow-installationslås endnu ikke etableret i samme transaktionelle autoritet. At statusagenten kan afsløre overlap er ikke samme som at forhindre det. Dette er en stop-gate før en ny signeret fysisk klientpilot.

## Tester og gate

- Kør `PYTHONPATH=client/runtime:client/release/lib:backend python -m pytest -q backend/tests/test_clientflow_61b2c_release_visibility.py`.
- Kør 61B-2A/B-regressionerne og eksisterende releasecontroller-/recovery-/GUI-kontrakter.
- Kør **alle** GitHub CI-jobs og frontend build, inklusive SHA256-verifikation.
- Kontroller at release-input, katalog, approval, migrationskæde og eksisterende `1.3.44/1245` er bit-uændrede.
- Deploy kun almindelig backend/frontend efter grøn CI og godkendelse. Ingen installeret 1.3.43 eller 1.3.44 får ny kode fra Render-redeploy alene.
- Før fysisk pilot: design og test stabil fullscreen-handoff og tværgående installationslås, byg ny separat **signeret** ClientFlow-release, gennemfør preflight/rollback-audit og kræv eksplicit fysisk pilotaccept. Fleet, nyinstallation og DB-cutover skal forblive lukket.
