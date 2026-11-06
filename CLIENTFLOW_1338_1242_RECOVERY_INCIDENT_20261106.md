# ClientFlow 1.3.38 → 1.3.41 fysisk pilot: 6. november 2026

**Status: FYSISK PILOT FEJLEDE. Ingen ny release, ingen udvidet pilot og ingen opdatering af standardversionen.**

## Bekræftet hændelsesforløb på Viborg2 (ID 2)

- 1.3.38/1239 var aktiv. 1.3.41/1242 blev downloadet, hash-verificeret og staged.
- Activation intent blev registreret ca. 17:57 dansk tid. `automatic_rollback_failed`
  blev registreret kl. 16:57:25 UTC. ClientFlow-runtime og fjernadministration stoppede.
- Et efterfølgende deployment blev bestilt efter backend havde registreret `recovery_failed`,
  men lokal activation intent var stadig åben. Ny staging blev korrekt blokeret lokalt.
- Kontrolleret fysisk recovery den 6. november genoprettede 1.3.38 og bekræftede
  `rollback_health_verified`, `automatic_rollback_completed`, `activation_intent=None`,
  `NeedDaemonReload=no`, samt aktive væsentlige runtime-tjenester.
- Anti-rollback højvandsmærket **forbliver 1242**; staged 1.3.41 og den oprindelige
  hændelseshistorik må ikke slettes eller omskrives.
- Opdateringstimeren på Viborg2 blev efter recovery efterladt **inaktiv** med vilje;
  backendpilotflaget for 1242 blev deaktiveret i Render.

## Sandsynlig rodårsag og begrænsning

Den historiske 1.3.38-controller har `ProtectHome=yes` og ændrer ACL'er i
`/home/clientflow-kiosk` under både activation og rollback. Den nyere controller
bruger `ProtectHome=tmpfs` og **kun** `BindPaths=/home/clientflow-kiosk`.
Denne forskel passer med hændelsen og forklarer, hvorfor en `daemon-reload`
under en allerede kørende unit ikke kan ændre den eksisterende proces' sandbox.
Men den oprindelige 1.3.38-transaktion logger kun exception-typen; vi har derfor
ikke en fuld, definitiv fejltrace fra den gamle binær.

## Denne kildeløsning (ikke en publiceret klientrelease)

1. Den eksisterende **1.3.38-controller-bridge** kan kun foretages eksplicit af root
   på en lokalt verificeret, aktiv 1.3.38, efter at opdateringstimeren er stoppet
   og backend ikke har nogen aktiv deployment. `--check` er skrivebeskyttet;
   `--apply --confirm-clientflow-1338 --confirm-backend-idle` ændrer kun en
   præcis systemd drop-in og genindlæser systemd. Ingen release-/stateændring.
2. Backend behandler `recovery_failed` som en **udestående genopretningshændelse**,
   selvom deployment-rækken er terminal. Nye autorisationer blokeres, indtil
   superadministrator har verificeret den fysiske maskine og afgivet en auditlogget
   kvittering. Kvitteringen muterer ikke den originale terminale deployment.
3. `scripts/clientflow_local_recovery_attestation.sh` er en root-read-only lokal
   kontrol af aktivt release-symlink, uafsluttet intent, konkret rollbackhistorik,
   systemd reload-gate og kritiske tjenester. Den registrerer intet i backend.
4. Klientdetaljerne viser en særskilt recovery-lås og kræver eksplicit kvittering.

## Operationel rækkefølge på Viborg2

1. Bevar 1.3.38; **ingen** ny update, reboot eller sletning af state.
2. Afklar/annullér eventuel senere `authorized`/`verified` deployment i
   PlanIQ Display (en activation må ikke annulleres via denne kontrol).
3. Verificér fysisk normal kioskdrift, kør read-only attestation og kontroller
   klientens aktuelle version og at ingen opdatering kører.
4. Kvittér tidligere `recovery_failed` gennem superadmin-UI. Dette genstarter
   ingen opdatering og kvitterer ikke for fremtidige pilots.
5. Hvis en **ny, særskilt autoriseret fysisk pilot** planlægges, forbered
   1.3.38-bridge på den fysiske klient (`--check` før `--apply`). Kræv normal
   CI, backend-pilotautorisation, kontrolleret genstart og fysisk accept.
6. En eventuelt rettet klientrelease skal have **ny kildeidentitet og sekvens**;
   1.3.41/1242 er immutable og må ikke rebygges med ændrede bytes.

## Test- og releasegates

Ingen tests må svækkes. Kræv grøn backend/frontend CI, migrations- og
sikkerhedskontrakter, isolated recovery/activation-tests og fysisk verifikation
af ægte update+rollback på Ubuntu 26.04. Denne branch giver **ikke** generel
publicerings- eller rolloutautorisation.
