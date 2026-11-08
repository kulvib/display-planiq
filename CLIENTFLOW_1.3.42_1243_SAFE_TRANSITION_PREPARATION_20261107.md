# ClientFlow 1.3.42/1243 — klargøring til tre-release-overgang og Viborg2-pilot

**Fase:** kodeforberedelse, read-only checks og eventuelt særskilt godkendt, ikke-destruktiv arkivering. **Ingen sletning, publicering, katalogpromovering eller klientopdatering i denne branch.**

## Godkendt releaseidentitet — må ikke ombygges

| Felt | Uforanderlig værdi |
| --- | --- |
| Release | `clientflow-1.3.42-seq-1243` |
| Source commit | `b870cf8c3fa90286c6b4dccaae593eb8a0d57565` |
| Candidate SHA-256 | `4e52cbfbaa844c2d835e5b57f625b5a64cb98346c428ee410aead02b7c67c88a` |
| Installer SHA-256 | `e23fefccb4c126fee82a807ce0ffe22ddc5051aa8b6b53ca1907161622e126f3` |
| Approved bundle SHA-256 | `ee35cc6caa9304bbc7ee4b1c763ecdeaf03d9d58a6c73cee943805251d8d6914` |
| Approved bundle size | `223610880` bytes |
| Approval reference | `CF-1.3.42-1243-VIBORG2-PILOT-20261107` |

Indtil de fulde, godkendte bytes er publiceret, må backend-kataloget **ikke** få 1243 som valgbart release. Render-instansen kører lokal PostgreSQL og vedvarende artifactdisk. Vores nye backend-kode ændrer IKKE binærfilerne for 1.3.42/1243; den godkendte release henviser fortsat til den oprindelige source SHA ovenfor.

## Faktisk audit før overgangen

Render-store indeholder fire verificerede godkendte releases: `1.3.38/1239` (SHA `02c3d4261eabdac4b9967a3aad4419453f61ca483ef4eb34dacf284d3af16a11`), `1.3.39/1240` (SHA `40fb64e3e8e38686f4b03ee8f66afc81fe7a03247ed723d8a6ce636aebbcb798`), `1.3.40/1241` og `1.3.41/1242`. Mål for aktivt lager efter vellykket overgang er præcis tre: `1.3.40`, `1.3.41`, `1.3.42`. Det er **ikke** nået ved denne code-stage.

Den eksisterende oprydningskommando må ikke køres med `--confirm-prune` / `--confirm-no-dependencies`: den gamle 1.3.38 er stadig katalogets `latest_stable` / `default_install_version`, og Viborg2 bruger den som fysisk, lokalt recoverygrundlag. Det er et korrekt fail-closed stop. Vælg ikke at slette 1.3.39 "uden om" mekanismen for at omgå dette stop.

## Hvad implementeres

1. `clientflow_pilot_1243.py` forbereder en **deaktiveret** guard, som kun accepterer `CLIENTFLOW_1243_PILOT_CLIENT_ID=2` og præcis in-place `1.3.38 → 1.3.42`. Den kræver årsag og validerer source, SHA, størrelse, approval før *og* efter per-klient DB lock. Fejlagtige ID, samtidig 1241/1242-flag, downgrade/repair eller katalogudvidelse afvises. 1241 og 1242 afviser også samtidig 1243-flag. Kataloget forbliver `1242` og er 100% uændret.
2. `CLIENTFLOW_FRESH_INSTALL_SUSPENDED` er et separat **inaktivt** vedligeholdelsesflag (fraværende/`0` = normal drift). Ved enhver anden værdi returnerer nye tokens, bootstrap, fresh-install download, claim og completion `503`, også for tidligere udstedte tokens. Eksisterende klienters drift og in-place opdatering påvirkes ikke. Dette flag er **ikke** automatisk aktiveret; kræver egen Render-ændring, vedligeholdelsesvindue og verifikation af ingen aktive installationer.
3. `scripts/archive_clientflow_release_verified.py` er en sikker, read-only som standard / no-replace kopiering af ét godkendt, hashverificeret bundle fra `store` til et **andet, sikkert ejet** katalog. `--create-verified-archive` må kun bruges efter særskilt operatorbeslutning. Den kopierer, fsync'er, rehasher og lader originalen fuldstændig urørt. Den kan **ikke** slette noget. Et arkiv på SAMME Render-disk er **ikke** en uafhængig backup: kopier det også offsite, kontroller SHA-256 og behold recovery-beviset inden en senere godkendt sletning.

## Nødvendig rækkefølge efter grøn CI og smoke test

