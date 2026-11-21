# PlanIQ Display · 63D-21 · 1248-autorisation i superadministrator-UI

**Kun frontendrettelse. Ingen fysisk deployment, servicestart, klientsystemd-ændring eller signeret TAR-ændring.**

Efter 63D-19 afviste frontendens kandidatvalidator fortsat den nye 1248-kilde, da den kun pin-nede 1246 og 1247. Samtidig fandtes intet 1248-panel i releaseadministrationen. Den allerede etablerede backend-route er /api/clientflow/release-pilot-1248/authorize.

Denne kildeændring pin-ner 1248-kandidatens signatur, størrelse, kilde-commit og approval-reference uden at ændre de ældre registreringer. Et nyt panel gælder kun Viborg1, ID 3, fra version 1.3.46 til 1.3.47/1248 og kræver checkbox, begrundelse og superadministratorens adgangskode. Serveren genkontrollerer version, policyrevision, fysisk signeret TAR, unik Update-credential, friskt Status-bevis, manglende tidligere 1248-bestilling og alle lukkede fleet/cutover/nyinstallationsgates.

UI-teksterne beskriver handlingen præcist: den opretter en rigtig backend-deployment og returnerer et nyt UUID, men starter ikke den deaktiverede systemd-updater. En senere særskilt kontrol skal binde netop dette UUID til den root-private, hash-pinnede 63D-18 one-shot og en reviewet midlertidig /run/systemd/system/-drop-in.

STOP ved fejl og ved manglende 1248-historik: ingen blind gentagelse. Både den installerede 1247, de fire signerede TAR-arkiver og disabled updater.timer forbliver uændrede. Merge og Render-deploy alene autoriserer eller installerer intet.
