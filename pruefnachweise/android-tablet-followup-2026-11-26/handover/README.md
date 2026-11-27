# Android-Tablet: Übergabe und spätere Übernahme

Stand: 26. November 2026. Refs #121, #113 und Draft-PR #795.
Diese Übergabe ergänzt den bisherigen Stand als **Folgepatch 13** ausschließlich
um Dokumentation und Nachweise. Sie verändert keine ausführbaren Quellen und
erteilt keine Paket- oder Produktionsfreigabe.

## Ausgangsbasis, getesteter Stand und vollständige Patchfolge

| Bezug | Festgehaltener Stand | Bedeutung |
| --- | --- | --- |
| Gemeinsame Ausgangsbasis und zuletzt abgefragter `main` | `d4da48a5eadd0bda22422b924bef4ee3b4324040` | Basis der ersten fünf Patches; am 26.11. unverändert |
| Erste fünf Patches vollständig | `29acde7e3df2b8bcaaab0cc19b3377b8dbf4bd14` | Ausgangspunkt der nummerierten Folgepatches |
| Tatsächlich gebaut und mit Android-Providern geprüft | `7a7d90b04796cf338b98f0fdbb87e8da1c967043` | CI #101, nach Folgepatch 11 |
| Getesteter Git-Baum | `06c1a8cf6f115908dc21252682c2a358246f2cb7` | Inhalt des APK-/Provider-Prüfstands |
| Dokumentations-/Nachweisbasis dieser Übergabe | `8d5dc47fecf77b7ebc2db0e5cbb7cb4754005b29` | Erste fünf plus zwölf Folgepatches, noch vor diesem Übergabenachtrag |
| Baum dieser Dokumentationsbasis | `4f3cc2051a5b598171f690e3ff72d1c136068c9c` | Lokal identisch mit `680d348f3f9cff6ecf3adc5536a6490649d25ef6` |
| Aktueller Prüfzweig und Veröffentlichung der Nachträge | `work/android-tablet-20261126`, [Draft-PR #795](https://github.com/maik3531/Magnolie-Organizer/pull/795) | Aktuellen Head vor Übernahme erneut lesen und festhalten |

Der [vollständige Patchindex in #121](https://github.com/maik3531/Magnolie-Organizer/issues/121#issuecomment-7188858114)
enthält die vollständigen Dateien einschließlich mehrteiliger Issue-Kommentare.
[baseline-patch-series.json](baseline-patch-series.json) bindet die **ersten fünf
plus zwölf Folgepatches** mit Reihenfolge, SHA256, Größe, Commit-/Baumzuordnung
und primären Kommentaradressen. Der Index ergänzt anschließend Folgepatch 13
mit dessen eigenem Hash, Ergebnisbaum und veröffentlichtem Commit. Diese
Trennung vermeidet eine selbstreferenzielle Prüfsumme des Übergabepatches.

Für eine Wiederherstellung aus Issue-Kommentaren gilt: erste Serie 1–5 auf
`d4da48a5…`, danach Folgepatches 1–12 auf `29acde7e…`, anschließend Folgepatch 13
und gegebenenfalls ausdrücklich dokumentierte spätere Nachträge. Je Datei alle
Diff-Blöcke in Teilreihenfolge ohne Markdown-Zäune/Überschriften zusammensetzen,
Gesamtgröße und SHA256 prüfen und erst dann anwenden. Die identischen Spiegel
des ersten Patches in #682 sowie des Folgepatches 4 in #800 **nicht nochmals
anwenden**. Original-Logdateien behalten ihre Bytes einschließlich vorhandener
Leerzeichen; daraus entstandene Patchwarnungen sind keine Erlaubnis, Belege zu
bereinigen. Die älteren isolierten Vier-/Sechs-Patch-Belege bleiben historische
Teilnachweise und ersetzen das vollständige Serienmanifest nicht.

Entweder den vollständig geprüften Zweig übernehmen oder die vollständige
Patchserie rekonstruieren. Bereits enthaltene Änderungen zuerst anhand von
Ancestry und Diff prüfen; Branchübernahme und Patchserie nicht kumulativ anwenden.
Unterschiedliche lokale und veröffentlichte Commitkennungen sind im Manifest
explizit zugeordnet; maßgeblich für Inhaltsgleichheit ist der vollständige Tree.

## Was für die spätere Aktualisierung erhalten bleiben muss

Die Tabletoberfläche wird aus den **jeweils aktuellen gemeinsamen Quellen**
unter `magnolie-organizer/web`, den eingebundenen Windows-Schriftressourcen,
den gemeinsamen Verträgen und dem Tabletadapter erzeugt. Die kanonischen
Eingaben und ihre Bindung definiert die [Tablet-README](../../../Magnolie-Organizer-Android-Tablet-Beta/README.md#canonical-ownership).
Generierte Dateien unter `app/build/generated/projection` werden neu erzeugt;
sie sind kein dauerhaft separat zu pflegender UI-Zweig. Das alte Tag `v2.0.30`
bleibt ausschließlich eine unabhängige Codec-Referenz.

Für die Tabletversion bleiben direkte Android-Provider mit ausdrücklicher
Berechtigung und Quellenwahl maßgeblich. Magnolie Notes und KDE Connect sind
keine Voraussetzung. Lokale Organizer-Notizen bleiben erhalten. Kontakt- und
Terminkopien verleihen keine laufende Synchronisierung oder Provider-Schreib-
und Löschrechte. Request-/Session-/Revisionsbindung, Herkunftsschema, konservativer
Datenerhalt und Erfolg erst nach bestätigtem Speichern bleiben unverändert.

### Wenn `main` inzwischen weitergelaufen ist

1. Aktuellen `main`, den vollständigen Tablet-Prüfzweig, `AGENTS.md`,
   `ARBEITSSTAND.md` und den Patchindex neu lesen. Beide Heads, gemeinsamen
   Vorfahren und Änderungsumfang festhalten. Die hier genannten Heads sind
   historische Anker und ersetzen keine erneute Remote-Abfrage.
2. Einen getrennten Reviewzweig/Worktree auf dem dann aktuellen `main` anlegen.
   Den festgehaltenen Tablet-Head dort integrieren. Wurde die Serie bereits ganz
   oder teilweise übernommen, zuerst die tatsächliche Differenz ermitteln;
   keine vorhandenen Korrekturen durch erneutes blindes Anwenden überschreiben.
3. Konflikte in den kanonischen gemeinsamen Quellen, Verträgen oder dem
   Tabletadapter lösen. Sowohl spätere gemeinsame Korrekturen als auch die
   Tabletanforderungen erhalten. Ein neu erkannter Fehler bekommt ein eigenes
   Issue mit Reproduktion; keine pauschale Auflösung aller Konflikte zugunsten
   einer Seite und keine manuelle Reparatur generierter Assets.
4. Die Projektion aus dem vereinigten Stand vollständig neu erzeugen. Die
   betroffenen Web-/Import-/Layout-/Provenienzregressionen und bei gemeinsamem
   Quellcode die betroffenen anderen Plattformprüfungen ausführen. Ausführbare
   Änderungen, geänderte Abhängigkeiten oder neue Befunde erfordern passende
   neue Prüfungen; unveränderte bestandene Prüfungen nicht ohne Anlass wiederholen.
5. Den neuen sauberen Reviewcommit festhalten und den vollständigen APK-Gate
   einschließlich Quellbindung auf **diesem exakten Commit** ausführen. Native
   Prüfläufe müssen dieselben nachgewiesenen Kandidat-/Test-APK-Hashes verwenden.
   Nach weiteren Fixes die betroffenen Nachweise und den endgültigen Paketstand
   erneuern; ein älterer erfolgreicher Build gilt nicht für veränderte APK-Bytes.
6. Quellübernahme und Paketfreigabe getrennt bewerten: Die später beauftragte
   Integration der geprüften Quellen erfolgt nach Review des vereinigten Stands;
   offene native Restabnahmen bleiben dabei ausdrücklich dokumentiert. Für die
   stabile Veröffentlichung die unten zugeordneten erforderlichen Abnahmen auf
   dem finalen Commit/Paket abschließen und die Gesamtfreigabe in #113 festhalten.
   Eine konfliktfreie Git-Zusammenführung ist keine Funktions-, Geräte- oder
   Releaseabnahme. Dieser Auftrag stellt weiterhin Patches zur späteren Übernahme
   bereit und führt die Integration nicht vorweg.

Der am 26.11. durchgeführte lokale Merge-Tree-Vergleich und die Remote-Abfrage
belegen lediglich die konfliktfreie Zusammenführbarkeit mit dem oben genannten
unveränderten `main`; siehe [remote-baseline.json](remote-baseline.json).
Eine künftige veränderte Hauptbasis muss erneut geprüft werden.

## Ausführbare Prüfeinstiege und ihre Grenzen

Maßgeblich ist der vorhandene Workflow
[`.github/workflows/ports-2.0.30.yml`](../../../.github/workflows/ports-2.0.30.yml).
In dessen manueller Ausführung den gerade festgehaltenen Reviewzweig auswählen
und `target`/gegebenenfalls `component` wie folgt setzen. Die resultierende
Run-ID, den tatsächlichen `head_sha`, Versuch, Job und Artefakte protokollieren.
Die Auswahl allein ist noch kein Prüfnachweis.

| Workflowauswahl | Tatsächlicher Umfang | Zusätzliche Grenze |
| --- | --- | --- |
| `target=tablet` | Vollständiger APK-Gate; API34/`google_apis`; `ui` sowie getrennte `services`- und `files`-Sitzungen | `domains`, Providerstufe und Zusatzmatrizen sind nicht automatisch enthalten |
| `target=tablet-components`, `component=all` | API34; `services`, `files`, `domains` als getrennte Komponentenläufe | Kein vollständiger UI-Lauf; gezielt auch genau eine Komponente wählbar |
| `target=tablet-api26-components`, `component=all` | Entsprechende Komponentenmatrix auf API26 | Mindestplattform; keine vollständige API26-Bedienabnahme |
| `target=tablet-timezone-interop` | Eigene Zeitzonen-Vergleichsstufe auf API34 | Kein Ersatz für die vollständige Frontend-/Worker-/Restorematrix |
| `target=tablet-system-records` | API34-Providerstufe mit Kontakten, Kalendern, Identitäten, Berechtigungsprotokoll und Cleanup | Kein Activity-/Dialog-/IME-/TalkBack-/Livewiderruf-/Save-ACK-Gesamttest |
| `target=tablet-build-only` | Vollständiger APK-Gate und Quellbindung | Keine Emulator- oder native Abnahme |
| `target=tablet-aosp` | API34-AOSP-Diagnose | Kein Ersatz für die Google-Runtime-Abnahme |

`tools/native-checks.py` enthält außerdem `storage` (basics/SAF/fault/print) und
`notifications`; dafür existiert hier **kein eigener Workflowtarget**. Diese und
zusätzliche manuelle Gerätefälle müssen über die bereits dokumentierte
Native-Koordination ausgeführt und separat belegt werden. Suite `ui` umfasst
basics, restart, layout und time; die einzelnen Stufen und Exitcodes müssen
erfolgreich sein. Ein nicht durchgelaufener oder blockierter Schritt bleibt offen.

Die Workflowgrenzen bleiben verbindlich: vergebener Hauptslot, Locks bis zum
Cleanup, überprüfte Prozess-/ADB-Identität, begrenzte Zeiten, höchstens 6 GiB RAM,
kein Swap und höchstens 200 % CPU im vorhandenen nativen Wrapper. Ein isoliert
gesetztes `--main-slot-granted` erteilt keinen Slot. Vor jeder Sitzung gelten die
bestehenden Ressourcenprüfungen; parallele fremde native Läufe werden nicht
beendet. Die vollständigen existierenden Befehle stehen im verlinkten Workflow
und in der [Tablet-README](../../../Magnolie-Organizer-Android-Tablet-Beta/README.md).

### Noch offene Abnahme für den stabilen Kandidaten

| Bereich | Konkreter verbleibender Nachweis | Issues |
| --- | --- | --- |
| Tabletbedienung und Barrierefreiheit | Echte WebView; Hoch-/Querformat, kleine Fenster, große Schrift/RTL, Touch/Tastatur, IME, TalkBack und Stift; erreichbare Dialoge und Fokus/Status | #451, #792, #798, #801 |
| Zeichenblatt und native Eingabe | Fehlende Accessibility-Fensterbindung klären; echte Pointer-/Stiftsequenzen, strikte Modell-/RGBA-/PNG-/Reopen-Prüfung | #463, #458, #468 |
| Direkte Android-Kopien | Berechtigungsdialog, Livewiderruf, Abbruch während laufender Abfrage, UI-Save-ACK/Neustart; zweite Kontaktquelle und unsynchronisierte lokale Serienausnahmen | #791, #799, #800, #807 |
| Speicher, Dienste und Betriebsstabilität | SAF-/Restore-/Abbruch-/Neustartfälle, OS-Fehlerinjektion, Files/Domains, Benachrichtigungen/Reboot/Doze, reale Geräte und Upgrade; ungeklärten FontsProvider-ANR gesondert lösen | #454, #471, #472, #121 |
| Zeit, ICS und Altbestand | Aktuelle API26-/API34-/WebView-Matrix, Marker und VTIMEZONE, DATE/floating/Gap/Fold, Worker/Restore/Zonenwechsel; kollidierende Ausnahmen und bewusst gewählte Altbestandsreparatur mit Save/Reopen | #452, #453, #461, #464, #465, #680 |
| Anhänge und optionale externe Wege | Echte HTTPS-/Clipboard-Handler, Formular und Save/Reopen; DAV nur im tatsächlich zugesagten Umfang und mit zugelassenem Testserver | #682, #683 |

Die [beiden Audits](../../../contracts/android-tablet-followup-2026-11-26.md)
und die jeweiligen Issues enthalten Detailfälle. Bereits geschlossene historische
Fixes bleiben geschlossen; neue Quellfixes und historische Teilprüfungen schließen
die hier aufgeführten aktuellen Restabnahmen nicht automatisch.

## Vorhandener Erfolg und frische Nachweisprüfung

[CI #101](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45822320243)
hat auf dem oben festgehaltenen Testhead den vollständigen APK-Gate und die
API34-Providerstufe bestanden: **42 JUnit-Reports mit 303 Tests, ohne Fehler oder
Skips; zehn fachliche Providergruppen plus Cleanup; 19 protokollierte
Produkt-/Readbackprüfungen ohne WRITE_CONTACTS/WRITE_CALENDAR**.
[Originalnachweise und Artefaktprüfer](../ci-run-45822320243/README.md) binden
Quellstand, Lauf, APKs und tatsächliche Providerergebnisse. Das sind keine
303 zusätzlichen neuen Tests dieser Übergabe.

Die erneute [Integritätsprüfung](fresh-evidence-integrity.json) hat die bis dahin
vorhandenen **232 Belegdateien**, **462 CI-Quellinputs**, **83 erzeugten
Laufzeitdateien**, **63 Original-APK-Assets** und die vollständigen zwölf
Folgepatches überprüft. Der erneut gegen Original-ZIP und vollständiges Joblog
ausgeführte Artefaktprüfer lieferte denselben Bericht mit SHA256
`08a7bddc52ed4a9e14417c33867c8528c759331ec7449169aa0b163e668395d2`.
Das Serienmanifest ergänzt die Wiederherstellung der ursprünglichen fünf Patches.
Neue Handoverdateien werden zusätzlich in `../checksums.json` erfasst; die Zahl
232 bezeichnet ausdrücklich die unveränderte, vorher geprüfte Belegbasis.

Zwischen CI-Testhead und Übergabebasis änderten sich nur Dokumentation und
Nachweise; alle ausführbaren Inputs und alle Laufzeitoutputs blieben bytegleich.
Der spätere Projektionshash ist wegen erfasster Dokumentationsinputs verschieden.
Ein neuer erfolgreicher APK-/Emulatorlauf auf dem Dokumentationshead wird nicht
behauptet. `nativeAcceptance`, `googleAcceptance` und `productionRelease` bleiben
bis zur entsprechenden Gesamtprüfung falsch.

## Fortsetzungsprotokoll für kommende Änderungen

Bei jedem späteren überprüften Schritt folgende Angaben in `ARBEITSSTAND.md`,
im passenden Issue und im Prüfzweig sichern. Vollständige Patches einschließlich
Prüfsummen und Reproduktion vor der Übergabe veröffentlichen; keine nur lokal
vorhandenen Fixes als übernommen melden.

| Feld | Zu dokumentierender Inhalt |
| --- | --- |
| Auftrag und Issue | Konkrete Änderung, Reproduktion, Umfang und Abnahmekriterium |
| Basis | Datum, damals aktueller `main`, vorheriger Tablet-Head und gemeinsamer Vorfahr |
| Quellstand | Neuer tatsächlicher Remote-Commit, Tree, lokale Zuordnung, betroffene kanonische Dateien und Konfliktentscheidung |
| Buildbindung | Sauberer Checkout, Quellmanifest, Projektionshash und APK-/Test-APK-Prüfsummen |
| Ausführung | Workflowtarget/Suite, Lauf/Versuch/Job, API/Image/WebView/Gerät, tatsächlich ausgeführte Schritte und Exitcodes |
| Ergebnis | Bestandene und fehlgeschlagene Fälle, übersprungene/blockierte Teile, Rohbelege, Prüfsummen und genaue Aussagegrenzen |
| Übernahme | Patchreihenfolge/Hash/Issue-Link, geprüfter Ergebnisbaum, nächster Schritt und verbleibende Freigaben |

Die bisherigen Belege bleiben unverändert erhalten. Neue Ergebnisse ergänzen sie
mit ihrem eigenen Quellstand. So können weitere gemeinsame Änderungen übernommen
werden, ohne den Ursprung der Tabletanpassungen oder ihre offenen Grenzen zu verlieren.
