# PlanIQ Display – isoleret G2-forberedelse til fælles Identity

**19. november 2026 · kun draft-PR og syntetiske tests · ingen loginændring**

Baseline: Display main commit 46f5e65f6e224b0a6f97b3ddc2eb4ee27b6e31c6.
Identitetskrav: PlanIQ Identity arkitekturkontrakt v1.3 med v1.2's
C01–C30. G1 er fortsat åben og uden valgt leverandør.

## Ny backend-kode, men ikke et nyt login

En ny selvstændig pakke i backend/identity_integration_prep indeholder
forberedelse til OIDC Authorization Code med PKCE S256, tilfældig state og
nonce, binding til en tilfældig serverstyret BFF-session, atomisk
engangsforbrug af callback-state og fuld validering af ID-token signeret
med et på forhånd betroet RS256 JWKS.

E-mail, IdP-grupper og token-roller kan ikke tildele Display-adgang.
Først når et issuer + subject-par er **eksplicit verificeret** og
forbundet med en eksisterende lokal bruger, kan den fremtidige
backend overveje en session. Den lokale bruger skal være aktiv
Display-admin eller superadmin og respektere organisation og krav
om passwordskifte. Ingen JIT-/e-mail-only account creation.

Pakken er bevidst **ikke importeret fra service1**, registreret
som FastAPI-router eller eksponeret for frontend. Intet i sessioner,
refresh tokens, eksisterende brugeradministration eller database
er ændret, og der er ingen nye miljøvariabler, migrations, Docker
ændringer eller cloudressourcer.

## Kontrakt til produktintegrationerne

| Produkt | Tidligste integrationsmål | Bevar lokal myndighed |
|---|---|---|
| Display | Isoleret G2-klon efter kvalificeret G1 | Menneskelige administratorer; lokale bruger-ID'er, organisationer og roller; ClientFlow-maskin-, livestream-, terminal-, fjernskrivebord- og releasecredentials er helt uafhængige |
| Flow | Senere isoleret G2-produktintegration | Eksisterende org-, bruger-, admin- og step-up-autorisation |
| Events | Senere isoleret G2-produktintegration | Egne aktive organisationsmedlemskaber og adgangsgrants |
| Worklog | Sidst, G3-migration og særskilt GO | Eksisterende passkeys, MFA, brugerdata, 6h absolut/30min inaktivitet/14d husket browser, saldi, sæsondata og rollback |

## Ufravigelige tilbageværende G2-gates

1. G1-kvalifikation og en eksplicit valgt, vedligeholdt Identity-udbyder.
2. G2-BFF implementerer korrekt fortrolig kodeudveksling, verified discovery,
   JWKS-cache og rotation, eksakt redirect URI, sessionsoprettelse,
   sikre HttpOnly cookies, CSRF og atomisk persistent callback-lager.
3. Produktrettigheder kontrolleres fra Display-DB ved hvert relevant
   operationelt kald, også efter IdP-auth. Login må aldrig oprette
   eller ændre en produktrolle; linking kræver en særskilt, sikker
   tilmeldings- og godkendelsesproces med audit og rollback.
4. Logout/revokation/timeout, konto-/faktorhændelser og
   frisk handlingsbundet WebAuthn-UV-step-up testes med rigtig browser.
5. 1/25/100 syntetiske mennesker og tab af IdP-forbindelse testes
   uden at påvirke nogen ClientFlow-maskine eller kræve IdP-polling.
6. Særskilt isoleret G2-Display-klon, sikkerhedsreview og brugeraccept
   før første kobling til produktionsruter. Worklog-migration må ikke
   følge implicit med nogen anden produktintegration.

## CI-kontroller

backend/tests/test_identity_g2_offline_preparation.py verificerer
negative scenarier: svag/ukendt klient, HTTP eller falsk issuer,
callback- og sessionskift, replay, udløbet state, JWT kid/JWK/alg
substitution, forkerte audience/azp/nonce, udløbne tokens,
uautoriserede roller, dobbelte lokale links, inaktive konti og
manglende organisationsrelationer.

Testen afgrænser også appens importsti: service1, autentifikationsruter,
frontend og ClientFlow-systemer må ikke benytte den nye pakke.
PyJWT og cryptography er eksisterende Display-afhængigheder.

**Status: RESEARCH/PREP ONLY.** Ingen deployment, ingen G2-vendor-PASS,
ingen databaseændringer, ingen aktivering af Identity-login.
