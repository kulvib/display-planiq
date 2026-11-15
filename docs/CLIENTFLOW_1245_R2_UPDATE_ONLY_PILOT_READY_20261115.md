# PlanIQ Display – 1245 R2 update-only pilot: source-ready, NOT deployed

**Status:** Kodemæssig forberedelse til særskilt operatørgodkendt Viborg1-pilot. Dette er IKKE en tilladelse til at opdatere Viborg1, ændre miljøflag eller gøre 1245 til stabil standard.

## Godkendte, uforanderlige bytes

| Felt | Værdi |
|---|---|
| Release ID | `clientflow-1.3.44-seq-1245` |
| Source SHA | `06857104952ebb40bf1394c423c01332d28f8d5e` |
| Candidate SHA256 | `ffe58332c8e3b263e00f299e363dc95ecb9ac7e0176fd51888be98fecad9bd97` |
| Installer SHA256 | `fc843b6b37772996ecbfa67ff08a0e6f372443bf7d6104ca28d616855bc5737a` |
| Approved bundle SHA256 | `28c4836536279d04381ad299937c59fce5315df1e817984b0377abdd7c86d6a5` |
| Approved size | `223610880` bytes |
| Approval reference | `CF-1.3.44-1245-20261114-0685710-ffe58332-R2` |
| GitHub approval run | `43640050058` |

**Disse releasebytes ændres ikke af denne kodeændring.** Den oprindelige ClientFlow-klientpakke bygges ikke om, og ingen ny kilde-SHA anvendes som dens proveniens.

## Katalog og sikkerhedsgates

1. Aktivt backend-katalog må nu indeholde præcis 1244 stable/fresh-only og 1245 supported/update-only. `latest_stable` og `default_install_version` er begge stadig `1.3.43`.
2. `clientflow_pilot_1245_approval.json` er byte-bundet til den godkendte R2-pakke. At dette dokument har `approved: true` betyder **kun**, at kilde- og artefaktbindingen er klar til den særlige pilotguard; det udsteder ikke en deploymentordre.
3. Den særskilte 1245-pilot kræver **begge**, eksakt `CLIENTFLOW_1245_PILOT_CLIENT_ID=3` **og** `CLIENTFLOW_1245_PILOT_ARM_REFERENCE=CF-1.3.44-1245-20261114-0685710-ffe58332-R2`. Ingen af disse værdier sættes af kildeændringen. Operatøren må ikke sætte nogen af dem før separat, eksplicit godkendelse af den fysiske pilot.
4. Hvis blot én af de to miljøvariabler mangler, er forkert, eller et af historiske pilotflag for 1241/1242/1243 fortsat er aktivt, afviser backend en 1245-deployment. Dette kontrolleres både før og efter databasens klientlås.
5. Klient-ID 3 skal være online og rapportere præcis `1.3.43`, målrelease skal være `1.3.44/1245` i `in_place_update`, og en superadministrator skal afgive en reel begrundelse. Der er hverken automatisk opdatering, pre-activation repair, downgrade eller manuel rollback.
6. Den godkendte 1245-bundle er allerede publiceret i Render release-store. Read-only retention-kontrollen viste to godkendte releases (1244 og 1245), korrekt SHA256, ingen ugyldige filer og fortsat rollback spærring.
7. `CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1` bevares. Denne kildeændring hæver ikke nogen drifts-suspension.

## Fysisk fallback

Operatøren har bekræftet fysisk adgang til Viborg1 samt skærm, tastatur og lokalt `cfadmin`-login. Den skrivbeskyttede baselinekontrol af 1244 viste alle syv kontroller `PASS` og ca. 451,7 GB ledig disk. **En faktisk fejlinduceret recoverytest er endnu ikke udført**, og dette dokument må ikke fortolkes som en sådan test.

Før en konkret pilotordre: (1) gennemgå fysisk adgang og netværk; (2) verificér igen aktiv 1244 og fravær af pending activation; (3) bekræft eksakt R2-store-integritet og grøn GitHub CI/Render deploy; (4) fastlæg stopkriterier og fysisk beredskab. Kør ikke manuel nedgradering, genudstedelse af gamle identiteter eller maskin-reset ved en fejlet pilot. Indsaml først registreret aktiveringsstatus og recoveryjournal fra klienten; standse ny udrulning og følg den særskilt godkendte root-kontrollerede recoveryprocedure. Funktionel godkendelse kræver reelle billedbuffere i Livestream, Remote Desktop, netværk, cookie-refresh og korrekt Control Room-status – ikke bare aktive systemd-tjenester.

## Releaseprocedure og stopkriterier

- Denne sourcepakke skal i egen GitHub-branch, CI og særskilt review. Den må ikke merges til `main` uden eksplicit godkendelse af den ændrede 1245-pilotautorisation.
- Først efter grøn CI, kontrolleret Render deployment og en **ny særskilt operatørbeslutning** kan de to pilotmiljøvariable sættes. Der må ikke oprettes en deployment, før de fysiske gates er bestået.
- Et vellykket pilotresultat promoverer **ikke** 1245 til stabil. En senere særskilt promotion skal ændre både `latest_stable` og `default_install_version` atomisk og bevare tre-release-politikken og de gamle godkendte bytes.
- Stop ved afvigende SHA256, uklar kildeidentitet, 5xx-udfald, manglende lokal fallback, udestående aktiveringsintent, fejlet recovery eller fortsat nul-buffer-livestream.

## Skrivebeskyttede kontroller

```bash
python scripts/clientflow_1245_source_preflight.py --repo-root .
python scripts/clientflow_1245_pilot_policy_preflight.py --repo-root .
python scripts/clientflow_1245_r2_pilot_preflight.py --repo-root .
PYTHONPATH=backend:client/release/lib:. python -m pytest -q \
  backend/tests/test_clientflow_1245_exact_single_client_pilot.py \
  scripts/tests/test_clientflow_1245_r2_pilot_stage.py \
  scripts/tests/test_clientflow_1245_pilot_policy_preflight.py \
  scripts/tests/test_clientflow_1244_catalog_promotion.py
sha256sum --check --strict SHA256SUMS.txt
```
