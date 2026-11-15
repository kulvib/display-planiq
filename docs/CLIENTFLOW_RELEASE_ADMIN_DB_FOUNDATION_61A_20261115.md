# ClientFlow releaseadministration – sikker DB-grundstruktur (61A)

**Basis:** Frisk `display-planiq-main(20261115-135844).zip` fra 15. november 2026.  
**Formål:** Erstatte manuelle Render-baserede pilot-/klientflag med en central, holdbar og auditeret administrationsmodel **uden at aktivere udrulning som sideeffekt af en merge**.

## Fase A – indhold af denne branch

- Ny review-pinnet, additiv Alembic 61A-migration med fire tabeller: `clientflow_release_control`, `clientflow_rollout_wave`, `clientflow_rollout_target`, `clientflow_physical_acceptance`. Ingen eksisterende tabeller ændres/slettes, ingen eksisterende klientcredentials berøres.
- Singleton-policy bootstrapper på eksakt godkendt ClientFlow `1.3.44/1245` R2 med `fresh_install_open=false`, `fleet_open=false`, `cutover_enabled=false`, `revision=1` og præcis bundle-SHA256.
- En ny **superadministrator-only** sektion under Administration: `ClientFlow Releases`. Den viser den stabile målversion, lukkede gates og de seneste kladder. Kun oprettelse/annullering af **inaktive kladder** er muligt.
- Kladder kræver ny password-genbekræftelse, rate limit, servervalideret release-ID, revideret policy, entydige klient-ID'er, maksimum 25 klienter, tidsbegrænset udløb og transaktionsbundet audit. Første pilot er kun Viborg1 klient-ID 3, kildeversion 1244.
- Ingen offentlige eller klientautentificerede API'er til at udstede bølgetilladelser, markere fysisk accept, åbne nyinstallation eller aktivere DB-cutover. Ingen automatiske opdateringer.
- Historisk 59A/60A kildekode/digest og schemafingre bevares; kontraktens reviewed head bliver 61A. Verified old legacy migrations bevarer deres reviderede kildegraf. Skrivebeskyttelse ved automatisk downgrade består.
- De gamle `CLIENTFLOW_*_PILOT_*`, `CLIENTFLOW_STABLE_ROLLOUT_*`, `CLIENTFLOW_FRESH_INSTALL_SUSPENDED`-gates, `clientflow_1245_fleet_acceptance.json`, deploy- og enrollment-ruter er **ikke ændret**. Der er dermed ingen ny autorisationsvej til en fysisk klient i fase A.

## Afgrænsning og obligatorisk gate før merge

Dette er en **produktionssikker fundamentfase – ikke fuld environment-fri drift**. GitHub skal køre hele Python-/frontend-CI, Python-skema kontrakt, migrationer på en tom/eksisterende test-Postgres og single-node smoke. Ingen sikkerhedstest må deaktiveres. Migrationsfejl skal blokere deploy; Render predeploy skal ikke automatisk retry med tab-oprydning, DDL-fallback eller tabt data.

Efter merge og grøn smoke skal `clientflow_release_control` bekræftes read-only som default lukket, og en ny statusoversigt skal fungere for superadministrator. Pilot på Viborg1 må ikke starte endnu.

## Næste særskilt godkendte cutoverfase

Tilføj transaktionelle, tidsbegrænsede klientbundne wave-godkendelser, forbrug af tilladelse under per-client row lock med immutable artifact/SHA og aktuel Status-version, korrekt fysisk accept med revisionsbevis og stærk reauth, styring af fresh-install hold og UI for pause/stop. Migrér først til dobbeltlås, siden til ny DB-autoritet bag reviewed cutover. Gammel env-styring må først fjernes, når alle negative tests og fysisk Viborg1-recovery er dokumenteret. Ingen aktiv klientopdatering må ske blot fordi en politik er `stable`.

## Negative acceptance tests

1. Manglende/mismatchende singleton eller bundle ⇒ HTTP 503 (fail closed).
2. Ikke-superadministrator, impersonation, ugyldig adgangskode, stale revision, forkert klient eller duplikeret ID ⇒ ingen kladde.
3. Kladde giver aldrig deployment, pilot-/fleet-autorisation eller fysisk accept.
4. 1244 TAR og 1245 R2 TAR samt tre-release retention bevares fysisk uændret.
5. Kioskers normale Status-/Display-/System-API'er får nul ekstra Neon-opslag af disse modeller.
6. Alembic-historik, kilder og 60A/59A-digest er fortsat pinned. Ingen rollback/downgrade ændres.
