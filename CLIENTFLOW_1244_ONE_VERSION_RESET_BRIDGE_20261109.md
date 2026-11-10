# ClientFlow 1.3.43 / 1244 — præcist låst én-version-overgang

**Fase: kildekode til sikker overgang, uden nogen driftshandling.** Kun den friske `main`-ZIP fra 8. november 2026 kl. 20.42 er kildemateriale. Ændringerne ændrer ikke selve den allerede godkendte 1244-TAR.

## Godkendt mål

- Den eneste gældende baseline efter overgangen: `clientflow-1.3.43-seq-1244`.
- **Godkendt, uforanderlig TAR**: SHA-256 `d3fdae8fb2a93f74431780f4aadde21625d10917e99cfbe6095ff2394e1e856b`, størrelse `223610880` bytes.
- Source commit: `7ead8cf250b7d9b7c0d1bff5b70f574e76c11f41`.
- Godkendelsesreference: `CF-1.3.43-1244-20261109-7ead8cf-2243141d`.
- Godkendelses-run: `42667579175`. Separat GitHub-arkiv: `clientflow-1.3.43-1244-approved-transport`.
- GitHub-releasearkiver er *recovery-/revisionshistorik*, ikke aktive installerbare versioner.
- Brugeren har udtrykkeligt oplyst, at Viborg2 og Heidi1 er slettet og skal installeres på ny fra ren Ubuntu 26.04; denne oplysning behandles som operatørens bekræftelse. Backend har stadig klientidentiteterne, så gamle credentials skal tilbagekaldes og genprovisionering kontrolleres særskilt, før installationspausen ophæves.
- Fremtidig permanent policy er **højst de tre nyeste godkendte valgbare releases**. Ved denne nulstilling er antallet **én**, ikke tre. Kun den nyeste må være standard-fresh-install.

## Senest verificeret Render-tilstand før kodefasen

- Render release-store har **præcis fem** verificerede approved bundles `1239` til `1243`, ingen ugyldige artifacts.
- Tilgængelig diskplads **422408192 bytes**; 1244-godkendt TAR kræver `223610880` plus `67108864` bytes reserve. Forudsætningen skal verificeres igen umiddelbart før driftshandlingen.
- `CLIENTFLOW_FRESH_INSTALL_SUSPENDED=1` aktiv. Ingen `1241/1242/1243` pilotflag.
- Database-read-only: Heidi1 ID 1 og Viborg2 ID 2 stadig registreret `approved/ready`, `client_version` ukendt; **ingen aktuelle installationskoder** og **ingen uafsluttede deployments** på kontroltidspunktet. Der kan ske ændringer, så revider live-status inden publicering og oprydning.

## Sikker afgrænsning af ændringsleverancen

1. `scripts/clientflow_1244_transition_policy.py` kræver præcis fem allerede godkendte SHA-256/filstørrelser og præcis godkendt 1244-kandidat, gammel uændret 1243-katalogtilstand, aktiv installationspause og deaktiverede pilotflag.
2. `scripts/publish_clientflow_release.py` får et **engangsflag** `--authorize-1244-one-version-reset`. Det er kun gyldigt for **1244-TAR med den eksakte SHA, godkendelsesreference og source commit**. Allerede eksisterende immutable publication-, inode-, fsync-, SHA- og lock-kontroller forbliver aktive.
3. `scripts/audit_clientflow_release_retention.py` tillader denne ene eksplicitte **midlertidige 5→6** optagelse, men rapporterer fortsat `within_approved_limit=false` og `automatic_deletion_enabled=false`. Den permanente grænse på tre slækkes ikke. I den endelige én-release-baseline er `retention_ready=true` ved 1–3 korrekte godkendte bundles; `--require-three` kræver fortsat *præcis tre*.
4. `scripts/prune_clientflow_release_retention.py` kan gennemføre **seks→én** over fem særskilt godkendte *ældste-først* trin. Den afviser oprydning af 1244-bridgen, indtil et separat, deployet katalog har **udelukkende 1.3.43/1244 som `latest_stable`, `default_install_version` og eneste installable release**. Hvert trin kræver begge eksplicitte slettebekræftelser, exact SHA-256, fortsat pause, sikker disk-lock og re-audit. Sidste release kan aldrig slettes.
5. Dette er **ikke** et catalog-promotion-commit. Det gamle katalog peger fortsat på 1.3.38, indtil den godkendte 1244-TAR reelt ligger i Render. Ingen fysisk installation, klient-nulstilling, sletning eller aktivering sker ved GitHub-merge.

