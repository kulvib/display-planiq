# ClientFlow 61B-2F — manuel rollback i fælles lås og læsebaseret fysisk pilot-preflight

**Grundlag:** `display-planiq-main(20261116-161745).zip`, GitHub main `dc5a8cb6c1c2070c8ab5a5abdb1b55f0c3d0f9d4`.
Dette er kun kildeændringer, tester og en diagnostisk kommando. **Ingen klient er opdateret. Ingen release er signeret eller godkendt.** Stabil 1.3.44/1245, DB-gates, secrets, migrationsfiler og installationsordrer er uændrede.

## En stor sikkerhedsændring, men ikke en omgåelse

1. Direkte **root-initieret manuel rollback** bruger nu samme root-beskyttede `/var/lib/clientflow/install-coordinator` som controlleren og OS-/firmwarebrokeren. Låsen reserveres **efter** eksisterende central signatur-, approval-, mål- og idempotenskontrol, men **før** forbrug af permit, auditjournal eller mutation af runtime. En anden operation afvises uden audit-/systemændringer.
2. `operation_id` er en stabil kanonisk UUID af den signerede permit-ID (eller for historiske installationer en fast kombination af kilde, mål, approval og hash af begrundelse). Det muliggør samme ejers genoptagelse efter processtop, men ikke overtagelse af en anden operations lås.
3. Lock-release sker kun efter `manual_rollback` er skrevet og efterkontrolleret i holdbar lokal state, activation-intent er væk, og aktiv symlink peger på det verificerede mål. Fejl, signaler, afbrudt disk-skrivning og mistanke om usikker recovery **holder låsen**. Ingen automatisk oplåsning, lease, timeout eller nødknap er tilføjet.
4. En ny rent lokal, offline `scripts/clientflow_61b2f_pilot_preflight_readonly.py` kontrollerer host-screen-hash mod aktiv signeret release, aktiv releaseidentitet, systemd-unit/sikkerhedsparametre, installationslås samt OS-/ClientFlow-status. På fysisk host kontrollerer den desuden at host-service er enabled og active. Den bruger kun fil-læsning og `systemctl is-enabled` / `is-active`; ingen backend-opkald, databaselæsninger, write-operationer, restart eller installation. **Output er aldrig godkendelse** (`deployment_authorized=false`, `pilot_accepted=false`). Ved fejl eller ukendt tilstand bliver resultat `STOP` og exitkode 2.
5. Test-rødder må aldrig ramme `/var/lib/clientflow` på den rigtige host. Gå kun via korrekt signeret releasebuild, CI, fysisk godkendelse og separat kontrollant.

## Hvad denne fase ikke påstår

- Fælles lås på **første fabriksaktivering** er stadig ikke fuldt integreret med automatisk updatecontroller. Første aktivering og parallel OS-vedligeholdelse er en særskilt **STOP-gate**, indtil en eksplcit integration og fysisk test findes. Forsøg ikke at omgå controllerens egen systemd-/health-transaktion.
- Host-skærmen ved **allerførste opdatering** kan ikke love uafbrudt fullscreen, da den uafhængige service først installeres under promotion. Kræv et efterfølgende releaseskift med host-service aktiv for at teste fuld kontinuitet.
- CI beviser kilde og testkontrakter; ikke GNOME/Wayland-layer, signaturpipeline, fysisk skærm, strømafbrydelse eller en faktisk recovery. Scriptets resultat er kun et supplerende, lokalt read-only observationsbevis.
- Recovery fra en permanent lås må **ikke** ske ved at slette `state.json` manuelt. Det kræver særskilt dokumenteret godkendelse, korreleret command/permit-ID, aktiv release, journal/health, boot-ID og eventuel verificeret backend-terminalstatus.

## Foreslåede verifikationsgates (før fysisk pilot)

1. GitHub alle seks CI-jobs success på eksakt kildecommit; komplet SHA256-manifest; ingen svækkede/gennemskrevne sikkerhedstests.
2. Read-only Render/DB-gate: fresh install suspended, fleet closed, DB cutover false, ingen nye aktive targets eller fysiske acceptregistreringer. Kun dokumenteret lokal status; ingen ændring af miljøvariabler, låse eller central godkendelse.
3. Signer en **ny separat** immutable klientcandidate med ny release-id/sequence og verificeret releaseproveniens. 1.3.44/1245 forbliver uændret. Oprettelse og godkendelse af denne kandidat er en separat releaseprocedure.
4. Udpeg og verificer én fysisk bemandet testklient. Ingen parallel `apt`, `fwupd`, ClientFlow-opdatering eller manuel rollback. Recovery- og backoutplan samt kontaktpersoner dokumenteres inden ændringen.
5. Første fysisk godkendte opdatering: instrumentér browserstop, statusjournal, installation, genstart kun ved behov, boot-ID, netværk og Control Room-reconciliation. Host-service kan først være klar efter promotion. Ingen automatisk masseudrulning.
6. Efter at **en faktisk signeret release** har installeret host-screen, kør på den bemandede testklient (read-only, som root):

   ```sh
   sudo /usr/bin/python3 scripts/clientflow_61b2f_pilot_preflight_readonly.py
   ```

   Kommandoen er fra den godkendte source-checkout; den skal ikke kopieres ukontrolleret fra internettet. `READY_FOR_PHYSICAL_OBSERVATION` er ikke accept, kun forudsætning for særskilt visuelt tilsyn. `STOP` kræver udredning uden manuel sletning af låsen.
7. Ved næste separat signerede releaseskift: observer visuelt topmost fullscreen under stop/start af `clientflow.target`, også hvis browseren genstarter, inkl. fejlet health og rollback. Bekræft fallback og genstart uden skærmsløjfer. Dokumentér tidsstempler, hash, boot-ID og installeret version.
8. Fysisk accept er særskilt og kræver kontrol af reelle installationer, root-/filrettigheder, service, locked/in-doubt-tilstande, Rollback Permit trust, Render-kontinuitet, backend-journal, Control Room og sikkerhedsflags. **Først derefter** må en yderligere pilot-/fleet-aktivering besluttes.

## Regresionstests

```sh
PYTHONPATH=client/release/lib:client/runtime:backend:backend/tests python -m pytest -q \
  backend/tests/test_clientflow_61b2f_manual_rollback_install_lock.py \
  backend/tests/test_clientflow_61b2f_readonly_pilot_preflight.py \
  backend/tests/test_clientflow_61b2de_install_coordinator_and_host.py \
  backend/tests/test_clientflow_manual_rollback_1241.py \
  backend/tests/test_clientflow_signed_rollback_permit_contract.py \
  backend/tests/test_clientflow_durable_rollback_reporting.py
```

Derudover: alle eksisterende controller-, system-broker-, framebuffer-/fullscreen-, CI-/host-/preclaim-kontrakter på GitHub.

**Forslag branch:** `feature/display-61b2f-manual-rollback-pilot-preflight-20261116`. Merge og Render kun efter CI og reviews. **Ingen fysisk installation** uden separat release- og pilot-godkendelse.
