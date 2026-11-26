# Mac #771: vollständiger Geltungsbereich einzelner EventKit-Abfragen

Stand: 26. November 2026. Ausgangscommit:
`616069f15fed21d8d8d05c8ef795f4ed21bd059c`.
Quellpatch zur späteren Codex-Prüfung und Übernahme, keine Paketfreigabe.

## Ursache und Entscheidung

Apples Dokumentation zu
[`predicateForEvents(withStart:end:calendars:)`](https://developer.apple.com/documentation/eventkit/ekeventstore/predicateforevents%28withstart%3Aend%3Acalendars%3A%29)
wurde am 26. November 2026 einschließlich der angebotenen Markdown-Fassung
gelesen. Zeitfenster über vier Jahre werden auf den Anfang dieses Bereichs
verkürzt. Die API arbeitet dabei mit der Standardzeitzone.

Der bisherige Guard in `SystemSourcePolicy.requireWindow` ließ bis zu
`4 * 366 * 86400` Sekunden zu. Beispielsweise passieren 1. Januar 2026 bis
4. Januar 2030 diesen Guard, obwohl sie über vier Kalenderjahre hinausreichen.
Sowohl `SystemAccountStore.readEvents` als auch `snapshotEvents` verwenden
einen einzelnen EventKit-Predicate. Der typisierte Snapshot übernahm trotzdem
den gesamten angeforderten Bereich als Scope. Dies ist ein bestätigter
Quellenbefund, kein hier ausgeführter EventKit-Verlustnachweis.

**Neuer Vertrag:** Ein allgemeiner nativer Kalenderabruf akzeptiert höchstens
366 Tage als verstrichene Sekunden (`31_622_400`), entsprechend der schon
vorhandenen Kalenderkopie. Größere, leere, umgekehrte oder nicht endliche
Fenster scheitern ausdrücklich; es wird weder abgeschnitten noch ein
Teilresultat als vollständig bezeichnet. Die Meldung verwendet die bereits
vorhandene deutsche Übersetzung „Wählen Sie einen Zeitraum mit höchstens
366 Tagen.“

Das ist eine bewusste Einschränkung des früheren allgemeinen Vierjahresvertrags.
Es gibt keine neue Segmentierung und keine neue Deduplikation von Serien.
366 lokale Kalendertage mit einer zusätzlichen Herbstumstellungsstunde
überschreiten die Sekundengrenze ebenfalls; das kleinere Fenster muss bewusst
gewählt werden. Der Guard hängt weder von einem Kalenderjahr-Modell noch von
der Systemzeitzone ab.

## Konkrete Einbindung

- Beide allgemeinen Reader prüfen denselben Guard bereits **vor** Erzeugung
  des EventKit-Predicates; beide werden durch die gemeinsame Korrektur erfasst.
- `SystemSourceSnapshot.init` verwendet ihn ebenfalls. Ein künstlich breiterer
  Scope kann damit auch nachgelagert nicht als gültiger Snapshot entstehen.
- Der einzige externe Swift-Aufrufer von `snapshotEvents` ist der vorhandene
  `SystemCalendarImportHost`. Seine normale Auswahl bleibt von 30 Tagen vor
  heute bis einschließlich 90 Tage danach; die eigene 366-Tage-Prüfung bleibt.
  Für `readEvents` wurde außerhalb der Fassade kein aktueller Aufrufer gefunden.
- `SystemCalendarImport` behält seinen eigenen 366-Tage-Guard. Die bisherige
  Testvorbereitung eines 367-Tage-Snapshots wurde auf den jetzt früheren
  Ablehnungspunkt umgestellt, ohne den Negativfall zu entfernen.
- `authorizesAbsenceDeletion` bleibt `false`; keine Synchronisation,
  Löschfreigabe oder Veränderung der Apple-Quelle wird daraus abgeleitet.

## Prüfung und genaue Beweisgrenze

Tatsächlich unter Linux mit Python und Node 24.22.3 / JSDOM 26.1.0 geprüft:

1. Quellenpfad: Guard vor Predicate in beiden Readern, Aufrufer und unveränderte
   Standardauswahl, vorhandene deutsche Übersetzung.
2. Sieben unabhängige Datumsrechnungen mit Pythons `datetime`: 1464-Tage-Befund,
   normale und Schaltjahre, 23-/25-Stunden-Tage und 366 Tage plus eine Stunde.
   Dies prüft die erwarteten Fixture-Werte, **führt Swift nicht aus**.
3. `python3 tools/check_system_calendar_import.py --js-runtime /path/to/node`
   mit `MACOS_BETA_JSDOM=/path/to/jsdom/lib/api.js`: **307 Prüfungen bestanden**.
   Echte erzeugte Oberfläche, synthetische EventKit-Nutzlasten und Transport;
   kein nativer EventKit-/macOS-Nachweis.
4. `git diff --check`: bestanden.

Vier neue Swift-Testmethoden sowie zwei gezielte Anpassungen vorhandener Tests
sind vorbereitet. Sie behandeln das konkrete 1464-Tage-Fenster, normale und
Schaltjahre, exakt 366 Tage, eine Sekunde darüber, Zeitzonen-Offsetwechsel,
NaN/Unendlich sowie einen Datensatz in der letzten Minute des erlaubten
Fensters samt exaktem Snapshot-Scope und fehlender Löschautorität.

**Swift ist in der Arbeitsumgebung nicht vorhanden. Diese Swift-Tests wurden
weder kompiliert noch ausgeführt.** Der synthetische letzte Datensatz beweist
keinen tatsächlichen EventKit-Abruf am Fensterende. Native Prüfung auf Intel
und Apple Silicon bleibt erforderlich, insbesondere mit einem expliziten
Testkalender und Termin am Ende eines zulässigen Fensters; in beiden Readern
außerdem eine übergroße Anfrage vor dem Predicate ablehnen lassen.

Für die gezielte Codex-Prüfung auf macOS im bestehenden Quell- und Werkzeugstand:

```sh
cd Magnolie-Organizer-macOS-Beta
swift test --jobs 2 --filter 'SystemSourcePolicyTests|SystemSourceSnapshotTests|SystemCalendarImportTests'
```

Linux/Windows verwenden andere Kalenderadapter; dieser Patch behauptet dort
weder einen entsprechenden Fehler noch eine native Korrektur.
