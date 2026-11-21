# Fase 63D-16: 1.3.47/1248 kildefrys, midlertidig fjerde TAR og fysisk Viborg1-pilot

## Leveret som kildeændring

- Kildeidentiteten er ændret fra `client/VERSION=1.3.46`, sekvens 1247 til
  **`1.3.47`, sekvens `1248`** i `client/release/release-input.json`.
- Den eksisterende kanoniske release-build-gate accepterer **kun** denne nye,
  usignerede kandidat. `clientflow_63d11_prevent_duplicate_build.py` forbliver
  uændret og afviser stadig nye 1247-bytes som allerede godkendt.
- Historiske 1245/1246/1247-artifakter, approval-locks og stage-kataloger er
  **ikke** omskrevet. Aktivt katalog er endnu sekvens 1247 med kun 1245 stabil.
- Historiske read-only-preflights kan nu genkende 1248 som separat usigneret
  efterfølger, uden at udvide udrulnings-, rollback- eller fresh-install-autoritet.
- Render-release-store tillader kun en **eksplicit** og eksakt 1248-publicering
  som fjerde TAR; tre-release-standardpolitik består efterfølgende.

## Ikke udført – kræver særskilte gates

1. Godkend kildebranch med grønt **GitHub CI** for præcis source SHA.
2. Kør det kanoniske release-build-workflow med låst runtime-input-transport
   og krævede SHA'er, to reproducerbare uafhængige builders og valideret
   `REPRODUCIBILITY.json`.
3. Gennemfør **manuel** signering og approval for præcis 1248-TAR. Ingen
   genbrug af den godkendte 1247-signatur, approval-reference eller SHA.
4. Verificér faktiske Render-diskbytes til `1248_size + 64 MiB` reserve, og
   publicér med det eksplicitte `--authorize-1248-viborg1-fourth-storage-only`.
   **Ingen generel fjerde valgbare release** i kataloget.
5. Udarbejd og få godkendt **separat 1248 update-only-katalogstage**, kun for
   klient **ID 3**, fra præcis `1.3.46/1247`, og én autoriseret transaktion.
   Endelig releaseinstallering må ikke omgå den godkendte deployment-motor.
6. Fordi den installerede 1247-controller mangler koordinatorrettelsen, skal
   1247→1248-installationsforløbet have samme testede one-shot-låsning og
   journalført postflight som i 63D-14. Genaktivér **ikke** updater-timeren.
7. Fysisk accept: første PipeWire-buffer, kontinuerlige HLS-segmenter,
   faktisk Livestream-billede, Remote Desktop med friske frames og input,
   reconnect og reboot; mål forsinkelse og belastning. CI alene er ikke accept.

## Opbevaringsbeslutning

1245 er fortsat stabil, 1246 og 1247 er historisk godkendte og bevares fysisk.
Den nye 1248 er kun en midlertidig lagerundtagelse. En femte TAR eller
sletning af 1245/1246/1247 kræver ny, særskilt eksplicit beslutning.
