# PlanIQ Display – 61B-2H: first claim → first healthy activation

**Status:** Kildeimplementering til GitHub CI. Ikke signeret kandidat, ikke fysisk pilot og ingen produktionsautorisation.

**Kanonisk kilde:** `display-planiq-main(20261116-170003).zip` (16. november 2026). Stable approved release `1.3.44 / 1245` må ikke ændres. Næste særskilte kandidatidentitet skal fastlægges og afprøves særskilt.

## Én global installationsjournal

- De to identiske `install_coordinator.py`-kopier understøtter nu også `owner=fresh_install`. Låsens operation-ID er den eksisterende, holdbare `install_id` fra den præcise første claim. Låsen deles på den eksisterende `install-coordinator`-sti med OS, firmware, automatisk ClientFlow-update og manuel rollback.
- Før første consuming backend-claim kontrollerer den rene installationssti eksisterende ClientFlow-installationsspor og låseejerskab. Den nye installation gør krav på global journal **før** den opretter install-state og forbruger claim. Ved crash/resume bruges den oprindelige `install_id` – aldrig et nyt operation-ID.
- Efter et **definitivt** 4xx-svar fra første claim rydder pre-claim-cleanup kun egne, eksakte `release/install-state.json`- og credential-spor. Den sletter **aldrig** `install-coordinator`, som er en global lås. Journalen frigives først efter valideret cleanup. En idle coordinator må være det eneste efterladte spor, når ny CF-kode indtastes.
- 5xx, netværksfejl, uafsluttede lokale ændringer, beskadiget koordinationsjournal og ukendt installer-state er **STOP**. Låsen frigives ikke ved timeout eller procesudløb.
- Første aktivering bruger fortsat den eksisterende root-kontrollerede transaktion, backend-godkendelsesbevis, sundhedskontrol, anti-rollback og rollback. `activate_release` afviser en fremmed eller forkert installationsjournal. Den frigiver `fresh_install`-ejerskab **først efter en holdbar activation commit og verificeret active symlink**, også ved sikker gentagelse efter strømafbrydelse. Ved fejl beholder journalen ejerskab til recovery.
- Ældre, allerede installerede klienter uden `fresh_install`-journal kan fortsat gennemføre deres eksisterende, godkendelsesbevis-krævende first activation. Fravær af journal giver **ikke** en ny godkendelsesvej.

## Release-build STOP-gate

Den manuelle, signerede GitHub release-build-workflow kræver nu den strikte `clientflow_61b2g_release_source_gate.py` for det eksakt checkede commit. `--source-only` må **ikke** anvendes i build-workflowet. Kildecommit med `client/VERSION=1.3.44` og `release_sequence=1245` skal fortsat returnere `STOP_STABLE_SOURCE_NOT_A_NEW_CANDIDATE`. Det forhindrer ny kode under et allerede offentliggjort, uforanderligt release-ID. Ordinary CI / source-only gælder stadig for godkendte historiske kildefiler.

## Afgrænsninger og STOP før kandidat

1. **Preclaim Ubuntu apt-preflight:** `ensure_preclaim_host_readiness` udføres før første consuming claim og den nye globale fresh-install-lås. Den er ikke fuldt serialiseret med en eventuel selvstændig root-initieret Ubuntu-opdatering. Dette er et åbent sikkerheds- og fysisk pilotkrav. Ingen påstand om global serialisering af hele factory/bootstrap-kæden.
2. **Kandidatidentitet:** `client/VERSION=1.3.44`, sequence `1245` er bevidst uændret. Ny kandidat, eksempelvis `1.3.45 / 1246`, er ikke bygget eller signeret. Den strikte release-build-gate giver **STOP** for denne branch, indtil en ny kandidatidentitet og de resterende krav er opfyldt.
3. **Fysisk test:** GNOME/Wayland-hostskærm, første claim (godkendt/afvist), reboot, godkendt first activation og konflikt med OS/firmware er ikke fysisk godkendt. Alle DB-/fleet-/cutover-/nyinstallationsgates bevares lukket.
4. **CI:** Fuld GitHub CI samt Linux-baseret root-/systemd-kontrakt er den endelige gate. Lokale tests kan ikke bevise GNOME/Wayland-handoff.

## Testplan

- Global lock afviser firmware, OS og update, mens first install er pending.
- Definite backend 4xx rydder kun own preclaim state, bevarer coordinator, frigiver owner og tillader ny CF-kode.
- Fremmed `install_id`, corrupt fil, ekstra diskfil eller fremmed owner giver STOP uden deletion.
- Første aktivering skal fortsat kræve backend-approval proof og have holdbart health-verified resultat. Fejl/strømsvigt bevarer låsen; gentaget allerede gennemført aktivering kan frigive korrekt ejerskab.
- CI release-build afviser den eksisterende stable 1245-identitet uden at hente transport eller bygge kandidater.

## Anbefalet næste fase

Efter fuld grøn GitHub CI og produktions-smoketest: integrér den resterende preclaim/apt-serialisering uden at blokere normal factory-recovery. Først derefter oprettes en **særskilt, ny kandidatidentitet**, reproducerbar build, hash-verifikation, manuel signaturgodkendelse og en bemandet fysisk pilot. Ingen automatisk release-promotion og ingen ændringer af live-gates.
