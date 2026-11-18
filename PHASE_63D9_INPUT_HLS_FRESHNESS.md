# PlanIQ Display · Fase 63D-9 · input, transport og Livestream

**Status: KODEKANDIDAT – ikke en godkendt release.**

Foreslået branch: `phase/63d9-input-lane-hls-freshness`

Kilde: frisk main-ZIP `display-planiq-main(20261118-225435).zip` (18. november 2026). Der er **ikke** ændret release-id, releasepolitik, credentials, database-/miljøkonfiguration eller Render Environment. Version 1246 forbliver pilot på Viborg1, indtil accept er dokumenteret. Ingen bred udrulning.

## Hvad ændres?

### 1. Separat Remote Desktop input-lane

- Backend opretter en tredje autentificeret agentkanal, `/api/remote-desktop-agent/clients/{client_id}/input/ws`, med samme credential-, tokenversions- og periodiske revalideringskontrol som control/files. Den eksisterende HTTPS-relay understøtter også `input` uden ekstra miljøvariabler.
- Muse- og tastaturhandlinger routes via input, **hvis** den nye kanal er online. Ellers bruges eksisterende control-kanal, så backend kan deployes før klienten uden at ødelægge 1246. JPEG, capture og øvrig control bliver på control-kanalen; filer bliver på files-kanalen.
- Inputkanalen accepterer kun `session_open`, `session_close`, `mouse`, `key` og `text` fra backend og kun inputresultat/fejl fra klienten. En session skal åbnes før input. Kun whiteliste af inputfelter kan nå lokal input-RPC.
- Input indeholder en **bounded kø (96)**. Kun tilstødende, endnu ikke behandlede `mouse/move` i samme session kan erstattes; aldrig `down`, `up`, `click`, `scroll`, `key`, `text` eller sessionsbeskeder. Ved overbelastning anvendes backpressure.
- Lokal telemetri i den allerede eksisterende `media-telemetry.json` udvides med `input_queue_ms_*` og `input_rpc_ms_*` (ingen DB-kald). Eksisterende `input_to_frame_ms_*`, `relay_send_ms_*` og `capture_ms_*` bevares.
- Browseren måler transport-RTT via eksisterende autoriserede `ping/pong` uden ekstra HTTP-/databasekald. **RTT er ikke det samme som mus-til-skærm-latens.**

### 2. HLS uploader og afspiller

- Den lokale HLS-uploader læser det aktuelle producerede manifest, validerer segmentnavne og media-sequence og uploader kun de **fire nyeste, afsluttede segmenter** i korrekt rækkefølge; den publicerer først et tilpasset manifest, når alle refererede segmenter er tilgængelige.
- Segmenter udenfor vinduet bliver ikke uploadet igen; lokal hashhistorik begrænses til det aktive vindue for at undgå langsom hukommelsesvækst over flere timers drift.
- Ved manglende, ugyldigt eller halvskrevet manifest publiceres der ikke et nyt manifest. Ingen ændring af HLS backend-API eller af lokale GStreamer-producerindstillinger.
- HLS.js fortsætter på almindelig HLS, men sænker maksimal afspillerlatens fra 14 til 9 sekunder, og catch-up seek-grænsen fra 10 til 6 sekunder på klientdetaljesiden. Det er et **mål om mindre ekstra afspillerbuffer**, ikke en garanti for end-to-end-latency.
- Den eksisterende uploader-statusfil beriges med `last_put_ms`, `last_manifest_published_at`, `last_manifest_sequence` og `latest_segment_local_age_seconds` (kun lokale målinger, ingen nye databasekald for disse målinger).

## Gate: før en 1247-release overhovedet godkendes

