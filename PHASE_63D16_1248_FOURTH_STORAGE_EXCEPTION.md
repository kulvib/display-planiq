# 63D-16 – midlertidig fjerde, signeret ClientFlow-TAR på Render

Dette er kun en **lagerundtagelse** til den planlagte Viborg1-accepttest. Den
bevarer 1.3.44/1245 (stabil), 1.3.45/1246 og 1.3.46/1247 som uændrede,
verificerede og signerede TAR-filer og tillader **udelukkende**
`clientflow-1.3.47-seq-1248` som den fjerde.

- Den almindelige retentiongrænse forbliver **3**. `inspect_store` rapporterer
  fortsat korrekt `within_approved_limit=false` ved fire. Dette er en eksplicit
  midlertidig pilotundtagelse, ikke ny generel retentionpolitik.
- Normal publicering af en fjerde version blokeres stadig. Kun flaget
  `--authorize-1248-viborg1-fourth-storage-only` kan anvendes ved den
  specifikke 1248-publicering. Alle eksisterende signatur-, SHA-, kilde-,
  tilladelses- og diskpladskontroller er fortsat obligatoriske.
- Katalogets `max_selectable_versions=3`, `max_installable_versions=1` og
  `latest_stable=1.3.44` ændres ikke af denne lagerundtagelse. Senere separat
  1248-katalogstage og klientbundet autorisation skal godkendes før pilot.
- Flaget giver **ikke** tilladelse til installation, rollback, automatisk
  updater, fresh install eller bred udrulning.
- Der foretages **ingen sletning**, heller ikke efter forsøget. En senere
  tilbagevenden til 3 kræver særskilt dependency-audit og eksplicit godkendt
  arkivering/decommission.
- Før publicering skal faktisk Render-fri plads dokumenteres til
  `1248_tar_size + 64 MiB` reserve. Den lokale kilderepo-bump og signering
  for `1.3.47/1248` skal også være gennemført og CI verificeret.
- `1247` på Viborg1 og den deaktiverede updater-timer forbliver uændret, indtil
  en separat sikker installation af 1248 er autoriseret.

Denne fase er **kildeklargøring**; ikke en godkendelse af 1248 eller en
påstand om, at Livestream/Remote Desktop virker fysisk.
