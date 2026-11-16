PlanIQ Display / ClientFlow – samlet 61B-2I kilde- og testpakke
Dato: 16. november 2026
Kilde: display-planiq-main(20261116-173221).zip – kontrollér mod aktuel main før upload.

Branch:
  feature/display-61b2i-preclaim-shared-lock-20261116

Denne ZIP er en BRANCH-PATCH. Den indeholder ikke en ny klientinstallation,
release-kandidat, signatur, approval eller fysisk pilotautorisation.

UPLOAD:
  1. Opret branchen fra den præcise main, som ZIP'en blev baseret på.
  2. Upload filerne med bevaret mappestruktur; brug én samlet commit/PR.
  3. Kør HELE GitHub CI, inklusive Ubuntu-preclaim, platform og host-kontrakter.
  4. Hvis CI er rød: ingen merge, ingen Render-deploy, ingen klientinstallering.
  5. Efter grøn CI og review: merge/redeploy som normalt; gates bliver lukkede.

PATCH (alle relevante ændringer i én batch):
  client/release/lib/clientflow_release/install_coordinator.py
  client/runtime/clientflow_runtime/install_coordinator.py
  client/release/lib/clientflow_release/cli.py
  scripts/clientflow_61b2g_release_source_gate.py
  backend/tests/test_clientflow_61b2i_preclaim_shared_coordinator.py
  backend/tests/test_clientflow_61b2g_release_source_gate.py
  docs/CLIENTFLOW_61B2I_PRECLAIM_COORDINATION_20261116.md
  README_61B2I_PRECLAIM_LOCK_ONE_BATCH_20261116.txt
  SHA256SUMS.txt

BESKYTTELSE:
  - Preclaim Ubuntu/apt låser nu den eksisterende root-ejede installation journal.
  - Kanonisk UUIDv5 baseres på bundle-SHA256 og tillader exact-source recovery.
  - Root-ejet, nonblocking execution-lock hindrer to samtidige preclaim-apt-runs.
  - Ved fejlet preclaim forbliver journalen aktiv; ingen automatisk unlock.
  - Resume af pending install genbruger oprindelig fresh_install UUID.
  - Post-activation resume afvises allerede før hostens apt-kommandoer.
  - Inaktivt preclaim-katalog fra færdig/afvist installation behandles kun som
    ikke-konflikt, hvis både filerne og sikkerhedsrettighederne er korrekte.
  - Den offline, read-only release-kildegate kræver preclaim-låsen.

BEGRÆNSNINGER:
  - De første OS-updates på en fysisk Ubuntu 26.04-klient er ikke testet her.
  - Preclaim-ejerskab frigives efter sund Ubuntu tilstand og før CF-kode. Hvis
    anden vedligeholdelse vinder mellemrummet, vil første install-claim STOPPE.
  - Hverken first-install Wayland-handoff, kiosk-genstart eller ny release er
    testet på rigtig hardware. Afvent signeret release og særskilt fysisk pilot.
  - 1.3.44 / 1245 må IKKE genbruges til ny kildekode. Release-build-gate STOP.
  - Alle pilot/fleet/fresh-install/cutover-gates forbliver lukkede.

LOKALE TESTS:
  - 95 fokuserede tests: PASS efter kildeændring før sidste README-tilføjelse.
  - 807 scripts/tests PASS; 1 kunne ikke køre uden Git-metadata i bruger-ZIP.
    2 yderligere scripts/tests er miljøafhængige og udeladt fra lokal kørsel.
  - Fuld backend-indlæsning er ikke mulig her: sqlmodel mangler lokalt.
  - GitHub CI er obligatorisk og endelig accept-gate; der er ingen auto-merge.
