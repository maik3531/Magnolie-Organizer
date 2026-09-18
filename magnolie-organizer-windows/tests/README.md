# Testabdeckung

Die portablen CoreTests verwenden einen kleinen eigenen Gruppen-Runner ohne zusätzliches Testframework. Er prüft AtomicStore einschließlich Abbruch/Recovery, Verschlüsselungs-Goldens und Manipulation, Gesamtarchive, ICS/VCF/LDIF/Claws/Lotus einschließlich Thunderbird-Fixtures, ODS, Windows Contacts, Graph/OAuth/Token, Reminder einschließlich Neustart/Kennwort/DST, Tray und Magnolienbaum einschließlich echtem Loopback-Netzwerk.

## Normal

```powershell
dotnet restore --locked-mode
dotnet run --project tests/CoreTests.csproj -c Release --no-restore
bun install --frozen-lockfile
bun run test
dotnet build MagnolieOrganizer.Windows.csproj -c Release --no-restore
```

`tests/run.js` liest die kanonische Version einmal aus `Directory.Build.props`
und übergibt Version und daraus gebildeten Installernamen an Handbuch- und
Release-Audit. Der Audit führt mit PowerShell echte Abbruch-, Rollback- und
XML-Duplikatprüfungen aus; ohne PowerShell prüft er dieselben Invarianten statisch.

## Release-Audit: Funktion und Integration

Die 37 funktionalen CoreTests-Gruppen sind von bereits veröffentlichten Dateien
unabhängig. Die Gruppe `Release-Audit` prüft denselben strikten Validator mit
temporären synthetischen Installerdaten, Manifest, Buildrecord und beiden
Prüfsummenlisten. Positive und gezielt beschädigte Fixtures prüfen Versionen,
URLs, Hashes, Byteanzahl, Pflichtfelder, Duplikate und fehlende Dateien/Einträge.
Die Variablen `MAGNOLIE_SOURCE_ARCHIVE_TEST` und `MAGNOLIE_RELEASE_BUILD_TEST`
überspringen diese Gruppe nicht.

Die Prüfung der tatsächlichen Veröffentlichungswurzel bleibt ein separater,
verpflichtender Release-Integration-Gate, nicht Teil des Vorab-Unit-Gates:

```powershell
dotnet run --project tests/CoreTests.csproj -c Release --no-restore -- --published-release-audit
dotnet run --project tests/CoreTests.csproj -c Release --no-restore -- --published-release-audit "C:\release-candidate"
```

Ohne Pfad wird die Wurzel mit `update.xml` über `MAGNOLIE_TEST_SOURCE_ROOT`,
sonst CWD und Build-Ausgabepfad gefunden. Ein expliziter Pfad bezeichnet exakt
die zu prüfende Wurzel. Erfolg liefert Exitcode 0, jeder Auditfehler Exitcode 1,
ungültige CLI-Argumentanzahl Exitcode 2. Der Audit liest nur, führt keinen
Installer aus und verändert keine Manifeste, Prüfsummen oder Artefakte.

Dieser Integrationscheck ist zusätzlich zum bestehenden Produktionsprozess
`release_gate` mit Hashbindung und Benutzerfreigabe auszuführen, sobald eine
konsistente Kandidatenwurzel vorliegt, und an der veröffentlichten Wurzel zu
wiederholen. Ein grüner funktionaler Lauf ersetzt weder diesen Audit noch die
Benutzerfreigabe oder einen echten Windows-Lauf. Produktions-Releaseskripte
werden durch diese Testtrennung nicht geändert.

Bekannter historischer Integrationsblocker: Die veröffentlichte Fassung 2.0.17
nennt in `update.xml` den Windows-SHA `5f28cdfdd557ba5071a9b76c0cf53958dcc2b14779d79e5e19642aa5d67700d5`,
während Root-Installer, Buildrecord und Windows-Prüfsummenliste
`ffd4a770a78b403edeb16c89674079e27d5ba155b4a4f716062e439293a35640` bestätigen.
Der explizite Audit muss dies weiterhin ablehnen. Alte Benutzerartefakte und
`update.xml` bleiben unverändert; eine neue Fassung benötigt Benutzerfreigabe.

## Windows UI

Der UI-Test benötigt Windows, eine interaktive Desktop-Sitzung und WebView2. Auf Linux wird das Windows-Ziel nur gebaut; ausgeführt wird der Test dort nicht. `vm/StartTest.ps1` schreibt zusätzlich `ReminderTestCodes`, `RecoveryTestCodes` und die zugehörigen Bestanden-Felder in `vm-result.json`.

```powershell
dotnet run --project MagnolieOrganizer.Windows.csproj -c Release --no-restore -- --ui-self-test
```

`build/Build.ps1` führt nach dem Publish sowohl `--self-test` als auch `--ui-self-test` aus. Der UI-Test verwendet ein temporäres `%LOCALAPPDATA%`, startet im Tray verborgen, hält das MainForm-HWND über wiederholtes Hide/Restore stabil, rauchtestet DWM und bereitet eine native NotifyIcon-Benachrichtigung ohne eigene Popup-Form vor. Nur der explizite Linux-Modus `-CrossCompile` überspringt die Ausführung dieser Windows-EXE und des offiziellen `--packaging-self-test`; seine ZIP- und Installer-Inhalte tragen dafür zwingend `WINDOWS-RUNTIME-UNVERIFIED.txt` mit `artifactTrust=UNSIGNED` und benötigen anschließend eine Windows-VM-Prüfung. Der Installer heißt in offiziellem und Cross-Modus stets `Magnolie-Organizer-Windows-<version>-Setup-x64.exe`; der Audit schließt einen `-UNSIGNED`-Ausgabenamen aus, ohne die Authenticode- und Zeitstempelpflicht offizieller Builds zu lockern.

## Last

Ohne Variable läuft eine kleine CI-Menge von 500 Datensätzen. Die vollständige Freigabeprüfung verwendet 30.000 Datensätze und harte Laufzeitgrenzen für Lotus-Import sowie Gesamtarchiv-Erzeugen/-Lesen.

```powershell
$env:MAGNOLIE_STRESS_COUNT=30000
dotnet run --project tests/CoreTests.csproj -c Release --no-restore
```