- **Gate A – kun læsning:** Kontroller aktuel Render audit, katalogsekvens, klienter/tilstand, uafsluttede deployments, aktive installationskoder og lokalt `activation_intent` på Viborg2. Der må ikke være aktive downloads eller status der mangler lokal recovery-ACK. Kræv fysisk lokal adgang, dokumentér vellykket 1.3.38-controller-bridge og `CONTROLLER_KIOSK_ACL_DRY_RUN=PASS`. Verificér faktisk højeste anti-rollback sekvens uden at nulstille den.
- **Gate B – separat arkiv:** Hvis drift og afhængigheder er godkendt, lav verificerede kopier af **1.3.38 og 1.3.39** til separat archive-katalog og en **uafhængig** offsite-lokation; dokumentér eksakte SHA-256, size og recoveryplan. Brug kun den godkendte katalog-pinnede 1.3.38 som fysisk recovery-reference; arkivet alene betyder ikke aktiv manuel rollback.
- **Gate C – eksplicit fresh-install-pause:** Sæt `CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1`, lad Render-deploy/health-gate passere og test at alle fem endpoints afviser nye og allerede udstedte fresh-installationsprocesser. Deaktivér både `CLIENTFLOW_1241_PILOT_CLIENT_ID` og `CLIENTFLOW_1242_PILOT_CLIENT_ID`; **lad `CLIENTFLOW_1243_PILOT_CLIENT_ID` være fraværende**. Vær især opmærksom på, at katalogets 1.3.38 default midlertidigt ikke kan hentes, hvis dens aktive bundle fjernes under denne fase. Dette er en styret test-only vedligeholdelsespause, ikke en generel produktionsløsning.
- **Gate D – særskilt rotationskode:** Først med bekræftet ekstern backup, midlertidigt suspenderet fresh-install, nul aktive deployments og konkret menneskelig godkendelse implementeres/reviewes den endelige rotationsmekanisme med transaktionel verificering og gendannelsesplan. **Denne branch indeholder ikke en sådan destruktiv mekanisme.** Fremadrettet 1.3.42-publicering må ikke omgå store-audit, gruppe-/ejerrettigheder eller tre-releasegrænsen.
- **Gate E – efter publicering og re-read postflight:** I separat reviewet branch tilføjes katalogets 1243 entry, update-only, current-version præcis 1.3.38, ikke installable/default, med `catalog_sequence=1243`. Kør CI, deploy og smoke, bekræft at guard stadig er off. Kun efter dette og særskilt manuel Viborg2-godkendelse sættes `CLIENTFLOW_1243_PILOT_CLIENT_ID=2`, og kun ét deployment startes.
- **Gate F – fysisk accept:** Installer/test med tilsyn på Viborg2, inklusive kontrolleret reboot, aktiv symlink, GUI/Chrome/Wayland, Control Room, kalender, Livestream første HLS-segment, Remote Desktop, terminal og service-reconnect. Foretag særskilt simuleret aktiveringsfejl med automatisk recovery i **isoleret** miljø, ikke med sabotage af den succesfulde fysiske testklient.
- **Gate G – genåbn fresh-installs:** Kun efter særskilt stable/default-promovering til en fysisk accepteret og publiceret release; test normal enrollment på et testmiljø. Lad aldrig `CLIENTFLOW_FRESH_INSTALL_SUSPENDED` blive slået fra mens katalog/default peger på en fraværende bundle.

## Særligt om rollback

Tre lagrede godkendte releases er historik og mulige input til recovery, ikke bevis for at manuel rollback virker. Den allerede godkendte 1.3.42/1243 har `rollback-trust.json` med `enabled=false`; backend `rollback_allowed=false`. Intet i denne branch åbner manuel rollback, nedgradering eller anti-rollback omgåelse. Lokal, dokumenteret 1.3.38-recovery skal beskyttes under piloten.

## Eksempler, kun read-only (kør i Render Shell under korrekte brugeridentiteter)

```bash
cd /opt/display
gosu display_app env PYTHONPATH=/opt/display/backend:/opt/display \
  python3 scripts/audit_clientflow_release_retention.py \
  --artifact-dir /var/data/clientflow-release-artifacts/store

# Kun verificering: arkivkataloget SKAL allerede være oprettet sikkert og
# må IKKE være det aktive store-katalog.
gosu display_app env PYTHONPATH=/opt/display/backend:/opt/display \
  python3 scripts/archive_clientflow_release_verified.py \
  --source-store /var/data/clientflow-release-artifacts/store \
  --archive-dir /var/data/clientflow-release-artifacts/recovery-archive \
  --release-id clientflow-1.3.38-seq-1239 \
  --expected-sha256 02c3d4261eabdac4b9967a3aad4419453f61ca483ef4eb34dacf284d3af16a11
```

**Ingen `--create-verified-archive` i læsefasen, ingen sletteflag og intet katalogskift.**