1. GitHub CI (alle jobs) skal være grøn. Kør også produktionens eksisterende smoke-test. **Lokale tests er ikke en erstatning for GitHub CI.**
2. Deploy **backend/frontend først** mens Viborg1 fortsat kører 1246. Bekræft at Remote Desktop stadig virker på den gamle client-agent via control-fallback.
3. Byg og verificér derefter kun en **1247 pilotkandidat** fra den godkendte main, ikke fra denne ZIP alene. Test udelukkende på Viborg1; ingen ny environment-variabel, credential-nulstilling eller reinstall.
4. Test med stabil backend uden Render-redeploy i målevinduet. Log faktisk anvendt transport (WSS eller HTTPS), 5–10 minutters input med klik/drag/release/taster og 5–10 minutters Livestream. Gentag efter kontrolleret kortvarigt forbindelsestab. Test også filkanalen og sessionsafslutning.
5. Sammenlign før/efter ved samme netværk og billedkvalitet: `input_queue_ms_avg/max`, `input_rpc_ms_avg/max`, `relay_send_ms_avg/max`, `input_to_frame_ms_avg/max`, browser transport-RTT og synlig reaktion på skærmen. For HLS: `last_put_ms`, `latest_segment_local_age_seconds`, HLS.js-lag og **faktisk observeret** forskel mellem klientskærm og afspilning. HLS.js-lag alene måler ikke nødvendigvis capture-/uploadforsinkelse.
6. Stop hvis input bliver hængende, knapslip mistes, filer fejler, sessioner genåbnes uden autorisation, manifestet refererer manglende segmenter, backend/DB-belastning vokser eller livestreamen ikke viser en faktisk forbedring. Behold 1246 og korrigér kandidaten.

## Sikre lokale read-only observationer på Viborg1

```bash
sudo python3 - <<'PY'
import json
from pathlib import Path
paths = [
    Path('/var/lib/clientflow/remote-desktop/media-telemetry.json'),
    Path('/var/lib/clientflow/livestream-uploader/status.json'),
]
for path in paths:
    print(f'===== {path.name} =====')
    if not path.is_file():
        print('NOT_FOUND')
        continue
    data = json.loads(path.read_text())
    if path.name == 'media-telemetry.json':
        for session, row in data.get('sessions', {}).items():
            print('session:', session)
            for key in ('capture_ms_avg', 'relay_send_ms_avg', 'input_queue_ms_avg',
                        'input_queue_ms_max', 'input_rpc_ms_avg', 'input_rpc_ms_max',
                        'input_to_frame_ms_avg', 'input_to_frame_ms_max'):
                print(f'  {key}: {row.get(key)}')
    else:
        for key in ('state', 'last_put_ms', 'last_manifest_sequence',
                    'latest_segment_local_age_seconds', 'last_manifest_published_at'):
            print(f'{key}: {data.get(key)}')
PY
```

Ingen af disse tal må omtales som dokumenteret lavere end 1246, før der er lavet en kontrolleret pilotmåling.

## Sikkerheds- og driftsbemærkning

En tredje agentkanal medfører også et ekstra 15-sekunders credential-revalideringstjek **mens inputkanalen er tilsluttet**, i overensstemmelse med de eksisterende kanalers sikkerhedsmodel. Det er ikke gratis på backend/databasen; måles i piloten, og må ikke skjules som nul ekstra DB-kald. Selve telemetrien og RTT-pings kræver ingen database.

## Teststatus på udviklingsmiljø

- `python -m compileall`: PASS for de berørte Python-moduler.
- Lokale relaterede pytest-kørsler (Remote Desktop, HLS, legacy-gates): **65 passed, 2 skipped**. To tests kræver ekstra lokale afhængigheder (herunder SQLModel), som ikke var installeret i miljøet. Nye pure-Python input/HLS-tests er kørt.
- **Ikke udført/ikke påstået:** GitHub CI, frontend `npm ci` + fuld lint/build, Render-deploy, faktisk 1247-bundle, netværks-/USB/HID-måling på Viborg1 eller stabil-backend-pilot. Disse er obligatoriske før releasegodkendelse.
