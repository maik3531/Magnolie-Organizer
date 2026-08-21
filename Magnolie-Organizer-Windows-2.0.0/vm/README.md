# Windows-11-VM-Test

Die Testumgebung installiert Windows 11 Pro (Index 5) unbeaufsichtigt in eine
lokale KVM. Das Microsoft-ISO wird nicht verändert. Eine zweite ISO enthält
die Antwortdatei und die selbstenthaltende Windows-Ausgabe des Organizers.

```bash
MAGNOLIE_VM_BRANDING=unbranded ./vm/Create-TestMedia.sh
./vm/Create-VM.sh /pfad/zu/Windows-11.iso
```

Die VM heißt `magnolie-win11-test` und verwendet UEFI Secure Boot, TPM 2.0,
8 GiB Arbeitsspeicher, vier virtuelle CPUs und einen 80-GiB-Sparse-Datenträger.
Die VNC-Anzeige ist ausschließlich an `127.0.0.1` gebunden.

Ein offizieller VM-Datenträger muss seine Branding-Erwartung explizit angeben:
`MAGNOLIE_VM_BRANDING=official MAGNOLIE_CONTRIBUTOR_HASH=<64-hex> ./vm/Create-TestMedia.sh`.
Hash und `Ausgabe/build-config.json` werden vor dem ISO-Bau exakt verglichen.

Das lokale Einmalkonto `MagnolieTest` und sein in `Autounattend.xml` sichtbares
Kennwort sind nur für diese wegwerfbare Test-VM bestimmt. `StartTest.ps1`
kopiert das Programm nach `C:\Magnolie-Test`, führt `--self-test` aus, startet
die Oberfläche und schreibt `vm-result.json` sowie die Testprotokolle dorthin.

Für einen realen Installer-Test erzeugt `Create-Installer-TestMedia.sh` eine
eigene ISO. Der unbeaufsichtigte Test installiert den Organizer, installiert
dieselbe Version als Update darüber, deinstalliert ihn bei vorhandener
unbekannter Datei und installiert anschließend ohne manuelles Löschen des
Restordners neu. Danach prüft `--ui-self-test` in WebView2 die eingebettete
DejaVu-Sans-Schrift und die normale Fenstergröße.

```bash
./vm/Create-Installer-TestMedia.sh
```
