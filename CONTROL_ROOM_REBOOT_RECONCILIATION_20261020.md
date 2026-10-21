# Control Room – sikker genstartsafstemning (2026-10-20)

## Dokumenteret fejl (Heidi1 / client_id=1)

- 20:02:49 lokal tid: genstart kølagt i Control Room.
- 20:02:50: autoriseret System-agent krævede kommandoen; broker aktiveret.
- 20:03:29: maskinen var startet på nyt boot-ID.
- Ca. 20:08:32: backend markerede samme kommando `expired`, selv om brokerens **lokale** vedvarende journal havde `state=completed` for det pågældende kommando-ID.
- Fejlen i backend er en manglende sikker afslutning efter fysisk bootgrænse; `claimed_at=None` efter udløb er ikke bevis for aldrig at være blevet krævet, da `_clear_claim()` nulstiller dette felt.

## Løsning

1. Read-projektionen viser normal drift straks efter verificeret, online **nyt canonical Status boot-ID**, selv hvis en historisk genstartskommando stadig er aktiv. Kommandoens **status** forbliver uændret; der fabrikeres ingen `succeeded`.
2. Ved et aktivt reboot på et nyt boot-ID afvises tidligere kølagte genstarter. **Ældre klienter**, der ikke kan garantere sikker broker-recovery, ender som `failed`/`cancelled` med forklaring og får aldrig en potentielt farlig gentagelse.
3. Ny System-agent annoncerer `safe_reboot_recovery` via autentificeret status med **matchende nyt boot-ID**. Kun da kan tidligere krævet reboot genudleveres i `recovery_only`-tilstand med **samme klient og command-ID**, og først efter at canonical Status-agenten har verificeret bootgrænsen.
4. Broker kræver ved recovery-only en eksisterende journalpost, bundet til korrekt `client_id`, `command_id` og `action`, samt det annoncerede aktuelle boot-ID. Manglende journal eller boot-mismatch fejler lukket uden at genstarte. En broker-`complete` kvittering via det normale, autentificerede System-agent-endpoint er eneste authority for `succeeded`.
5. System-agentens eget rapporterede boot-ID bruges desuden **kun som veto** mod at udlevere en gammel queued reboot, når System-agenten starter før Status-agenten. Det bruges aldrig som selvstændigt succesbevis.
6. Clientlist viser `Fuldskærm: Ukendt` når en ældre ClientFlow-klient ikke rapporterer Chrome fullscreen.

## Bevidst afgrænsning

- Ingen ændring i Livestream, Terminal, Remote Desktop, frontendens Control Room-livestream-kontrakt, MFA, OS-/firmwareopdateringskommandoer, shutdown-reconciliation eller browserens fuldskærmsmåling.
- Ingen bagudrettet omskrivning af allerede udløbne kommandoer; Heidi1's `expired` historik forbliver reviderbar.
- *Da ClientFlow-kildekoden er ændret, må den tidligere 1.3.40 source stage **ikke** publiceres uden ny source freeze og to uafhængige builds efter godkendt PR/CI.*
- En lille eksisterende SQLite source/build-kontraktpakke kan køres lokalt, men fuld DB-integration og hele GitHub CI forbliver endelig gate.

## Produktionsaccept efter CI, merge og Render Live

1. Kontroller på Heidi1 uden ny genstart: `online`, `normal`, `pending_reboot=false`; gammel `expired` kommandolog uændret; fuldskærmschip selvforklarende.
2. Fysisk genstartstest på den **nye** recovery-sikre klientversion efter separat godkendt udgivelse. Verificér `claimed → succeeded` med journalidentitet og nyt boot-ID; ingen ekstra reboot.
3. Negative automatiske scenarier: lokal boot uden claim, stale queued reboot, manglende journal, forkert boot-ID, manglende kapabilitet, udløbet kommando, update/shutdown-isolation, gentaget report.
4. Ingen produktionstest, der kræver at afbryde netværk/strøm eller fremprovokere fejl, før særskilt aftale.
