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
