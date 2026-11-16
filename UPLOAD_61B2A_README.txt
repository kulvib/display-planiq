PlanIQ Display 61B-2A – KILDEBRANCH (ingen aktiv release)

Basis: den vedhæftede display-planiq-main(20261116-082716).zip.
Branchforslag: feature/display-61b2a-update-maintenance-20261116

Udgangspunkt: opret en NY branch fra samme main, ikke en release-tag.
Udpak ZIP og upload de eksisterende mapper/filer uden at overskrive andre filer.
Filen SHA256SUMS.txt er hele det opdaterede manifest.
Dette arkiv indeholder ikke en komplet repo-kopi, ikke en signeret klientrelease.

Kør GitHub CI og gennemgå afvigelser; merge/deploy ikke før CI og kodeaudit.
Efter merge er ændringer i klientens runtime stadig IKKE på en fysisk klient.
Build/signering/godkendelse og fysisk pilot kræver en særskilt gate.
Alle ClientFlow 1245/pilot/fleet/fresh-install/cutover-gates forbliver lukkede.

61B-2A afgrænsning: OS/firmware-browserlås, lokal status og Control Room.
IKKE FÆRDIGT: separat fullscreen-maintenance-skærm, fælles ClientFlow
release-lifecycle i status, signeret release, fysisk pilot eller fleet-rollout.
Se docs/CLIENTFLOW_61B2_OS_FIRMWARE_MAINTENANCE_STAGING_20261116.md
