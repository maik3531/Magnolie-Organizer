# Magnolie Organizer für Windows

Dieser Ordner ist ein eigenständiger Windows-Port. Er verändert oder benötigt
keine Datei des Linux-Pakets. Die sichtbare Oberfläche unter `app/web/` ist
aus Magnolie Organizer 2.0.0 übernommen. Ringbuch, Papier, Register, Abstände
und alle zwanzig Sprachen bleiben erhalten; nur Contributor-Freischaltung und
Branding sind Windows-spezifisch.

## Windows-Technik

- C# und WinForms aus .NET 8
- Microsoft WebView2 aus der auf Windows 10/11 vorhandenen Edge-Laufzeit
- Windows-Datei- und Ordnerdialoge
- Windows-Zwischenablage und Shell-Aufrufe
- `NotifyIcon` für Tray und Benachrichtigungen
- benannter Windows-Mutex für genau eine laufende Instanz
- `%LOCALAPPDATA%\Magnolie Organizer` für Daten und Einstellungen
- atomarer Dateiersatz mit schreibendem Flush
- AES-256-GCM und PBKDF2-SHA256 aus `System.Security.Cryptography`
- X25519 aus `BouncyCastle.Cryptography` für den Linux-kompatiblen Magnolienbaum

GTK, WebKitGTK, systemd, UFW, BlueZ und Linux-XDG-Bibliotheken werden nicht
verwendet.

## Bauen

Auf Windows 10 oder 11 x64 mit .NET-8-SDK, Bun 1.2.20, Python 3 und GNU
gettext (`msgfmt` und `xgettext` im `PATH`):

```powershell
.\build\Build.ps1
```

Dies ist ausdrücklich ein **unsignierter lokaler Build**. Das Skript prüft den portablen Kern und die Oberfläche, erzeugt
eine selbstenthaltende x64-Anwendung und packt
`Magnolie-Organizer-Windows-2.0.13-x64.zip`.
`Build.ps1` wählt `python3` beziehungsweise `python` einmal aus und reicht exakt
diesen Interpreter über `MAGNOLIE_PYTHON` an Tests und Kataloggeneratoren weiter.
Fehlt `msgfmt`, bricht der Bau vor Tests und Generierung ab.

Normale Eigenbauten enthalten kein Contributor-Branding. Für einen offiziellen
Binärbau kann `MAGNOLIE_CONTRIBUTOR_HASH` auf eine 64-stellige SHA-256-Hexfolge
gesetzt werden. Das Skript schreibt daraus ausschließlich in die Ausgabe eine
`build-config.json`; Klartextschlüssel und Konfigurationsdatei gehören nicht zum
Quellpaket.

Optional kann `MAGNOLIE_GRAPH_CLIENT_ID` beim Bau auf die GUID einer eigenen
Microsoft-Entra-App gesetzt werden. Ohne diese Variable bleibt der lokale
Windows-Kontakteabgleich vollständig nutzbar; die Windows-Oberfläche bietet
keine nachträgliche Client-ID-Konfiguration an. Die Appregistrierung muss öffentliche
Clientflows (Gerätecode) und die delegierte Berechtigung `Contacts.ReadWrite`
erlauben. Ein Client Secret wird weder benötigt noch unterstützt.

Nach dem Entpacken startet `Magnolie Organizer.exe` die Anwendung. Eine
Installation von Python, GTK oder Node.js ist für das fertige Programm nicht
nötig. WebView2 gehört zu aktuellen Windows-10-/11-Installationen; fehlt die
Laufzeit, nennt das Programm dies ausdrücklich.

Alternativ installiert `Magnolie-Organizer-Windows-2.0.13-Setup-x64.exe` die
Anwendung für das aktuelle Benutzerkonto. Der Installer legt den Programmeintrag
im Startmenü und den Deinstallationseintrag unter Apps an, aber keinen
Deinstallieren-Link im Startmenü. Das Windows-Benutzerhandbuch ist eine optionale,
standardmäßig ausgewählte Installer-Komponente und erhält einen eigenen Eintrag
im selben Startmenüordner. Es verwendet keinen eigenen Uninstaller, sondern wird
zusammen mit den Programmdateien entfernt. Persönliche Daten bleiben bei der
Deinstallation standardmäßig erhalten und können auf ausdrücklichen Wunsch mit
entfernt werden.

