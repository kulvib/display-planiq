# PlanIQ Display – terminalens hjælpescripts (20.10.2026)

Kilde: `display-planiq-main(20261020-175243).zip`. Gennemgået i `frontend/src/pages/clientdetailspage/terminal/ClientTerminalDialog.jsx` med tilhørende runtime- og sikkerhedskontrakter.

## Konklusion

Der var 15 supportkommandoer, fordelt på runtime (7), Ubuntu/host (3) og logs (5). **Ingen af dem bør slettes alene på grund af overlap**: En samlet oversigt og et snævert fejlsøgningsudtræk har forskellige supportformål. Der er ikke i kildeauditten dokumenteret en forældet kommando, som kan fjernes uden at miste anvendelig funktionalitet. De fleste er læseoperationer; alle netværks- og privilegerede udtræk er afgrænset til Admin-terminalen.

| Eksisterende kommando | Anbefaling | Begrundelse |
|---|---|---|
| ClientFlow samlet status | Bevar | Hurtigt overblik over canonical serviceenheder og aktiv release |
| Display / kiosk browser | Bevar | Detaljer om Display-runtime, Chrome og Browser Guard |
| Aktiv release / updater | Bevar | Særskilt update-fejlsøgning |
| Livestream v2 status | Bevar | Producent/uploader/desired-state har særlig driftsværdi |
| Terminal status | Bevar | Særskilt diagnose af Terminal-agent og brokers |
| Remote Desktop status | Bevar | Særskilt diagnose af RD-agent og brokers |
| Aktive ClientFlow units | Bevar | Kompakt liste uden fuldt `systemctl status` |
| Ubuntu / APT health | Bevar | `dpkg --audit`, apt check og behov for genstart; ændrer ikke pakker |
| Disk, RAM og oppetid | Bevar | Lille bruger-terminal-kommando |
| Netværk, DNS, tid og backend | Bevar | Overordnet netværk og backend-reachability, supplerer WiFi |
| Display/browser logs | Bevar | Målrettede logspor |
| Status/System logs | Bevar | Nødvendige ved kommando-/presence-fejl |
| Livestream logs | Bevar | Nødvendige ved streamfejl |
| Terminal logs | Bevar | Nødvendige ved remote-terminal-fejl |
| Remote Desktop logs | Bevar | Nødvendige ved RD-fejl |

## Tilføjet i denne leverance

1. **WiFi / NetworkManager diagnose** (Admin, skrivebeskyttet): aktuel forbindelse, radiostatus, WiFi-adapter, cachet SSID/signal, gemte profilers navne/UUID (aldrig secrets), IP/default-ruter, DNS, NetworkManager status. Ingen tvungen rescan, ingen ændring af interface, ingen log-dump med potentielt følsomt indhold.
2. **Tilføj WiFi-profil (uden aktivering)** (Admin, interaktiv): læser interface, SSID, skjult-netværk-valg og skjult WPA2/WPA3-Personal (PSK eller SAE)-adgangskode direkte fra TTY. Kræver `OPRET`, gemmer en ny NetworkManager-profil med `autoconnect=no`, ruller ufuldstændige profiler tilbage ved fejl. **Ændrer aldrig aktiv forbindelse eller routing.** Ingen adgangskoder indsættes i supportknappens tekst eller i browseren. Kortvarigt kan `nmcli connection modify` argumenter dog være synlige for lokale privilegerede processer, som ved almindelig root-betjening; dette skal medtages i sikkerhedsvurderingen.

### Bevidst ikke automatiseret

Automatisk aktivering/deaktivering af WiFi, skift af default-route, sletning af eksisterende WiFi-profiler og ændringer af NetworkManager/Polkit-regler. Disse handlinger kan afbryde den eneste remote supportkanal og kræver en særskilt, fail-safe omkoblingsprocedure med en testet rollback eller fysisk fallback. Særligt hvis klienten kører via WiFi i forvejen, må en remote kommando **ikke** ukontrolleret skifte SSID.

Kommandoerne forudsætter Ubuntu med NetworkManager/nmcli og WPA2/WPA3-Personal. Enterprise/802.1X og captive portal kræver separat understøttet flow. Den nye WiFi-profil bliver kun brugbar, når den senere aktiveres under sikre forhold. En profil med `autoconnect=no` overtager ikke forbindelsen efter genstart.

## Mulige senere forbedringer

- Udtræk supportkommandoernes lange Bash-tekster til genbrugelige, versionerede testmoduler; behold præcis UI-adfærd.
- Overvej korte sammenfatninger i stedet for fulde `journalctl --no-pager -l`-udskrifter i første supportvisning. Gennemgå logs for potentielle secrets før deling.
- Tilbyd særskilt, **bevidst godkendt** WiFi-cutover med netværksbekræftelse og automatisk rollback, når fail-safe-forløbet kan testes fysisk.
- Måling i produktions-UI, så WiFi-hjælperne er læsbare på mobil uden at afsløre adgangskoder.

Denne fase ændrer **ingen** terminaladgangsregler, backend-API'er, ClientFlow-releasekatalog eller kiosk-Netværkspolitik.
