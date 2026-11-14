# PlanIQ Display – ClientFlow Livestream liveness / recovery, kildekandidat

**Grundlag:** `display-planiq-main(20261114-145213).zip` (14. november 2026). Brugerens webadministration har grøn CI og smoke-test. Klient Viborg1 har fortsat den godkendte **1.3.43 / sequence 1244**. Denne ændring er **kun kildekode**: Ingen ny signeret release, ingen tilladelse til in-place opdatering, ingen ændring af den godkendte releasekatalogpolitik.

## Dokumenterede observationer

- I den tidligere hændelse modtog `pipewiresrc` nul source buffers efter oprettet Mutter ScreenCast-node. To 25-sekunders opstartsforsøg mislykkedes, tredje forsøg kom i gang.
- Både Livestream og Remote Desktop er også verificeret fungerende samtidig i begge opstartsrækkefølger. Dette beviser **ikke**, at en samtidighedskonflikt forårsagede den tidligere fejl.
- Ved et fungerende HLS-stop blev `source_buffers=734`, `encoded_buffers=691`, `muxed_buffers=0` logget. GStreamer kan levere bufferlister, som den gamle `BUFFER`-probe ikke medregnede.
- WiFi-afbrydelsen 13. november kl. 18.22 var bevidst udført af operatøren. Den er en separat transporthændelse, ikke dokumentation for Mutter-fejl.

## Samlet kodeændring (separat branch, ikke produktion)

1. **GStreamer HLS buffer-tæller**: Se både `Gst.Buffer` og `Gst.BufferList` på de tre eksisterende pipeline-trin. En bufferliste tælles efter sit antal buffere, uden at billeder eller medieindhold logges. Beholder eksisterende lognøgler, så observabiliteten er bagudkompatibel.
2. **Efter-opstart output-watchdog**: Efter det første HLS-segment kontrolleres kun playlistens/segmenternes filmetadata. Hvis *ingen* nye HLS-outputændringer observeres i 90 sekunder, logges en maskinlæsbar `clientflow_hls_stalled` med stadieindikation, og capture-helperen afsluttes med fejl. Supervisorens allerede eksisterende ønsket-tilstandsmekanisme kan derefter forsøge en ny capture-proces. Der inspiceres ikke pixels, så et uændret skrivebordsbillede alene udløser ikke en genstart.
3. **Løbende diagnosticering**: `clientflow_hls_running` udskrives hvert 30. sekund med output-alder og trin-tællere, så stillestående output kan lokaliseres i journalen uden brugerdata.
4. **Observerbar capture-exit**: `livestream_producer` journalfører `capture_process_exited` og skriver en kort `failed`-status med `exit_code`, før den eksisterende restart-/desired-state-logik overtager. Systemd-processen må ikke bruges som eneste indikator for at den individuelle optagelse er rask.
5. **Målrettede tests**: Stubbet GStreamer beviser normal output-fremdrift, stillestående desktop med nye segmenter, reel 90 sekunders HLS-stall, håndtering af `BUFFER_LIST`, oprydning af pad-prober og diagnosticering af uventet capture-exit.

## Bevidst uændret

- HLS bitrate/fps/preset, 25-sekunders opstartsdeadline, 2-sekunders segmenter, GNOME/Mutter DBus og PipeWire source-indstillinger.
- Kiosk/Chrome, terminalhelp/WiFi, kontrolkanal og Remote Desktop – disse blev allerede ændret og verificeret i den seneste `main`-kandidat.
- Sikkerhed, credentials, MFA, permissions, release/rollback/gates, checkpointer, retention og databasen.

## GO / NO-GO kriterier

**Kode-GO** kræver alle målrettede tests, source checksums, fuld GitHub CI, lint, dependency audit og review af log/status-kontrakt. **Runtime-/release-GO** kræver derudover:

- Ren, byggbar ny versionsidentitet og officiel signeret release-approval. Godkendelse af in-place opdatering må aldrig antages ud fra den gamle `fresh_install`-katalogpost.
- Fysisk pilot på Ubuntu 26.04.1, både ved statisk skærm og aktiv skærm: HLS-output må ikke blive fejlagtigt markeret som stalled; sikker stilstand på 90 sekunder skal genetableres uden recovery-loop.
- Livestream alene, Remote Desktop alene, begge rækkefølger, stop/genstart, reboot, kontrolleret WiFi-tab, cookie-reload og statusindikatorer.
- Ingen test må svække eller omgå sikkerhedsgates. **Ingen installation eller ændring på aktiv Viborg1 uden særskilt, eksplicit beslutning**.

## Åbne risici

- Den præcise upstream-rodårsag til den periodiske nul-buffer-fejl er stadig ikke bevist. En post-start watchdog kan afhjælpe et efterfølgende output-stall, men ikke gøre de første 25 sekunders PipeWire-opstart fejlfri.
- Watchdogens 90 sekunders grænse er en kandidat. Den skal fysisk valideres på en GNOME/Wayland-klient med strømstyring og langvarigt statisk billede.
- `BUFFER_LIST`-målingen er dokumenteret ved enhedstest med GStreamer-stubs, ikke ved fysisk hardwaretest med aktiv pipeline.