Das reproduzierbar bereinigte Windows-Quellarchiv entsteht mit
`build\BuildSource.ps1` als `Magnolie-Organizer-Windows-2.0.13-Source.zip`.
`Build.ps1` prüft Hauptordner, kanonische Version, Pflichtdateien und deren
SHA-256-Inhalte. Fehlt ein aktuelles Quellarchiv, baut und prüft es das Archiv
innerhalb derselben gesperrten Staging-Transaktion. Lokale Ausgaben,
Abhängigkeiten, Zwischenstände und interne Arbeitsnotizen sind ausgeschlossen.

Exakte Befehle für eine vollständige lokale Prüfung:

```powershell
.\build\BuildSource.ps1
.\build\Build.ps1
.\build\Build.ps1 -BuildInstaller
```

Der dritte Befehl benötigt `makensis.exe` und erzeugt
`Magnolie-Organizer-Windows-2.0.13-Setup-x64.exe` samt entsprechendem
Prüfsummeneintrag. Auch der unsignierte Linux-Cross-Build und
`installer/BuildInstaller.sh` verwenden ausschließlich diesen kanonischen Namen;
`-UNSIGNED` ist nie Bestandteil eines Ausgabedateinamens. Veraltete Artefakte mit
diesem Suffix werden bei erfolgreicher Veröffentlichung entfernt. Eine offizielle Ausgabe setzt zusätzlich
`MAGNOLIE_OFFICIAL_RELEASE=1`, den exakten `MAGNOLIE_CONTRIBUTOR_HASH` sowie
`MAGNOLIE_SIGNTOOL`, `MAGNOLIE_SIGN_CERTIFICATE`, `MAGNOLIE_SIGN_PASSWORD`,
`MAGNOLIE_SIGN_PUBLISHER` und `MAGNOLIE_TIMESTAMP_URL`. Fehlt eine Voraussetzung,
bricht der Bau geschlossen ab. Anwendung und Installer werden signiert und samt
RFC3161-Zeitstempel und den exakt konfigurierten Zertifikat-Herausgeber geprüft; erst
danach erhält der Installer seinen kanonischen Namen. Die Prüfsummendatei enthält zwingend ZIP und
aktuelles Quell-ZIP sowie bei angefordertem Bau zwingend den Installer;
PDB-Dateien sind nicht im Binär-ZIP. Handbuchversion und Installername werden aus
der Version in `Directory.Build.props` an den Handbuch-Port und seine Tests
übergeben; NSIS übernimmt das Handbuch ausschließlich aus der geprüften
`Ausgabe\handbuch`-Stagingstruktur.

Ein Linux-Rechner darf ausdrücklich einen nicht freigabefähigen Windows-Bau
einschließlich selbstenthaltendem `win-x64`-Publish, deterministischem ZIP, NSIS-
Installer und Prüfsummen erzeugen. Dafür ist exakt folgende Umgebung vorgesehen:

```bash
env PATH="/tmp/opencode/nsis-root/usr/bin:$PATH" NSISDIR="/tmp/opencode/nsis-root/usr/share/nsis" /tmp/opencode/powershell-7.4.13/pwsh -NoProfile -File ./build/Build.ps1 -CrossCompile
```

`-CrossCompile` verweigert den offiziellen Betrieb und
jede konfigurierte Signierung. Der Installer und die an das Handbuch übergebenen
Metadaten tragen immer den Namen `Magnolie-Organizer-Windows-2.0.13-Setup-x64.exe`.
Der kanonische Dateiname ist kein Vertrauensnachweis: Der Cross-Build bleibt
ausdrücklich nicht offiziell und unsigniert; maßgeblich sind sein Release-Hinweis
und `artifactTrust=UNSIGNED` im eingebetteten Laufzeitmarker.
Quellarchivprüfung, gesperrte Restores, C#- und Bun-Quelltests, Publish, ZIP, NSIS,
Prüfsummen sowie transaktionales Staging/Rollback bleiben aktiv. Nur die unter
Linux unmögliche Ausführung der Windows-EXE mit `--packaging-self-test`,
`--self-test` und `--ui-self-test` entfällt. `WINDOWS-RUNTIME-UNVERIFIED.txt` liegt
deshalb in Ausgabe, ZIP und Installer und enthält maschinenlesbar Version und
SHA-256 des geprüften Quellarchivs. Vor irgendeiner Nutzung ist die Validierung in
einer Windows-VM zwingend. Offizielle Builds enthalten diesen Marker nie.

