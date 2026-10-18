# ClientFlow 1.3.39 / seq 1240 – pilotfejl og permanent kildekoderettelse

**Status 18. oktober 2026:** Heidi1/Viborg1 er fysisk, lokalt og i backend godkendt tilbage på **1.3.38 / seq 1239**. Den fejlede deployment `703c5a33-192d-4a7b-b7d4-78a2f1413cab` forbliver `recovery_failed`; `CLIENTFLOW_1240_PILOT_CLIENT_ID` er fjernet. Ingen automatisk ny pilot er autoriseret.

## Dokumenteret fejl

- Installeret controller: `User=root`, `ProtectHome=yes`, ingen bind-undtagelse for `/home/clientflow-kiosk`.
- Canonical release-transaktionen forsøger `setfacl` og `find ... setfacl` under `/home/clientflow-kiosk` fra controller-servicens isolerede mount namespace.
- På Viborg1 viste den fysiske reproduktion, at `ProtectHome=yes` gav `SANDBOX_HOME_VISIBLE=False`, mens `ProtectHome=tmpfs` + `BindPaths=/home/clientflow-kiosk` gav både kiosk-home-adgang og `setfacl --test=0`.
- Aktivering 1.3.39 fejlede; rollback 1.3.38 fejlede. Den konkrete oprindelige undtagelse blev ikke bevaret i transaktionshistorikken. Konflikten er reproduceret, men er ikke bevist ved et historisk exception-trace.
- Manuel checkpoint-bundet recovery genoprettede 1.3.38. Alle 45 systemd-definitioner, release-state, runtime-services, backend-tilstedeværelse og fysisk skærm/GUI bestod efterkontrol.

## Kildeændringer (ikke en release)

1. Controller-unit bruger `ProtectHome=tmpfs` og **kun** `BindPaths=/home/clientflow-kiosk` og bevarer øvrig systemd-hardening.
2. Staging/aktivering afviser target-releases med inkompatibel update-controller-home-sandbox **før** backend aktiveringsautorisation. Dette er en fail-closed kompatibilitetskontrol; allerede godkendt 1.3.39 bliver ikke automatisk tilladt igen.
3. Transaktionen gemmer begrænsede, ikke-følsomme fejldetaljer for både aktivering og automatisk rollback: fejltrin, klasse, eksekverbart program og exitkode, hvis kendt. Ingen stdout/stderr, command-argumenter eller credentials gemmes i release-history.
4. Automatisk controller-recovery: Når backend stadig har en aktiv deployment, der matcher den lokale, dokumenterede `automatic_rollback_failed` og `activation_intent`, prøver controlleren én afgrænset genoptaget rollback til den **tidligere** release før backend får terminal `recovery_failed`.
5. Recovery låser den kanoniske release-transaktion, kontrollerer exact release-ID'er, approval-reference, historik, active link og den tidligere releases verificerede prepared tree. Ingen ny activation af den fejlede release; kun genopstart/health-check af tidligere release. Health-grænsen gemmes før boot-enable. Ved fejl bevares `activation_intent` og logges det præcise fejlede trin.
6. Privilegeret transaktions-CLI får den eksplicitte nødfunktion `recover-failed-update` for en lokalt uafsluttet, dokumenteret in-place rollback, også hvis backend-deployment allerede er terminal. Funktionen **ændrer ikke** backend-historik. Den kræver root og eksakte release-/approval-bindinger.
7. Regressionstests dækker sandbox-kontrakten, unsafe target-afvisning, lokal state-integritet, health-fail-closed, original/rollback-diagnostik samt rapportering af `rolled_back` i stedet for `succeeded`.

## Kritisk overgang: gammel 1.3.38-controller

**En ny release kan ikke ændre sikkerheds-sandkassen i den controllerproces, som allerede kører fra 1.3.38.** At inkludere `ProtectHome=tmpfs` i en fremtidig target-release er ikke tilstrækkeligt til en in-place opdatering fra 1.3.38. En kontrolleret **én-gangs bro** er nødvendig på Heidi1, eller man må anvende fresh-install til den nye version. Ingen automatisk eller skjult ændring af gammel release er forsvarlig.

`scripts/clientflow_1338_controller_bridge.sh` er en **ikke-eksekveret** værktøjsforberedelse:

- Standardkørsel uden argumenter er kun preflight (læser state/units).
- Ændring kræver root og præcis `--apply --confirm-clientflow-1338` samt aktiv og verificeret 1.3.38 og ingen eksisterende controller-drop-ins.
- Broen lægger en separat, root-owned systemd-drop-in med den allerede fysisk afprøvede snævre mount-adgang. Den ændrer hverken de immutable releases, symlink, database eller release-state.
- **Må først bruges efter særskilt operatørgodkendelse, ny grøn GitHub CI, backend-gate med 0 aktive deployments og en ny, godkendt target-release.**
- Efter en vellykket opdatering skal drop-in'en fjernes kontrolleret, **kun** når den nye aktive controller-unit selv har samme beskyttelse, den lokale transaktion er afsluttet, og fysisk accept er grøn.

## Operationel sandbox-test på en fysisk Ubuntu-klient

`scripts/clientflow_controller_sandbox_probe.sh` kører et midlertidigt systemd unit under `ProtectHome=tmpfs` og `BindPaths=/home/clientflow-kiosk`. Den kontrollerer kiosk-home, at øvrige hjemmemapper er skjult, og ACL-dry-run med `setfacl --test`. **Ingen aktive ClientFlow-enheder eller state ændres.** Kør kun med root på en godkendt testmaskine efter kontrol af scriptsource.

## Release- og CI-gates

- ZIP-filen, hvorfra denne kildekodepatch er udledt: `display-planiq-main(20261018-152435).zip`.
- Denne patch er **ikke** en godkendt release og rører ikke `client/VERSION`, `client/release/release-input.json`, backend-katalog, SHA/approval-artifacts eller pilotvariabler.
- Release-sekvensen hos Heidi1 er allerede **1240**, selv om klienten igen kører 1.3.38. En ny in-place target-release skal have en **strengt højere sekvens** og gennem hele source-freeze, approved artifact, staging, CI og backend authorization.
- Alle normale GitHub CI-jobs er obligatoriske; lokale tests er kun forberedende. Den operationelle backend-integrationstest kræver de låste CI-afhængigheder og database.
- Afslut først næste pilot efter korrekt backend-status, fysisk accept (Chrome/Wayland + GUI), version/release-state, systemd timers og en genstartstest, som **først** må udføres efter sundhedskontrol.

### Relevante upstream-kilder

Systemd beskriver `ProtectHome=tmpfs` + `BindPaths=` som måden at vise én bestemt hjemmemappe, mens øvrige holdes skjult; `ProtectHome=yes` kan ikke kombineres med en nested bind mount under `/home`.

- https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html
