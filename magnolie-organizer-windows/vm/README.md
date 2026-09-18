# Windows-11-VM-Test

Die Testumgebung installiert Windows 11 Pro (Index 5) unbeaufsichtigt in eine
lokale KVM. Das Microsoft-ISO wird nicht verändert. Eine zweite ISO enthält
die Antwortdatei und die selbstenthaltende Windows-Ausgabe des Organizers.

```bash
MAGNOLIE_VM_BRANDING=unbranded bash ./vm/Create-TestMedia.sh
bash ./vm/Create-VM.sh /pfad/zu/Windows-11.iso
```

Die VM heißt `magnolie-win11-test` und verwendet UEFI, TPM 2.0,
8 GiB Arbeitsspeicher, vier virtuelle CPUs, einen 80-GiB-Sparse-Datenträger
und einen 64-MiB-FAT-Datenträger für hostseitig lesbare Testergebnisse.
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
bash ./vm/Create-Installer-TestMedia.sh
bash ./vm/Create-VM.sh /pfad/zu/Windows-11.iso ./vm/Magnolie-Installer-Test.iso
```

Der Installer-Test schreibt `RESULT.txt` und `windows-vm-test.log` auf
`vm/Magnolie-Windows-Results.img`, synchronisiert die Dateien, hängt den
Ergebnisdatenträger aus und fährt die VM anschließend selbst herunter. Der Host
darf das FAT-Abbild erst lesen, nachdem die VM beendet wurde.

Das Ergebnisabbild enthält eine MBR-partitionierte FAT32-Partition ab 1 MiB.
Die unbeaufsichtigte Installation verhindert Windows-Geräteverschlüsselung,
damit der Host den Ergebniskanal lesen kann. Nach dem Herunterfahren lassen sich
die Dateien ohne Einhängen auslesen:

```bash
mcopy -i vm/Magnolie-Windows-Results.img@@1048576 ::RESULT.txt ::windows-vm-test.log .
```

Bestehende Test-VMs bleiben mit einem getrennten Lauf unangetastet, wenn
`MAGNOLIE_VM_NAME`, `MAGNOLIE_VM_DISK` und `MAGNOLIE_VM_RESULTS_IMAGE` auf einen
neuen Namen und neue Datenträgerpfade gesetzt werden. Ohne diese Variablen
bleiben die oben genannten Standardnamen unverändert.

## Runbook und bekannte Fehlerbilder

Der Test wurde mit einem deutschen Windows-11-25H2-ISO unter libvirt/KVM
erprobt. Folgende Punkte sind bei späteren Läufen wichtig:

1. Beim ersten Start kann die Aufforderung zum Starten von DVD nur wenige
   Sekunden sichtbar sein. Wenn stattdessen eine UEFI-Shell oder ein leeres
   System erscheint, die neue Wegwerf-VM einmal zurücksetzen und das
   DVD-Startfenster beobachten. Dabei eine druckbare Taste wie die Leertaste
   verwenden; eine allein gesendete Umschalttaste bestätigt diesen Prompt
   nicht. Nicht den Datenträger einer bestehenden VM wiederverwenden.
2. Während und nach der Installation kann die VNC-Anzeige vollständig schwarz
   werden, obwohl Windows weiterarbeitet. Zuerst die Anzeige mit einer
   Umschalttaste wecken und Datenträgeraktivität beziehungsweise DHCP-Lease
   prüfen. Eine schwarze Anzeige allein ist kein Grund für einen Reset.
3. Ein direkt mit FAT formatiertes Rohabbild ohne Partitionstabelle wird als
   fester SATA-Datenträger von Windows 11 nicht eingebunden. Das Erzeugungsskript
   verwendet deshalb zwingend MBR, eine Partition ab Sektor 2048, FAT32 und
   denselben Wert im BPB-Feld für versteckte Sektoren.
4. Windows-Geräteverschlüsselung kann einen eingebundenen festen
   Ergebnisdatenträger automatisch in ein FVE-Volume umwandeln. Ein solches
   Abbild beginnt in der Partition mit der OEM-Kennung `-FVE-FS-` und ist mit
   Mtools nicht lesbar. `Autounattend.xml` setzt deshalb
   `PreventDeviceEncryption`. Diese Einstellung wirkt nur während einer neuen
   Windows-Installation; das nachträgliche Ersetzen des Ergebnisabbilds in einer
   bereits installierten VM genügt nicht.
5. Fehlt der Datenträger `MAGNOLIE_RESULTS`, kann das Protokoll nicht dauerhaft
   geschrieben oder der Datenträger nicht ausgehängt werden, bleibt die VM
   absichtlich aktiv. In diesem Zustand unter `Dieser PC` prüfen, ob neben den
   beiden ISO-Laufwerken ein Volume `MAGNOLIE` vorhanden ist. Erst den
   Ergebniskanal korrigieren, dann den Test erneut starten.
6. `Invoke-WebRequest` an `192.168.122.1:18080` ist nur ein zusätzlicher
   Diagnosekanal. Er ersetzt nie `RESULT.txt` und `windows-vm-test.log`, weil
   Host-Firewall oder libvirt-Netzfilter den Rückkanal blockieren können.
7. Das Ergebnisabbild niemals bei laufender VM hostseitig öffnen. Nach dem
   Lifecycle-Ereignis `Shutdown Finished after guest request` zuerst die
   Partition prüfen und dann Mtools mit dem Offset `@@1048576` verwenden.

Nützliche Hostdiagnose, wobei die Namen bei getrennten Läufen entsprechend den
Umgebungsvariablen anzupassen sind:

```bash
virsh --connect qemu:///system domstate magnolie-win11-test
virsh --connect qemu:///system domifaddr magnolie-win11-test --source lease
virsh --connect qemu:///system domstats magnolie-win11-test --block --state
sfdisk -d vm/Magnolie-Windows-Results.img
dd if=vm/Magnolie-Windows-Results.img bs=512 skip=2048 count=1 status=none | file -
mdir -i vm/Magnolie-Windows-Results.img@@1048576 ::
```