## Påkrævet operationsrækkefølge (separate gates)

1. **GitHub**: Upload changes-only branch, fuld CI PASS, merge, Render redeploy og smoke PASS. Kontrollér at Render kører den samme nye `main`-commit; **ikke** original source SHA 7ead8cf. Den godkendte 1244-TAR skal fortsat referere til den oprindelige source SHA 7ead8cf.
2. **Read-only Render preflight**: Revider disk, 5 SHA-256, live databaseklienter og aktive installations-/deploymentbindinger, og bekræft manglende pilotflag. Kør:

   ```bash
   cd /opt/display
   gosu display_app env PYTHONPATH=/opt/display/backend:/opt/display \
     python3 scripts/preflight_clientflow_1244_reset_publication.py \
     --artifact-dir /var/data/clientflow-release-artifacts/store
   ```

   Kræv `CLIENTFLOW_1244_PUBLICATION_PREFLIGHT=READ_ONLY_PASS`; det er **ikke** slette- eller installationsgodkendelse.
3. **GitHub-arkiv → Render**: Download `clientflow-approved-1.3.43-1244.tar` fra den allerede godkendte GitHub-tag og verificér eksakt **TAR**-SHA og størrelse fra en separat stagingsti uden for store (helst ephemeralt `/tmp`). Brug efter særskilt operatørgodkendelse den eksisterende publisher med `--publish-release`, alle tre eksakte proveniensfelter og `--authorize-1244-one-version-reset`. Kræv `RELEASE_STORE_POSTFLIGHT=PASS` og `CLIENTFLOW_1244_RESET_ADMISSION=VERIFIED_SIX_TEMPORARY`. Den seksdelte store er *en bevidst midlertidig tilstand*, ikke ny normal.
4. **Separat kode-/CI-gate: 1244-only katalog**: Først nu ændres backend-kataloget til præcis én stable/fresh-install entry `1.3.43`, `catalog_sequence=1244`, `max_selectable_versions=3`, `max_installable_versions=1`, historiske entries fjernet. `update_allowed=false` i denne nulstilling, ingen tvungen downgrade. Kør CI, merge, Render redeploy/smoke, verificér 1244-store/selector mens fresh-install stadig er suspenderet.
5. **Trinvis oprydning, ikke script i denne branch**: Med katalog 1244 aktivt og uændret, fresh-install pause stadig aktiv, nul åbne deployments/enrollment og særskilt autorisation, brug `scripts/prune_clientflow_release_retention.py` ét godkendt SHA-pinnet bundle ad gangen i rækkefølge: **1239 → 1240 → 1241 → 1242 → 1243**. Gentag både read-only plan og postflight for hver. Stop ved enhver mismatch; **slet aldrig manuelt med `rm` eller bypass databasen**. De gamle GitHub-revisionsoplysninger bevares, men versionskatalog og aktivt Render-store indeholder til sidst kun 1244. Kræv derefter `approved_count=1`, `within_approved_limit=true`, `retention_ready=true`, `invalid_artifacts=[]`.
6. **Inden genåbning af fresh installs**: Tilbagekald gamle klientcredentials og sørg for, at de slettede Heidi1/Viborg2 ikke stadig er aktive backendklientidentiteter. Kontrollér gyldigt nyt enrollment-flow, at første installation vælger **kun 1.3.43**, og at 1244 er tilgængelig i store. Ophæv først derefter installationspausen efter eksplicit driftsbeslutning og smoke.
7. **Fysisk test**: Ny Ubuntu 26.04 på Viborg2 først, installer ClientFlow 1.3.43 og test kiosk, netværk, Control Room, agent, browser/Wayland, kalender, terminal, livestream, Remote Desktop og Ubuntu-/dracut-opdatering; derefter samme på Heidi1. Først efter begge PASS går vi videre til øvrige nye klienter.

**Stop** ved diskplads- eller SHA-mismatch, ugyldigt lager, uafsluttede deployments, uklare klientcredentials, uventede pilotflag, manglende katalogskift eller CI/smoke FAIL. Ingen sletning i denne branch.
