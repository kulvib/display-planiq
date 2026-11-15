PlanIQ Display · Rettelse af 3 CI-fejl · 15-11-2026

Kilde: display-planiq-feature-clientflow-release-admin-db-foundation-61a-20261115.zip (vedhæftet i samtalen).

Mål-branch: feature/clientflow-release-admin-db-foundation-61a-20261115

Rettede filer:
- backend/tests/test_display_authority_53a_source.py
- backend/tests/test_user_impersonation_contract.py
- SHA256SUMS.txt

Årsager og rettelser:
1) To historiske source-kontrakttests forventede en forældet kæde (head -> 59A).
   De kontrollerer nu de faktiske, allerede håndhævede overgange: 59A -> 60A -> 61A.
   Ingen sikkerhedscheck er fjernet eller sprunget over.
2) SHA256SUMS.txt blev ikke opdateret efter rettelserne af SQLModel-kolonnen
   og HTTP-testklienten. Manifestet er genberegnet for de to filer og de
   to opdaterede tests. Alle manifestets registrerede poster er verificeret.

Brug:
1. Pak ZIP'en ud lokalt.
2. Kopiér filerne ind i samme sti på den angivne branch.
3. Commit og push til GitHub; kør den fulde CI, før merge og Render.

Denne ZIP indeholder kun de tre ændrede filer plus vejledningen.
Den forudsætter, at de to tidligere rettelser på branchen er bevaret:
- backend/service1/clientflow_release_admin_models.py (max_length=36)
- backend/tests/test_clientflow_release_admin_61a_http.py (ASGI-klient)

Kontrol: Syntaks/parsing og samtlige SHA256SUMS-poster bestået; migreringskæde
sammenholdt statisk med runner. Fuld CI er IKKE kørt i dette miljø.
