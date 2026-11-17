PLANIQ DISPLAY – 62B CI HOTFIX – pg_restore custom-format stdin
Dato: 17. november 2026

Kun 3 ændrede filer, upload til EKSISTERENDE branch:
  .github/workflows/single-node-smoke.yml
  scripts/tests/test_display_62b_backup_evidence.py
  SHA256SUMS.txt

Årsag:
  `pg_restore --list -` behandler - som filnavn og fejler med:
  pg_restore: error: could not open input file "-": No such file or directory

Rettelse:
  `docker exec -i ... pg_restore --list < "$dump" >/dev/null`
  pg_restore læser arkivet fra stdin, når filnavn udelades.
  Docker `-i` er bevaret; dumpet og den senere faktiske isolerede
  restore af den syntetiske database er uændrede.

Nye regressionstests sikrer, at stdin-formen bevares og den forkerte
`pg_restore --list - <` ikke genindføres.

Lokale kontroller:
  18/18 fokuserede tests bestået (62A og 62B)
  SHA256SUMS.txt verificeret, 646/646 entries
  Workflow YAML parsing PASS
  Python syntaks PASS
  Bash syntaks PASS
  ZIP-integritet PASS

Fuld GitHub CI / faktisk Docker 18 restore: AFVENTER.
Der er IKKE ændret produktionskode, data, deploy, adgangsgates,
release 1.3.44/1245 eller klienter. Vent med merge og Render redeploy.