Vor dem finalen Linux-Releasebau aktualisiert folgender Windows-Befehl die Windows-
Hashes im Wurzelmanifest und im Linux-Quellmanifest. Der Helfer akzeptiert nur den
kanonisch benannten Installer mit gültiger Authenticode-Signatur, RFC3161-Zeitstempel
und exakt passendem `-ExpectedPublisher` beziehungsweise `MAGNOLIE_SIGN_PUBLISHER`.
Ein vorhandenes `signtool` wird zusätzlich mit `verify /pa /all /tw` geprüft. Ohne
diese Signatur-Policy sowie bei fehlender Signatur bricht er geschlossen ab. Signierte Manifeste werden
verweigert. `-UpdateManualWindows` ist nur erlaubt, wenn der Handbuchverweis exakt
denselben Installer bezeichnet:

```powershell
    .\build\UpdateManifest.ps1 -Installer .\Magnolie-Organizer-Windows-2.0.13-Setup-x64.exe -ExpectedPublisher 'CN=Exakter Zertifikatinhaber' -UpdateManualWindows
```

## Daten

Der Windows-Port speichert unter:

```text
%LOCALAPPDATA%\Magnolie Organizer\daten.json
```

Die Kennworthülle ist mit der Linux-Fassung kompatibel. Ein Datenbestand kann
daher zwischen beiden Systemen übertragen werden.

Der Magnolienbaum speichert seine dauerhafte Identität, Partner, Inbox und
Outbox zusätzlich in `baum.json`, `baum-eingang.json` und `baum-post.json`.
Diese drei Dateien sind in Version 2.0.0 noch nicht in die journalisierte
Kennworttransaktion des Hauptdatenbestands eingebunden und liegen daher lokal
unabhängig und unverschlüsselt. Der Port stellt dafür ausdrücklich keinen
Kennwortschutz in Aussicht.

Codepaarung, Paarungsdatei Fassung 2, UDP-Suche, HTTP sowie die verschlüsselten
Transporte `baum-1` und `baum-fs1` sind mit Linux kompatibel. Partner aus einer
v2-Datei verwenden Forward-Secrecy-Sitzungen mit kryptografisch gebundener
Empfangsquittung.

mDNS meldet den Dienst `_magnolie-phone._tcp` je betriebsbereiter Schnittstelle
und legt den A-Satz der jeweiligen Adresse bei; Windows beantwortet keine
Abfrage nach dem eigenen `.local`-Namen, ohne diesen Satz bliebe der SRV-Verweis
unauflösbar. Die KDE-Connect- und Magnolienbaumsuche senden zusätzlich an die
gerichtete Rundsendeadresse jedes IPv4-Netzes, weil Windows `255.255.255.255`
nur über die Schnittstelle der Standardroute leitet.

Bluetooth veröffentlicht dieselben verschlüsselten Telefonrahmen als
RFCOMM-Dienst über WinRT. Voraussetzung sind ein eingeschaltetes Funkgerät, der
von Windows erteilte Gerätezugriff und eine bestehende Windows-Kopplung mit dem
Telefon; fehlt eine davon, nennt der Port den Grund (`no_hardware`, `disabled`,
`permission_missing`, `os_restricted`) statt stillschweigend nicht zu verbinden.

Eingehende Verbindungen benötigen unter Windows eine Firewallfreigabe. Der
Installer läuft bewusst ohne Administratorrechte und kann sie nicht anlegen;
die Anwendung richtet sie deshalb beim Einschalten der Telefonverbindung oder
des Magnolienbaums sowie beim Start einer Telefon- oder KDE-Connect-Paarung mit
genau einer UAC-Abfrage ein. Die Magnolienbaumsuche selbst benötigt keine
Rechteerhöhung. Die Regeln gelten ausschließlich für diese Programmdatei und
für die Ports 8741/TCP, 8737/TCP, 1716-1764/TCP sowie 8737/UDP, 1716/UDP und
5353/UDP.
