# PlanIQ Display · Fase 63D-9R · rettelser efter kodeaudit

**Status: KODEKANDIDAT – IKKE MERGET, IKKE EN GODKENDT 1247-RELEASE.**

Branch: `phase/63d9r-input-reconnect-hls-guards`

Kilde: frisk main-ZIP `display-planiq-main(20261118-225435).zip` + samtlige ændringer fra Fase 63D-9. Den medfølgende ændrings-ZIP og Git-patch er **kumulative relativt til den oprindelige main** (ikke kun en delta oven på en allerede uploadet 63D-9).

## Rettede auditfund

1. **Tidlig input-registrering:** Backend sender kun input via en kanal, hvor agenten har sendt `input_ready` for den konkrete, autoriserede browsersession. `input_ready` fra en udskiftet forbindelse ignoreres. Indtil kvittering anvendes den eksisterende control-kanal, så 1246 forbliver kompatibel.
2. **Genforbindelse og fallback:** Fejler et send på den bekræftede inputkanal, afregistreres klarstatus for sessionen, og backend forsøger den eksisterende control-kanal uden at lukke browserens WebSocket. Fejler også denne, vises en kontrolleret fejl til browseren. Hændelser har stabile `input_id` ved begge forsøgsveje.
3. **Nedtrykkede knapper/taster:** Den eksisterende privilegerede inputbroker sporer nedtrykkede uinput-taster/museknapper per session. `release_session` frigiver kun den relevante sessions knapper; andre samtidige sessioners hold respekteres. Agenten frigiver ved sessionslukning og kanalbrud. Afslutning venter på igangværende input-RPC, så en sen `down` ikke kommer efter oprydningen.
4. **Inputtrafik/latency:** Kun musebevægelser (`mouse/move`) undlader succes-kvittering på den nye inputkanal. Fejl og kvittering for andre input bevares. I HTTPS-relay-tilstand fjerner det ét autentificeret retur-POST per succesfuld musebevægelse. Den ordnede kø er begrænset til 32 ventende hændelser med kun tilstødende bevægelses-coalescing, aldrig tabsbaseret coalescing af klik/up/taster.
5. **HLS-tilbageløb:** Manifestets første/sidste sekvens valideres, også ved tilladt fremtidig metadata. Uploaderen afviser et manifest, hvor første eller sidste sekvens går baglæns i den aktive generation, og gemmer tidligere publicerede sekvenser i den eksisterende lokale statusfil for normale uploader-genstarter. Beskyttelsen er ikke en global transaktionsgaranti på tværs af flere uafhængige uploadere – det skal verificeres i pilot.
6. **Idle-databasebelastning:** Den tredje inputforbindelse startes kun ved en aktiv, autoriseret Remote Desktop-browsersession og stoppes efter den sidste sessionslukning/afbrudte controlforbindelse. Den eksisterende 15-sekunders autorisationskontrol bibeholdes **mens** forbindelsen er aktiv; ingen nye miljøvariabler eller svækket autorisationskontrol.

## Bevarede kontrakter

- Backend/control/file forbliver kompatible med en 1246-klient, hvor inputforbindelsen ikke eksisterer. Ingen ændring af credentials, Render Environment, database-/migrationsskema eller releasepolitik.
- HLS-kildefiler valideres fortsat mod sikre filnavne og lokal filtilstedeværelse, før manifest uploades; ukendte sikre HLS-metadata bevares uden usikker omskrivning.
- Remote Desktop kræver fortsat eksisterende superadmin/sessionautorisation. Den tredje kanal anvender den eksisterende credential og periodisk revalidering.
- Det nye `release_session`-RPC er kun tilgængeligt via den eksisterende privilegerede lokale inputbroker og ændrer ikke netværks-API'ets autorisationsmodel.

## Kvalitetskontrol og gates

**Lokal test:** `python -m compileall` og målrettede source-/regressionstests; se den separate ændringsoversigt for faktisk PASS/SKIP-status. SQLModel-baseret fuld backend-integration, Node 24 frontend-build og GitHub CI skal stadig kontrolleres i GitHub. Den isolerede source-AST-test dækker den faktiske fallback/ACK-kode, men erstatter ikke en integreret WebSocket-/database-test.

1. Opret branch fra præcis den main-ZIP, der er angivet ovenfor, og læg alle kumulative ændrede filer ind. GitHub CI skal være helt grøn, inklusive sikkerheds- og source-gates.
2. Deploy backend/frontend **før** ny klient og verificér Remote Desktop med 1246 (control-fallback), filer og lukning af sessionsforbindelsen. Ingen nulstilling af eksisterende credentials.
3. Pilotkandidat 1247 bygges først efter grøn CI fra den godkendte main. Kun Viborg1, der ikke er en produktionsklient.
4. Mål med stabil backend uden redeploy: kontrol af musens faktiske responstid, drag/down/up, tastetryk, genforbindelser, WS og tvungen HTTPS-fallback; sammenlign `input_queue_ms`, `input_rpc_ms`, `input_to_frame_ms` samt browser RTT uden at forveksle RTT med input-til-pixel-latency.
5. For Livestream: mål alder på seneste segment, manifest-sekvens, lokal uploadtid og faktisk ende-til-ende-afspilningsforsinkelse. Test segmentrotation og pause/genstart af uploader.
6. Overvåg ekstra databaserevalideringer **mens** Remote Desktop er aktivt. Ved 100 samtidige aktive klienter kan den tredje kanal stadig medføre op til 576.000 revalideringer/døgn alene fra 15-sekunders kontrol – kun inaktive klienter undgår dette ekstra arbejde.

**STOP** ved fejl i knapslip, dubletter, afspilning, autorisationsgate, filoperationer, voksende inputforsinkelse eller uventet databaseforbrug. Behold pilot 1246; ingen bred udrulning og ingen ændring af release-retention.
