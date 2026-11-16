# ClientFlow 61B-2I · Ubuntu preclaim og fælles installationsjournal

## Formål og scope

Kildeændringer, ikke en klientinstallation eller ny godkendt release. Fase 61B-2H
beskyttede allerede første consuming claim og den første health-godkendte aktivering.
61B-2I beskytter også *apt-recovery og Ubuntu package-upgrade før CF-kode*
med samme root-ejede installationsjournal som ClientFlow, Ubuntu og firmware.

## Fuldstændig adgangsmodel

- En ny installation bruger `preclaim_host` med et deterministisk, kanonisk UUIDv5
  bundet til hele den allerede verificerede bundles SHA256. Operation-ID'et er
  **ikke** et bruger-id eller en backend-godkendelse.
- En allerede pending installation genanvender sin originale `fresh_install`-UUID
  til genkontrol af Ubuntu og *beholder* den oprindelige lås indtil holdbart
  verificeret første aktivering.
- `preclaim-run.lock` er root-ejet (0600), lokal og proces-eksklusiv. Den
  forhindrer to samtidige apt-kørsler med samme deterministiske UUID.
- Den delte `state.json` låser alle andre ændringsplaner ude, også efter en
  procesafbrydelse. Ingen tidsbaseret force-unlock og ingen installation efter
  usikker eller fejlende host-readiness.
- En gennemført apt-readiness frigiver **preclaim-only**-ejerskabet, så normal
  initial enrollment kan begynde. Ved enhver fejl forbliver journalen aktiv,
  indtil genkontrol med *præcis samme godkendte bundle* gennemføres. Ingen
  kode i denne fase sletter eller overstyrer en andens journal.
- En afvist first claim må efter 61B-2H fortsat efterlade det sikre, inaktive
  koordinator-katalog. Også det nye `preclaim-run.lock`-inode bevares.

En gammel install-state med allerede aktiv release eller igangværende activation
blokeres desuden skrivebeskyttet **før** preclaim-apt-opdateringen, så et
fejlagtigt resume ikke opdaterer Ubuntu på en allerede aktiv kiosk.

## Samordning, reentrancy og restgrænser

Der eksisterer et begrænset tidsvindue mellem succesfuld preclaim-host-readiness
og initial `fresh_install`-claim: preclaim-ejerskabet frigives, når apt er
verificeret sund, **før** første CF-kode læses. Hvis en OS-/firmwareopdatering
vinder dette vindue, afvises ClientFlow-claim uden at gennemføre backend claim
eller ClientFlow-installation; forsøget må genstartes efter ny preclaim-kontrol.
Der er ikke uafbrudt reserveret ejerskab gennem dette inaktive vindue, og derfor
er komplet flerproces-/fysisk concurrency-accept **ikke** erklæret.

Første fabriksaktivering, efterfølgende release-swap og opdateringer med
reboot skal stadig gennemgå fysisk accept på Ubuntu 26.04/Wayland med kiosk,
netværksforbindelse, offline fullscreen, hostens pakkehåndtering og recovery.

## STOP-kriterier og fravalg

- Alle release-/pilot-/fleet-/nyinstallations-/cutover-gates forbliver lukkede.
- `client/VERSION = 1.3.44` og `release_sequence = 1245` ændres ikke.
- Ingen build, signering, promovering, live apt-opdatering eller CF-kode-forbrug.
- `scripts/clientflow_61b2g_release_source_gate.py` kræver preclaim-låskontrakten
  i de nøjagtige SHA256-verificerede kilder, men kan ikke godkende et deployment.
- En låst/ufuldstændig preclaim på en virkelig klient må kun genoptages efter
  verificering af den **oprindelige** signeret/approved bundle og journal.
  Undlad manuel sletning af `state.json` eller `coordinate.lock`.
- Version/sequence-fremrykning og ny signeret kandidat skal være en særskilt,
  eksplicit godkendt releaseproces efter grøn CI og fysisk preflight.

## Testbevis

Tests dækker eksisterende fremmed lås, simultan genindgang med samme UUID,
apt-afbrydelse/KeyboardInterrupt, wrong bundle, forkert resume-install-id,
root-only file-mode/symlink, clean-install og streng source-gate ved manipulation.
CI er den endelige gate; de lokale tests alene beviser ikke et faktisk
GNOME-/Wayland-handoff eller en maskin-genstart.
