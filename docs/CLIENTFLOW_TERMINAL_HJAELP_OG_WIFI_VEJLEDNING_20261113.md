# ClientFlow – vejledning til terminalens hjælpescripts

**Gælder:** den foreslåede kildeændring efter ClientFlow 1.3.43 / sekvens 1244. Dette dokument og terminalmenuens vejledninger er **ikke** en installeret release. Kør først nye hjælpere på en fysisk overvåget testklient efter godkendt CI og release-pilot.

## Før du vælger et hjælpescript

1. Vælg først **Supportkommandoer** i Remote Terminal. Åbn **»Hvornår skal jeg bruge denne?«** ved den relevante kommando, og læs hele vejledningen.
2. **Indsæt** placerer kommandoen i terminalen til gennemgang. **Kopiér** kopierer uden at køre. **Kør** sender kommandoen til terminalen og starter den.
3. **Kun læsning** betyder ingen tilsigtet ændring af klientens tilstand. Det er stadig muligt at vise interne adresser og driftslogs, som skal kontrolleres inden deling.
4. **Gemmer WiFi-profil** skriver til NetworkManagers beskyttede systemprofilmappe, men aktiverer ikke netværket. **Kan afbryde fjernadgang** betyder et aktivt netværksskift – brug ikke dette uden fysisk nødadgang og aftalt servicevindue.
5. **Admin** kræver gyldig Admin-terminal/step-up. En advarsel i journalen betyder ikke automatisk, at en service er defekt; sammenhold journal, systemd og den faktiske funktion.

## Hurtig fejlsøgning – hvilket script skal jeg vælge?

| Situation | Start med | Følg op med | Hvorfor |
|---|---|---|---|
| Klienten er offline i Control Room | Netværk, DNS, tid og backend | ClientFlow samlet status; Status/System logs | Adskil fysisk uplink, DNS, HTTPS-backend og statusagent. |
| Browseren åbner ikke eller lukker forkert | Display / kiosk browser | Display/browser logs | Sammenhold browserens ønskede og faktiske status med internetgate. |
| Cookie-dialogen vises efter refresh-timer | Display / kiosk browser | Display/browser logs | Undersøg timer og Browser Guards geninstallation efter reload. Accepter ikke samtykke automatisk. |
| Livestream er sort eller langsom | Livestream v2 status | Livestream logs | Se både ønsket processtatus og HLS-fremdrift; `active` er ikke nok. |
| Remote Desktop fryser | Remote Desktop status | Remote Desktop logs; Netværk, DNS, tid og backend | Afklar capture-problem versus tabt WebSocket. |
| Remote Terminal fejler | Terminal status | Terminal logs | Find agent-, broker- og PTY-fejl. |
| Ny version er ikke installeret | Aktiv release / updater | ClientFlow samlet status; Rollbackrapportering / outbox | Kontrollér aktiv release og opdateringsforløb, uden at udløse opdatering. |
| Systemet er langsomt eller løber tør for plads | Disk, RAM og oppetid | Ubuntu / APT health | Undersøg ressourcer og eventuelle pakkefejl. |
| WiFi er væk eller ustabilt | WiFi / NetworkManager diagnose | WiFi udfald og recovery | Fastslå radio, interface, signal, DNS, afbrydelser og recovery. |
| Du skal tilføje et ekstra WiFi | WiFi / NetworkManager diagnose | Tilføj WiFi-profil (uden aktivering) | Gem profilen sikkert uden at flytte den aktive rute. |
| Du vil afprøve en ny WiFi-profil | Planlæg fysisk fallback og servicevindue | Test gemt WiFi (auto-rollback) | Aktivt skift kan straks afbryde Remote Terminal. |

## De tre WiFi-arbejdsgange

### A. Fjernfejlsøgning – kun læsning

Kør **WiFi / NetworkManager diagnose** først. Den viser WiFi-interface, aktuelle forbindelser, kendte netværk, signal, routing og DNS uden at oprette eller aktivere profiler. Brug derefter **WiFi udfald og recovery**, hvis fejlen opstod for nylig; den analyserer de seneste 30 minutter. Logs kan ikke bevise, hvem der betjente WiFi-kontrollen, uden passende proces-/brugerdata. Skjul interne netværksnavne/IP-adresser før deling.

### B. Tilføj nyt netværk uden at risikere den aktive forbindelse

Kør **Tilføj WiFi-profil (uden aktivering)** i Admin-terminal. Hav WiFi-interface, SSID og WPA2/WPA3-personlig adgangskode klar. Password indtastes interaktivt og vises ikke på skærmen; skriv **OPRET** for at gemme. Ved succes vises `WIFI_PROFILE_STAGED=PASS`, `PROFILE_UUID=...`, `AUTOCONNECT=no` og `ACTIVE_CONNECTION_UNCHANGED=yes`. Gem UUID til en senere fysisk overvåget test. **Denne kommando skifter ikke netværk og aktiverer ikke autoconnect.** Virksomheds-WiFi med 802.1X understøttes ikke af den aktuelle hjælper.

### C. Afprøv gemt WiFi med checkpoint – risiko for fjernadgang

Udfør **kun** denne test, hvis nogen fysisk kan gendanne forbindelse ved fejl. Kør **Test gemt WiFi (auto-rollback)** i Admin-terminal og indtast UUID/interface. Godkend først med **TEST**. NetworkManager opretter checkpoint med 120 sekunders timeout og skifter aktivt til den nye profil. Remote Terminal og Remote Desktop kan lukke midt i testen. Bekræft kun med **Yes**, hvis både internet, routing og genoprettet fjernadgang reelt er verificeret. Uden bekræftelse forsøger NetworkManager rollback. Denne mekanisme beskytter ikke mod alle fejl (bl.a. strømsvigt, driverfejl eller firmwareproblemer). Profilen forbliver `autoconnect=no`; en permanent plan for prioritet/fallback kræver særskilt godkendelse.

## Beslutninger for kataloget

- **Bevar alle 20 eksisterende/foreslåede hjælpere:** Hver har et særskilt kontrolområde. Den nye menu viser ikke længere rå bash-kode som eneste forklaring.
- **Ingen sletninger uden dokumenteret overlap eller fejl:** `ClientFlow samlet status` er overblik; målrettede helpers er nødvendige til dybere diagnose. Loghjælperne undersøger andre tids- og procesforløb end statuskommandoerne.
- **Ingen tavse ændringer:** Diagnostik og loglæsning er adskilt fra WiFi-profilskrivning og aktiv netværkstest. WiFi-test kræver menneskelig bekræftelse.
- **Statisk verificering er ikke fysisk godkendelse:** Bash-syntaks, sikrede parametre og UI-kontrakter testes automatisk. Den faktiske WiFi-oprettelse, checkpoint, rollback og kiosk-recovery skal verificeres på Ubuntu 26.04-testklienten før produktion.

## Status og udrulning

Denne kildepakke må ikke anvendes direkte på den aktive 1.3.43/1244-klient. Før release kræves samlet GitHub CI, sikkerhedsaudit, fysisk pilot og eksplicit godkendelse. Den tidligere observerede Mutter/PipeWire-fejl kræver fortsat yderligere årsagsanalyse; terminalvejledningerne løser ikke den fejl i sig selv.
