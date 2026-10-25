# PlanIQ Display – sikker genbrug af en eksisterende rollbacknøgle (70A)

## Din beslutning

**Hvis der allerede findes en gyldig central Ed25519-rollback-signeringsnøgle, genbruger vi den.** Ingen automatisk nøglegenerering eller -rotation. Du er ejer af den private nøgle og behøver ikke forstå kryptografien for at udføre kontrollen. Send **aldrig** den private nøgle til ChatGPT, GitHub, en supportmail eller en frontendside.

## Det er vigtigt at skelne mellem nøglerne

PlanIQ Display anvender flere forskellige nøgler. Klienternes individuelle Ed25519-opdateringsnøgler, JWT-hemmeligheder og eventuelle ældre release-signaturer er **ikke** automatisk den centrale rollback-signeringsnøgle. Den nuværende kode bruger udelukkende en særskilt Ed25519-privatnøgle i Render-hemmeligheden `CLIENTFLOW_ROLLBACK_SIGNING_KEY_PEM_B64`. Vi må **ikke** kopiere eller genbruge andre nøgler på tværs af sikkerhedsformål uden særskilt sikkerhedsgennemgang.

## Nem kontrol – først i Render, uden at afsløre nøglen

Når 70A er merged og Render er redeployed, åbn **Render Shell** for Display-backend-servicen, og indsæt **kun denne kommando**:

```bash
cd /opt/render/project/src && python3 scripts/clientflow_existing_rollback_key.py
```

Den læser kun den allerede konfigurerede rollbacknøgle, hvis den findes i denne service. Den opretter, gemmer, uploader og aktiverer intet. Den viser højst den **offentlige** nøgleidentitet og et statusresultat.

- **“Eksisterende ... fundet ... GENBRUG DEN”**: Nøglen findes i denne service og har korrekt format. Notér nøgle-ID'et; send ikke private data.
- **“Ingen rollbacknøgle konfigureret”**: Der er ingen nøgle i netop dette miljø. Nøglen kan stadig være opbevaret hos dig i din adgangskodeadministrator eller et andet godkendt nøglearkiv. **Generér ikke straks en ny nøgle.**
- **“... ugyldig”**: Stop. Vi reparerer ikke dette ved at overskrive eller automatisk rotere nøglen.
- **“Rollback-feature (kun observation): enabled”** før en godkendt fysisk pilot: Stop og undersøg konfigurationen; kontrollen deaktiverer ikke noget.

I Render kan status for kildefilens trust vises som `not_available_in_backend_runtime` – det er forventet, fordi backenden deployes uden klientens releasekilde. Vi kontrollerer source-trust separat i GitHub CI.

Scriptet kan også med et særskilt, senere godkendt kald `--public-trust` vise en **offentlig** nøglepost, der kan pinne den nøjagtigt samme identitet i en ny 1.3.41-release. Det er stadig **ikke** godkendelse til at aktivere rollback.

Hvis du allerede har nøglen sikkert opbevaret lokalt, men den **ikke** findes i Render, håndterer vi dens identitet og sikker provisionering i en efterfølgende separat godkendt fase. Du skal ikke uploade nøglefilen her.

## De næste sikkerhedsgates

1. Verificér, om den dedikerede private rollbacknøgle allerede eksisterer. **Genbrug den, hvis gyldig.**
2. Afstem dens **offentlige** nøgle-ID med `client/release/rollback-trust.json`; eksisterende repo har endnu `enabled=false`, `keys=[]`.
3. Fastlås den tilsvarende offentlige nøgle i source-release 1.3.41 / 1242. Opdater aldrig de gamle immutable 1.3.40-installationer indirekte.
4. Kør GitHub CI, signeringsgates og reproducerbar release-build. Kræv særskilt autorisation til publication og **fysisk pilot på en reserveklient**.
5. Hold `CLIENTFLOW_SIGNED_ROLLBACK_ENABLED=false` indtil fysisk accept og separat godkendelse. En aktiv rollbackknap må **ikke** indføres, før fjerntransport, autentifikation, rapportering og recovery er end-to-end-verificeret.

Kommandoen kan ikke bevise, at en nøgle **ikke** findes uden for Render; den registrerer kun det aktuelle miljø. Ingen private hemmeligheder skal nogensinde indgå i source, ZIP, frontend, driftlogs eller ChatGPT.
