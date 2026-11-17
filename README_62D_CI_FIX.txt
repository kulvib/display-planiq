PlanIQ Display 62D - CI rettelse: F401 ubrugt datetime-import - 17.11.2026

Anvend i den EKSISTERENDE branch:
  feature/display-62d-recovery-coverage-deploy-evidence-20261117

Overskriv KUN disse to filer med de vedlagte versioner:
  scripts/tests/test_display_62d_recovery_and_deploy_evidence.py
  SHA256SUMS.txt

Rettelse: slettet ubenyttet linje `from datetime import datetime` i 62D-testfilen.
Ingen testcases, asserts, produktionskode eller sikkerhedsgates ændret.

Valider på GitHub: python -m ruff check backend/service1 backend/scripts scripts --select F,
fuld CI og Display single-node PostgreSQL smoke. Merge først når alle krævede gates er grønne.
SHA256SUMS indeholder stadig 656 poster. Den egentlige backup-/migrationstilladelse ændres ikke.
