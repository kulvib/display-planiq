# PlanIQ Display 61B-2K – sammenhængende kandidat- og artefaktkontrol

**Dato:** 17. november 2026 · **Source baseline:** `main` commit `b7201b53d6bce0b509568f48ada19e625b867105`.

## Formål

61B-2J leverede kildeidentiteten **1.3.45 / 1246**. Dette trin lukker overdragelsen mellem
GitHubs to reproducerbare *usignerede* bygninger og den **særskilt manuelle**
releasegodkendelse. Samme read-only verificering udføres på to uafhængige
GitHub-kørsler, med eksakte kilde- og artefaktbindinger:

1. `.github/workflows/release-build.yml` kører preflight på eksakt source SHA,
   pinned runtime-input transport, to uafhængige builds, Ubuntu 26.04 host-
   og runtime-gates, byte-for-byte-reproducerbarhed og *derefter* ny fuldstændig
   handoff-verificering, inden GitHub attesterer og uploader artefakter.
2. `.github/workflows/release-approve.yml` henter kun artefakter fra et
   succesfuldt source-identisk build-run; **før** manuel approval valideres
   de samme bytes og embedded TAR-medlemmer igen, nu også mod operatørens
   eksplicit angivne candidate- og installer-SHA256.
3. Begge punkter bruger `scripts/verify_clientflow_candidate_handoff.py`.
   Scriptet har ingen netværks-, installations-, publicerings-, database- eller
   systemd-skriverettigheder og returnerer `VERIFIED_UNSIGNED_HANDOFF_ONLY`.

## Hvad kontrolleres?

- Handoffmappen har **præcis** de seks forventede filer: kandidatbundle,
  separat installer, payload, kandidatmanifest, `SHA256SUMS` og
  `REPRODUCIBILITY.json` – ingen ekstra filer eller symlinks.
- Alle filer og deres størrelser og SHA256 stemmer med den reproducerede
  record og checksum-listen. Dobbelte eller fremmede checksum-linjer afvises.
- `source_commit`, `source_date_epoch`, releaseidentitet og den låste
  Python/pip/setuptools-toolchain stemmer med source.
- Runtime-input-transportens SHA er korrekt bundet til record; i build-run
  sammenlignes den også med det oprindeligt valgte transport-SHA. Inputfilens
  faktiske bytes er allerede kontrolleret tidligere i release-build-pipelinen.
- Kandidatens manifest er **ikke deployable**, har ingen approval og kræver
  manuel aktivering; offline runtime og platformkontrakt er komplette.
- TAR indeholder præcis `manifest.json`, `clientflow-payload.tar` og den
  versionsbundne installer; ingen symlinks/ekstra/duplikerede medlemmer.
  De indlejrede bytes stemmer med sidecar-filerne, inkl. TAR-manifestet.
- Produktionskataloget indeholder kun **1.3.44/1245** som godkendt/stabil;
  `physical_pilot_accepted` er fortsat `false`.

## Kontrolindstillinger

Read-only på allerede bygget, uændret kandidat-handoff:

```bash
python scripts/verify_clientflow_candidate_handoff.py \
  --repo "$GITHUB_WORKSPACE" \
  --handoff "$RUNNER_TEMP/handoff" \
  --expected-source-sha "$EXPECTED_SOURCE_SHA" \
  --expected-candidate-sha256 "$EXPECTED_CANDIDATE_SHA256" \
  --expected-installer-sha256 "$EXPECTED_INSTALLER_SHA256"
```

`--expected-runtime-transport-sha256` kan desuden sættes under build-run.
Der må ikke opfindes eller gættes SHA'er, source commits eller runtime-input
URLs; de skal komme fra den godkendte, faktiske buildkæde.

## Hårde STOP-kriterier og resterende godkendelser

En vellykket 61B-2K-test **er ikke** en produceret artefakt eller en release-
godkendelse. Den faktiske **1.3.45/1246** skal fortsat:

1. Bestå alle GitHub CI-jobs på den præcise kildecommit.
2. Få en separat, succesfuld manual `release-build.yml` med to byte-identiske
   outputs, eksakt pinned runtime-input transport, eksekverbar Ubuntu 26.04-
   kandidatkontrol og GitHub source-attestation.
3. Undergå manuel artefaktreview af SHA, payload, installer og journal;
   først derefter kan separat **manuel** `release-approve.yml` overvejes.
   `release-approve.yml` er ikke en fysisk pilotgodkendelse eller fleet-
   tilladelse.
4. Have eksplicit bemandet pilotplan, verificeret klient-ID og **separate**
   driftsgates før signeret/fysisk update. Første install/fresh-preclaim, boot,
   GNOME/Wayland-hostskærm, kioskstop/restart, rollback og root-recovery skal
   bestå fysisk. Ingen automatisk katalogpromotion.

61B-2K ændrer ikke releasecontroller, installation/OS/firmware-broker,
recoveryjournal, installer, browser, database, catalog, signerede 1.3.44-bytes,
eller CI-sikkerhedspolitikker. En forkert eller ukomplet kandidat giver STOP;
**aldrig** automatisk signering, approval eller deployment.

## Testafgrænsning

Lokalt kan vi fuldt teste syntetiske handoffs og alle negative source-/byte-
kontrakter. Vi kan ikke producere en rigtig 1.3.45-kandidat uden det eksterne,
SHA-låste `runtime-inputs.tar` og det præcise Git-commit; det kræver GitHub-
release-build efter CI. Hverken en lokal pytest-PASS eller en Render-deploy
beviser fysisk Ubuntu/Wayland-accept.
