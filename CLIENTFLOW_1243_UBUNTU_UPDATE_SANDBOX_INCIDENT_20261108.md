# ClientFlow · Ubuntu-opdatering / dracut · isoleret kildekorrektion · 8. november 2026

## Dokumenteret hændelse (Viborg2, ClientFlow 1.3.42/1243)

- Kanonisk `update_os` blev autoriseret og hentet af System-agenten 18:36:22 CET.
- Privilegeret System-broker udførte APT. `dracut` trigger forsøgte at læse
  `/usr/lib/modules/7.0.0-43-generic` og fejlede med `Cannot find module directory`.
- Uden for systemd-sandbox eksisterede `/usr/lib/modules/7.0.0-43-generic` og
  tilhørende kernel/headers/initrd. `dpkg --verify linux-modules-7.0.0-43-generic`
  rapporterede ingen afvigelser.
- `systemctl show clientflow-system-broker.service` bekræftede `ProtectKernelModules=yes`.
- Efterfølgende `sudo dpkg --configure dracut` uden for sandbox lykkedes; `dpkg --audit`
  var tom, og `/boot/initrd.img-7.0.0-43-generic` blev regenereret.
- Kommandens `system_command_in_doubt` er korrekt fail-closed og må ikke fjernes
  eller genafspilles automatisk. Ingen automatisk retry/recovery på fysisk klient.

## Rettelsens præcise scope

De **to** root-owned, fixed-function services, som kører APT/dpkg, har nu
`ProtectKernelModules=no` fordi systemd ellers maskerer `/usr/lib/modules`.
Til gengæld afvises *eksplicit kernelmodul-indlæsning* fortsat med både
`CapabilityBoundingSet=~CAP_SYS_MODULE` og `SystemCallFilter=~@module`.

Alle andre tjenester beholder eksisterende isolation, herunder den
uprivilegerede `clientflow-system-agent.service` (`ProtectKernelModules=yes`).
Ingen ekstra mulighed for almindelige brugere, ny public API, scripts til
udenomgåelse af backend eller ændring af den durable kommandojournal tilføjes.

Frontend lader terminal kanonisk System-command-fejl erstatte gammel lokal
"afventer System-agent"-tekst, med en sikker, handlingsegnet in-doubt-besked.

## Gates inden fysisk test / release

1. Kør hele CI (Python/JS lint/tests + Ubuntu 26.04 host gates) uden at svække tests.
2. Host gate starter isoleret systemd runtime-probe med **de faktisk definerede**
   sandbox-properties for begge package-services. Den skal kunne læse den
   faktiske `/usr/lib/modules` og bevise fravær af CAP_SYS_MODULE i bounding set.
3. Godkendte 1.3.42/1243 bytes og katalog-/default/installationspolicy ændres ikke.
   Ændringen kræver **et nyt release-ID/sekvens og en ny reproducérbar build/approval**.
4. På separat, fysisk Ubuntu 26.04 testinstallation: bekræft faktisk APT/dpkg
   inklusive `dracut` trigger, sund `dpkg --audit`, boot/initrd og OS-opdateringsstatus
   før/efter kontrolleret reboot. Test også no-retry/in-doubt fejlscenariet.
5. Ingen aktiv flag-ændring, reinstall, reboot, publish, oprydning eller
   manuelle ændringer af Viborg2/Heidi1 i denne kodefase.

Dette er en kilde- og testleverance – **ikke** dokumentation for bestået
fysisk Ubuntu-opdatering eller installeret ny release.
