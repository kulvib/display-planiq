PLANiQ DISPLAY 62C - CI-RETTELSE / FastAPI Body(default=None)
17. november 2026

MÅL-BRANCH: feature/display-62c-session-head-health-calendar-401-20261117

Upload KUN: 
  backend/tests/test_logout_session_fencing_62c.py
  SHA256SUMS.txt

ÅRSAG: De 5 direkte kald til auth.logout i 62C-testen omgår FastAPI
dependency injection. Derfor er den deklarerede standardparameter
Body(default=None) et FastAPI-objekt i Python, ikke en fortolket None-værdi.
4 af 5 tests ramte dermed AttributeError før deres sikkerhedspåstande.

RETTELSE: Samtlige direkte kald sender nu eksplicit body=None,
svarende til en normal HTTP logout-request uden JSON-body.
Produktionen (backend/service1/auth.py) er IKKE ændret.
Ingen sikkerhedspåstande er fjernet eller lempet.

KRAV: Kør fuld GitHub CI i den eksisterende branch.
STOP hvis nogen tests fejler. Ingen merge eller Render deploy før grøn CI.
Ingen produktionsdata, signerede releases eller gates ændres.

Indhold: kun to repo-filer plus denne vejledning.
