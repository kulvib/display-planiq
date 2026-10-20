# PlanIQ Display – supportsessioner adskilt fra livestream

## Afgrænsning

**Control Room Livestream-kontrakten er uændret.** Ingen ændring i frontendens livestreamkomponent,
API-ruter, viewer-heartbeat (25 sekunder), seerlease (75 sekunder), stop-grace (30 sekunder),
manuel start/stop, mobiladfærd, roller eller HLS-transporter.

Denne ændring fjerner kun Terminal og Remote Desktop som *implicitte livestreamseere*:

- Supportsessioner har fortsat deres egne autentificerede sessionspor og audit-lease.
- Supportsessioners oprettelse/lukning vækker ikke længere livestream-sweeperen.
- Terminal og Remote Desktop kan ikke alene starte eller holde en livestream-generation i live.
- Kun faktiske livestreamseere bevirker start/genoptagelse og holder den aktiv.
- Livestream uden seere stoppes efter den eksisterende grace-periode (med almindelig agent-forsinkelse).
- Livestream har samme udtrykkelige stop-lås som tidligere.

**Bevidst bevaret adfærd:** Den eksisterende Control Room-klientdetaljeside monterer
livestreamkomponenten automatisk på desktop og opretter en gyldig viewer-lease. Hvis den side
står åben, kan livestream derfor stadig være aktiv, selv om Terminal/RD også er åben.
Det er forventet i den godkendte Control Room-kontrakt, og denne PR ændrer det ikke.

## Regressionskrav

1. Terminal alene / Remote Desktop alene: ingen HLS-start, intet livestream-livscyklus-wakeup.
2. Faktisk livestreamseer: normal start, 25 sekunders heartbeat, aktiv stream, stop-grace.
3. Sidste livestreamseer forlader: stream stopper selv med åben Terminal/RD.
4. Manuel stop-lås: ingen genstart før bevidst manuel start.
5. Ingen ændrede frontend- eller API-kontrakter og ingen nye tjenester/migrationer.
6. PostgreSQL/SQLite-integrations- og fuld GitHub CI er endelig gate; ikke alle integrationstests kan afvikles i dette lokale miljø.

## Produktionsaccept efter grøn CI og Render Live

- Test først at Terminal og RD stadig kan åbnes og lukkes uafhængigt.
- Luk klientdetaljesiden og alle livestreamseere, men hold én supportsession åben:
  kontrollér at livestream stopper efter den normale seergrace.
- Åbn klientdetaljer på desktop: kontrollér at livestream starter som tidligere.
- Kontrollér manuel Stop og Start samt mobilvisning.
- Kontrollér at ingen nye HLS-produktioner startes ved åbning af Terminal/RD uden en viewer.

Ingen fysisk klientopdatering kræves for backendændringen; ClientFlow 1.3.40 / 1241 er fortsat på pause.
