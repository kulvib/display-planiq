PLANiQ DISPLAY / CLIENTFLOW 61B-2J - KILDEKANDIDAT 1.3.45 / 1246
16 november 2026

BRANCH: feature/display-61b2j-unsigned-candidate-1345-1246-20261116
BASE: Frisk bruger-ZIP display-planiq-main(20261116-175637).zip
Forventet GitHub main før branch: 3725379f409dc034fdf4ac3ddb253ef1ac6b6c79

Upload ALLE filer i denne ZIP til en NY branch fra ovenstående main med samme
sti. Upload ikke mapperne med arbejdskopier eller andre gamle branch-pakker.

Denne branch FRYSES KUN SOM UNSIGNED SOURCE CANDIDATE. Ingen ny client bundle
blev bygget, signeret, publiceret eller udrullet. Hverken release-approve,
Render gates eller fysisk installation skal aktiveres ved upload.

Hovedændringer:
- client/VERSION -> 1.3.45 og release-input -> sequence 1246.
- Ældre preflight-kontrakter accepterer KUN parrene 1.3.44/1245 og 1.3.45/1246,
  men alle LIVE stable release records, approval refs, hash og catalog selector
  forbliver eksakt original 1.3.44/1245.
- Release-source-gate tillader KUN den nye usignerede kandidatversion
  1.3.45/1246 og fejler ved promotion/manipulation af stable catalog eller
  ved utilsigtet fysisk 1245-pilotaccept (selv efter SHA256-omskrivning).
- Nye negative regressionstests dokumenterer disse grænser.

TESTS I LOKALT MILJØ:
707 script-tests PASS (15 miljø-/legacygrupper udeladt, se pipeline).
46 source-/release-/candidatekontrakttests PASS.
44 øvrige source-/udgivelsestests PASS.
87 vedligeholdelses-, låse-, rollback- og first-installtests PASS.
Full GitHub CI afventes (kan ikke erklæres PASS fra lokal test).

VIGTIGT: Preclaim-til-first-claim-vinduet er fortsat ikke fysisk accepteret,
og Wayland-/host fullscreen, efterkontrol, signering, katalogpromotion,
rollback og genstart kræver særskilt kontrolleret pilot. Alle produktionsgates
skal forblive LUKKEDE. Den gamle, signerede 1.3.44/1245 må ikke overskrives.

Se docs/CLIENTFLOW_61B2J_UNSIGNED_1345_1246_SOURCE_STAGE_20261116.md.
