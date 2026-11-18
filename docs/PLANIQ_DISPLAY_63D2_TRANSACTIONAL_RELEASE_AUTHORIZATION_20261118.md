# PlanIQ Display · Fase 63D-2 · Transaktionel releaseautorisation (forberedelse)

**Kilde:** `display-planiq-main(20261118-101520).zip`, GitHub `main` `f51d06de8f81244ec1c677b9412573c26066822d`. Denne fase ændrer **ikke** live deployment, Render-konfiguration, klientsoftware, databasmigrationer eller release-godkendelse.

## Formål

Byg og test den kommende transaktionelle DB-bølgeautorisation **før** den tilsluttes den eksisterende klient-deployment-router. Den eksisterende envejs-pilot og 1245-godkendelse skal stadig være selvstændige sikkerhedsgates, og en gennemgået kladde er aldrig en tilladelse.

## Leverance

- Ny isoleret `clientflow_release_wave_transactions.py` med PostgreSQL-`FOR UPDATE` i fast klient → releasepolitik → bølge → mål-orden. Databasekontrol forbliver `cutover_enabled=False` og `fleet_open=False` i live konfiguration. Koden returnerer derfor ikke en autorisation under nuværende policy.
- Kandidaten identificeres fra det *kanoniske* katalog og fra de eksisterende funktioner, der verificerer publicerede, signerede bytes (`deployment_release_snapshot`). Klient-/release-/bundle-SHA, størrelse, signaturreference, kandidat-SHA og kildecommit skal matche.
- Kræv aktiv, godkendt klient; ingen samtidig System-handling; superadministratoraktør; frisk aktiv Status-credential med samme klient, gyldig releaseversion og maksimum 90 sekunders statusalder; korrekt policiesrevision; nøjagtig én godkendt target; gyldig godkendt bølge og én entydig fysisk acceptance-række for samme release/SHA; ingen udløbne eller forbrugte mål.
- Fremtidig oprettelse af et `ClientFlowDeployment` og overgang af `ClientFlowRolloutTarget` til `consumed` samt wave til `running` udføres i **én ucommitted SQLModel-transaktion**, hvorefter en eksplicit kaldende route engang skal udføre audit og commit. Intet i modulet foretager et commit eller et deployment på egen hånd.
- Den gamle uafhængige pilot-/stable-policy kræves som callback under klientlåsen. Ingen mulighed for at autorisere rollback/downgrade gennem denne funktion.
- Negative SQL-integrationstests (køres i den normale GitHub CI, der installerer `sqlmodel`): drift i SHA/release/policyrevision, forældet eller tilbagekaldt credential, offline eller forkert kildeversion, udløb, falsk/uklar fysisk accept, dobbelt forbrug, stop/pause, rollback før commit, forkert actor og bortfald af eksisterende godkendelse. Yderligere dependency-free kildekontakt afviser enhver live router-tilkobling.

## Hvad 63D-2 bevidst ikke gør

1. Ingen ny fysisk pilot, signeret release eller runtime-input-transport. `1.3.45/1246` er stadig kun kildekandidat, og `1.3.44/1245` forbliver eneste katalog-stable.
2. Ingen API til at promovere en release, registrere fysisk pilotaccept, godkende/forbruge en DB-bølge eller aktivere DB-cutover. De funktioner kræver særskilt design af step-up, revisionsspor og de eksisterende udrulningskald før fysisk pilot.
3. Ingen nyinstallations-gate eller automatisk opdatering. Ingen reauth-svækkelse, env-flag-ændring eller frigivelse af installationslåse.
4. Intet bevist for 100 klienter eller reel samtidighed i PostgreSQL fra lokale SQLite-tests; dette kræver dedikeret Postgres-race-gate og en fysisk Ubuntu 26.04/Wayland-pilot.
5. Ingen påstand om, at alle release-administrationsfunktioner er færdige. En ny audit/commit/HTTP-integration skal tilsluttes senere og have en separat fysisk accept/rollout-beslutning.

## Næste sikkerhedsgate

Når fuld GitHub CI er grøn: verificér den transaktionelle motor i disposable PostgreSQL med konkurrerende samtidige kald og rollback. Dernæst færdiggøres *den menneskelige godkendelseskæde* og signeret release-kandidat. Lad den gamle eksplicitte pilot-gate være eneste live-autoritet indtil et særskilt, verificeret DB-cutover. Kode-merge alene må aldrig starte en klientopdatering.
