# ClientFlow 1.3.44 / 1245 – R2 byte-binding og sikkert pilotkatalog

**Kun source-staging – ingen pilotautorisation eller deployment.** Udgangspunkt er den seneste friske main-ZIP fra 14. november 2026 (`385c9a0834ad4241c1e65b36073ae07574a6bff7`). Der ændres **ikke** releasebytes, GitHub-arkiv, Render release-store, releasekatalogets aktive version, Render-miljøvariable eller Viborg1.

## Godkendte bytes (uændrede)

| Felt | Godkendt værdi |
|---|---|
| Release | `clientflow-1.3.44-seq-1245` |
| Oprindelig source commit | `06857104952ebb40bf1394c423c01332d28f8d5e` |
| Kandidat SHA256 | `ffe58332c8e3b263e00f299e363dc95ecb9ac7e0176fd51888be98fecad9bd97` |
| Installer SHA256 | `fc843b6b37772996ecbfa67ff08a0e6f372443bf7d6104ca28d616855bc5737a` |
| Approved TAR SHA256 | `28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5` |
| Approved TAR size | `223610880` bytes |
| Approval reference | `CF-1.3.44-1245-20261114-0685710-ffe58332-R2` |
| GitHub approval run | `43640050058` |
| Approved GitHub archive tag | `clientflow-1.3.44-1245-approved-transport` |

Render-store audit (operatørudskrift): Approved 1244 og 1245, `invalid_artifacts=[]`, `RELEASE_STORE_AUDIT=PASS`, rollback deaktiveret. Dette dokument udsteder **ikke** en ny sikkerhedsgodkendelse; det registrerer de allerede kontrollerede bytes. Den oprindelige 1245 TAR må aldrig genbygges med den nye policy-source.

## Hvorfor ændres det aktive katalog ikke endnu?

Den aktive `backend/service1/clientflow_release_catalog.json` skal stadig have **kun 1244**, `latest_stable=default_install_version=1.3.43`. Det nye `clientflow_release_catalog_1245_pilot.stage.json` er et **ikke-aktivt, gennemtestet stagingforslag** med 1244 som eneste stable/fresh-install og 1245 som `supported`, `in_place_update`-only, fra **præcis 1.3.43 til 1.3.44**. Derved kan kildeændringen merges uden at tilbyde en ny deploymentversion i produktions-UI.

`clientflow_pilot_1245_approval.json` fastholder nu de eksakte R2-bytes, men **`approved` er fortsat `false`**. Selvom miljøvariablen `CLIENTFLOW_1245_PILOT_CLIENT_ID=3` ved en fejl sættes, afviser pilotguarden deployment. Eksisterende flags for 1241/1242/1243 skal fortsat være tomme. Rollback-trust, reset-/decommission-politik og fresh-install-suspension ændres ikke.

## Før fysisk pilot kan autoriseres

1. CI på det nye policy-commit skal være grøn; preflight skal vise samtlige ni kontroller bestået.
2. **Fysisk fallback** skal dokumenteres og gennemgås ved Viborg1: Lokal skærm, tastatur, strøm, admin-login (`cfadmin`) og kendt beredskab hvis fjernadministrationen falder ud. Den seneste skrivbeskyttede 1244-baseline viste PASS for aktiv version/symlink/registreret bundle-SHA/godkendelsesreference og ca. 451,7 GB ledig disk, men **ikke** en praktisk recoverytest.
3. Før næste autorisation skal en ny kontrollant verificere 1244 på den fysiske klient, 1245 i Render-store, lokale installations-/aktiveringsforudsætninger og sikker mulighed for at standse forsøget. Ingen manuel rollback må åbnes uden separat tilladelse.
4. **Særskilt eksplicit operatørgodkendelse** er nødvendig til næste kodeændring: flyt den gennemgåede staged-katalogpost til den aktive katalogfil, og ændr først derefter `approved` til `true` i det eksakt byte-bundne låsdokument. Begge ændringer samt tests og SHA256-manifest skal fortsat passere GitHub CI og Render deployment. `CLIENTFLOW_1245_PILOT_CLIENT_ID=3` skal være default-off indtil særskilt aktivering.
5. En pilotinstallation kræver en udtrykkelig superadminhandling med begrundelse, og må kun rettes mod klient-ID 3 fra 1244 til 1245. Stop ved enhver fejl eller manglende fysisk fallback. Funktionel Livestream-billedlevering er **ikke** bevist af systemd eller 1245-buildet alene.
6. Først ved dokumenteret vellykket pilot kan **en ny, separat stabil promotion** sætte `latest_stable` og `default_install_version` til 1.3.44 i samme kontrollerede katalogændring. Ældre approved bytes bevares til historik efter tre-release-politikken; ingen automatisk udrulning eller rollback åbnes.

## Skrivebeskyttede checks

```bash
python scripts/clientflow_1245_source_preflight.py --repo-root .
python scripts/clientflow_1245_pilot_policy_preflight.py --repo-root .
python scripts/clientflow_1245_r2_pilot_preflight.py --repo-root .
python -m pytest -q \
  scripts/tests/test_clientflow_1245_r2_pilot_stage.py \
  scripts/tests/test_clientflow_1245_pilot_policy_preflight.py \
  backend/tests/test_clientflow_1245_exact_single_client_pilot.py
sha256sum --check --strict SHA256SUMS.txt
```

Disse checks muterer ikke produktionsdata, og `PASS` betyder **kun kildekandidat klar til CI**.
