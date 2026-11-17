PlanIQ Display · 62B · ÉN sammenhængende branch

Forslag: feature/display-62b-backup-isolated-restore-proof-20261117
Grundlag: display-planiq-main(20261117-110932).zip / main ba14ad180142233b0c00bd4fbade2a159f86764f

UPLOAD ALLE FILER MED DERES PLACERING, ingen sletninger:
- .github/workflows/single-node-smoke.yml
- scripts/display_62b_backup_evidence.py (NY)
- scripts/display_62b_offline_restore.sh (NY; executable bit i Git)
- scripts/tests/test_display_62b_backup_evidence.py (NY)
- docs/PLANIQ_DISPLAY_62B_BACKUP_RESTORE_PROOF_20261117.md (NY)
- SHA256SUMS.txt (opdateret)

IKKE EN SIGNERET RELEASE. IKKE EN FYSISK PILOT. INGEN BACKUP ER UDFØRT PÅ PRODUKTION.
Ingen eksisterende Render-config, Postgres data, signed releases, migrations,
statusagent, gates, miljøvariabler eller deploys ændres med denne kildepakke.

GitHub: Opret branch fra ovennævnte main; upload. Kør fuld CI.
Udløs single-node-smoke som særskilt workflow hvis den ikke udløses automatisk;
workflowet bygger i et DISPONIBELT CI-MILJØ og udfører reel isoleret pg_restore.
Ved fejl: STOP; ingen merge, ingen Render redeploy eller fysisk klientopdatering.

Kilde- og unittest-kontrol udført lokalt: se leverancebesked.
Rigtig produktionseksport / offline restore forudsætter selvstændigt godkendt
krypteret destination, fortrolighedskontrol og operatørhandling.

Fuld teknisk vejledning:
docs/PLANIQ_DISPLAY_62B_BACKUP_RESTORE_PROOF_20261117.md
