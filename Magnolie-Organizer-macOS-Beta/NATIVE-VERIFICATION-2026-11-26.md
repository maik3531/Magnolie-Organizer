# Fortsetzung der nativen Mac-Verifikation

Stand: 26. November 2026. Zugeordnet zu #121, #783, #785, #786 und dem
konkreten nativen Compilerbefund #788. Der plattformübergreifende
Quellarchivbefund #787 wird separat korrigiert.

## Übernommener und erneut bestätigter Stand

Arbeitszweig: `work/macos-issue-fixes-20261126`. Der bei Übernahme tatsächlich
abgefragte Remote-Head war `97baf780fa3474eba54d03e41d0258c97ae8b1ca`, die
entfernte Standardbasis `d4da48a5eadd0bda22422b924bef4ee3b4324040`.

Die vorhandene Übergabe wurde gezielt geprüft: 29/29 SHA256SUMS-Einträge,
30/30 publizierte Manifestdateien sowie 24/24 Patchdateien einschließlich
Dekompression, Originalbytezahl, Hash und From-Commit stimmen. Das Bundle
hat 1.219.360 Bytes und SHA-256
`a775686b950ffd30a6fcbd0c20b063efc777ffc1953980b5f6eae81dc24e7224`;
`git bundle verify` bestand. Alle 31 vorhandenen Issue-Kommentare wurden
über ihre gespeicherten IDs vollständig zurückgelesen. Issue-/Kommentar-URL,
Marker, UTF-8-Bytezahl und Text-SHA-256 stimmen jeweils. Es wurde kein
Übergabekommentar erneut veröffentlicht. Die historische Wiederherstellung
mit `fsck` wurde nicht erneut ausgeführt und bleibt ein historischer Beleg.

## Neuer tatsächlicher nativer Lauf

Die GitHub-CLI besitzt hier weiterhin keine Anmeldung; die vorhandene
Websitzung war bereits als Repositoryinhaber angemeldet. Deshalb konnte der
bereits definierte Workflow ohne neue Kontoverknüpfung gestartet werden.

| Eigenschaft | Tatsächlicher Wert |
| --- | --- |
| Run | [45786948279 / #91](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45786948279) |
| Quellcommit | `97baf780fa3474eba54d03e41d0258c97ae8b1ca` |
| Auslösung | `workflow_dispatch`, `target=macos` |
| Matrix | `macos-15` / ARM64 und `macos-15-intel` / x86_64 |
| Tablet | Nicht ausgewählt; Job übersprungen |
| ARM64-Job | `139796016432` |
| Intel-Job | `139796016051` |

Der ARM64-Job hat die Bindung an die aktuelle Quelle bestanden. Im Schritt
zum unabhängigen Zeitzonenvergleich wurde tatsächlich Swift gestartet.
Bereits der Bau des dafür benötigten Moduls `BetaCore` scheiterte an zwei
Compilerfehlern; der Vergleich wurde deshalb noch nicht ausgeführt.
Der inzwischen abgeschlossene Intel-Job bestätigt dieselben zwei Ursachen
und keine zusätzlichen Compilerfehler. Beide Mac-Jobs endeten mit `failure`;
Quellbindung und Abhängigkeiten/Kataloge waren jeweils erfolgreich. Import-
runtime, Host-/Swift-Tests, Bundlebau und App-Start wurden nicht erreicht.
Beobachtete Umgebungen: ARM64 macOS 15.8.2, Build 24H232; Intel macOS 15.7.9,
Build 24G830.

### #788: konkrete Compilerfehler und enger Fix

1. `Sources/BetaCore/Contract.swift`: Der Initialisiererparameter
   `text: String` verdeckte die gleichnamige Instanzmethode bei der neuen
   Importformat-/Mülltokenprüfung. `self.text(...)` bezeichnet die vorhandene
   Methode eindeutig; erlaubte Formate und Tokenbedingungen bleiben gleich.
2. `Sources/BetaCore/SystemAccountSync.swift`: Der throwing Gleichheitsvergleich
   stand im rechten Autoclosure eines `&&`-Operators ohne Fehlerweitergabe für
   diesen äußeren Operator. Die Gleichheitsprüfung liegt nun in einem eigenen
   `if try` innerhalb der unveränderten Bedingung
   `localChanged && remoteChanged`. Sie wird weiterhin nur bei beidseitiger
   Änderung ausgeführt; Konflikt und Fehler werden weiterhin weitergegeben.

Bestehende native Tests decken die fachliche Bedeutung ab:

- `FileImportProtocolTests.testNativeCommandAdmitsFormatsWithoutWebSelectedPaths`
- `SystemAccountSyncTests.testDisjointChangesMergeButSameFieldConflictLeavesBothAndBaselineUntouched`
- `SystemAccountSyncTests.testEqualChangesConvergeWithoutWriting`

Die lokale Diffprüfung bestand. In diesem Linux-Arbeitsplatz ist kein Swift
vorhanden; eine lokale Swift-Ausführung wird nicht behauptet. Die tatsächliche
native Wiederholung des korrigierten Quellstands ist der nächste Schritt.

## Unveränderte Abnahmegrenzen

Ein Compilerfehler ist kein Nachweis einer falschen Zeitzonenreferenz. Ein
erfolgreicher Bau allein ist kein bestandener Test der privaten Importlaufzeit,
der Apple-Provider, des App-Bundles oder eines iCloud-/iPhone-Rundlaufs. Jeder
spätere Lauf wird mit seiner tatsächlichen SHA und erreichten Phase ergänzt.

Die vorbereiteten übrigen Grenzen und Testfälle gelten weiter:
[CLOUD-MAC-TESTING.md](CLOUD-MAC-TESTING.md), [IMPORT-RUNTIME.md](IMPORT-RUNTIME.md)
und die vorhandenen #785-/#786-Verträge. Mac-12.7-Abnahme, TCC-Dialoge,
ausdrücklich eingerichtete Apple-Testquellen, Gerätegegenstellen und die
dokumentierten Implementierungsreste sind weiterhin offen. Die Fortsetzung
ist keine Freigabe für Main-Merge, Issue-Schließung oder Releasepublikation.
