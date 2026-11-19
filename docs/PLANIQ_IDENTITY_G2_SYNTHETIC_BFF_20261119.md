# PlanIQ Display · G2 synthetic BFF proof (19. november 2026)

**Forskningsforberedelse oven på draft-PR #389. IKKE et produktionslogin.**
Den valgte Keycloak/authentik-leverandør har endnu ikke bestået G1.
Arbejdet foregår derfor offline med en falsk OIDC-udbyder, ingen produktive
Identity-credentials, ingen Render/Neon ændringer og ingen brugere.

## Hvad denne samlede fase tilføjer

Modulet backend/identity_integration_prep/synthetic_bff.py simulerer
en fremtidig server-side login- og sessionsgrænse uden at importeres i
den kørende Display-service. Modulet er **ikke en FastAPI-router**.

- En kodeautorisation får servergenererede PKCE S256-verifier/challenge,
  nonce og state bundet til en tilfældig lokal browsersession.
- Det midlertidige, test-only SQLite-lager kræver eksplicit opt-in og
  et disponibelt filnavn. BEGIN IMMEDIATE og engangssletning af state
  gør parallelle callbacks gensidigt udelukkende på tværs af forbindelser.
- En injiceret syntetisk IdP-funktion skal verificere PKCE og redirect
  og returnere et signeret ID-token; Display accepterer kun signeret,
  korrekt issuer/audience/nonce fra sin forudbetroede, lokale JWKS.
  Inaktiv, ulænket eller forkert lokal bruger afvises; ingen email- eller
  IdP-gruppebaseret oprettelse/rolleeskalation.
- En syntetisk lokal session opbevarer kun hashes af tilfældige
  sessions- og CSRF-secrets. Den kontrollerer seneste brug, udløb,
  revokation, aktuel lokal adminrolle, organisationsrelation og
  stadig godkendt issuer+sub-link ved anmodninger.
- Skrivehandlinger afvises ved forkert Origin/CSRF, og logout tilbagekalder
  lokal session. Fremtidig IdP-nedetid kan ikke skabe en ny login-session,
  mens en allerede etableret *lokalt gyldig* session ikke laver IdP-poll.
- Negative tests dækker identitetsforveksling, replay på én eller to
  processer, stjålne sessioner, tokenmanipulation, dobbelte links,
  nedgraderede lokale roller, udløb og back-end-restart.
- Testene kontrollerer særskilt at service1/main.py, auth.py,
  frontend, ClientFlow, Remote Desktop, terminal og kompatibilitetsruter
  **ikke** importerer prototypen.

## Stopper før faktisk integration

Den syntetiske SQLite-store er **ikke en anbefaling om SQLite i drift**,
ikke en migrering og ikke en godkendt sessionstore. En kommende
providerkvalificeret G2-klon kræver separat:
1. Sikker, vedligeholdt OIDC-leverandør, discovery, signatur/JWKS-rotation,
   reel kodeudveksling, callback-beskyttelse, opdaterings- og revokationsflow.
2. Postgres-baseret transaktionslager og migrationsdesign, ikke testens SQLite.
   Sikker HttpOnly-cookie/SameSite/Secure, browser-Origin + CSRF, rate limits,
   audit og reauth-/step-up-kontrol.
3. Eksplicit verificeret identitetslinking med recovery, audit og konflikt/
   migration/rollback. Intet e-mail-only bootstrap, intet JIT-rolegrant.
4. Rigtig browser/MFA/passkey/UV, logout/back-channel, sessionstider og
   fysisk ClientFlow-regression uden IdP-afhængighed.
5. Særskilt godkendelse af isoleret Display-G2-klon, cloudressourcer,
   leverandør og eventuel senere produktionsaktivering.

**Denne PR må ikke i sig selv aktivere fælles Identity eller ændre
Display/Worklog/Flow/Events i produktion.** Identity G1/PR #12
forbliver draft med tre officielle CVE-blokeringer, 94 uafviklede
leverandørtestcases og otte afventende cloudgates.
