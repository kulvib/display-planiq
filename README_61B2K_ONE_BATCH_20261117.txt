PlanIQ Display · 61B-2K · 17. november 2026

BASELINE: main fra ZIP display-planiq-main(20261117-093547).zip
GitHub main: b7201b53d6bce0b509568f48ada19e625b867105

Formål: Streng offline, read-only artefaktkontrol af 1.3.45/1246-kandidaten
mellem det reproducerbare GitHub release-build og en mulig, særskilt manuel
releasegodkendelse. Ingen signering, promotion, installation eller ændring
på fysiske klienter.

UPLOAD SOM ÉN BRANCH, med mappestruktur uændret:
  .github/workflows/release-build.yml
  .github/workflows/release-approve.yml
  scripts/verify_clientflow_candidate_handoff.py
  backend/tests/test_clientflow_61b2k_candidate_handoff.py
  docs/CLIENTFLOW_61B2K_REPRODUCIBLE_CANDIDATE_HANDOFF_20261117.md
  README_61B2K_ONE_BATCH_20261117.txt
  SHA256SUMS.txt

Foreslået branch:
  feature/display-61b2k-reproducible-handoff-20261117

Verificeret lokalt:
  - 180 målrettede release-/security-/workflow-regressionstests PASS
  - source gate: READY_FOR_UNSIGNED_CANDIDATE_BUILD, deployable=false
  - original signerede 1.3.44/1245 katalog og acceptance uændrede
  - SHA256SUMS: se manifest og værktøjs-output

GitHub CI på ny branch: AFVENTER. GitHub release-build: IKKE kørt.

Ingen merge eller Render-redeploy før CI er grøn. Efter merge og grønt smoke
kan den separat godkendte GitHub release-build workflow køres på eksakt SHA
med eksisterende SHA-låst runtime transport; den producerer *kun usignerede*
artefakter og er ikke fysisk godkendelse. Se docs/...61B2K...md.
