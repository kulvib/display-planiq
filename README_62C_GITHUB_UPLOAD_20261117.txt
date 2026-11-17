PLANiQ DISPLAY 62C · GITHUB BRANCH-UPLOAD · 17 NOV 2026

Kilde: helt frisk vedhaeftet main-ZIP display-planiq-main(20261117-113750).zip
Forventet main-commit: 0df746e53fdec5beb439c6f8b06fa82341f2fbde

Anbefalet branch:
  feature/display-62c-session-head-health-calendar-401-20261117

Upload samtlige filer fra denne ZIP og bevar undermappestruktur. Erstat
SHA256SUMS.txt; upload ikke nye __pycache__, filer fra tidligere ZIP'er
eller produktionsdata. Pakken indeholder kun nye/aendrede kildefiler.

Kontroller GitHub CI:
- Backend, migrations and contracts
- Frontend contracts and build (npm lint / frontend tests)
- Ubuntu 26.04 executable proof scope
- Ubuntu 26.04 client host executable contracts
- Display single-node PostgreSQL smoke (62B isoleret restore)

STOP ved enhver CI-fejl. Ingen signeret ClientFlow-release skiftes, ingen
pilot/fleet/fresh-install-gate aabnes, ingen PostgreSQL/release-lager-migration.

Efter groen CI: merge til main; Render backend og frontend deployment skal
begge vaere live paa samme commit. Udfør smoke (se docs/PLANIQ_DISPLAY_62C_...):
HEAD /health 200 tom body, GET /health/db 200, login/logout,
aktivt/inaktivt sessionforloeb, flere faner, 15 min access refresh,
kalenderens saison-kald, og transient 502/503 som ikke fejltolkes som logout.
Test serverstatus og observer browsernetvaerk. Under den nuvaerende
persistente-disk-arkitektur kan Render stadig give kort 502 ved deploy.

Read-only analyse og recovery-vaerktoej fra 62B forbliver tilgængeligt.
Ingen produktionsbackup eller restore er gennemført af denne kodeleverance.
