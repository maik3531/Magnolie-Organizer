# Magnolie-Codereview: Patches und Prüfnachweise vom 27. November 2026

Diese Lieferung setzt den Chat **„Magnolie Codereview Issues Patches“** fort. Sie enthält die vollständigen Korrekturen für **16 neue Issues (#817–#832)** sowie den erneuten Befund im bereits vorhandenen **#790**. Der ursprüngliche Abgleich umfasst 816 vorhandene Issues und Pull Requests einschließlich geschlossener Einträge. Neue Befunde wurden mit diesem Bestand und der aktuellen Suche abgeglichen.

Die Patches sind für die spätere Prüfung und Einpflege mit Codex bereitgestellt. **Der Hauptzweig wurde durch diesen Review nicht geändert.** Der Artefaktzweig `work/codereview-20261127-patches` enthält die Patches, ihren Index und die Nachweise. Seine unveränderten Produktquellen bilden die unten genannte Anwendungsbasis; die Korrekturen werden durch Anwendung des Gesamtpatches oder der vollständigen Reihenfolge übernommen.

## Quellstand und überprüfbare Anwendung

| Merkmal | Exakter Wert |
| --- | --- |
| Ursprünglich untersuchte Basis | `63ca6c8f351dd52627dfc550ff0075e703957ab5` |
| Anwendungsbasis nach Abgleich mit dem Hauptzweig | `d9fa9065b1fe690616e6eae2671159c224ead406` |
| Lokaler Prüfcommit mit vollständiger Übergabe | `87a65670726fc226c6d9bf4dc00d0630ecb7fabb` |
| Erwarteter Git-Ergebnisbaum nach Anwendung | `1fcc414bd0c58a7cbcd9c3c676247a76d47ea6be` |
| Gesamtpatch | [magnolie-codereview.patch](magnolie-codereview.patch) |
| SHA-256 des Gesamtpatches | `36391a599dec73baa04d4c0b192165220bd2be10e7e4ff9cabd425be85bcee36` |
| Umfang | 90 geänderte Dateien; 23 geordnete Teilpatches |

Die lokalen Prüfcommits werden zur Provenienz im [Manifest](manifest.json) aufgeführt. Der vollständige Quellstand lässt sich aus der öffentlichen Basis und dem Gesamtpatch ohne Zugriff auf den früheren Gesprächsarbeitsplatz wiederherstellen. Entscheidend ist der exakt geprüfte Ergebnisbaum; ein neuer Commit nach `git am` kann wegen seiner Commitmetadaten eine andere Commit-ID haben.

Die in den Issues verlinkten Dateien zuerst herunterladen und in einer sauberen Arbeitskopie anwenden:

```sh
git switch -c pruefung/magnolie-codereview-20261127 d9fa9065b1fe690616e6eae2671159c224ead406
git apply --check /pfad/magnolie-codereview.patch
git apply --index /pfad/magnolie-codereview.patch
git write-tree
```

Der letzte Befehl muss `1fcc414bd0c58a7cbcd9c3c676247a76d47ea6be` ausgeben. Die Anwendung wurde in einem getrennten Git-Index geprüft. Ebenso wurden sämtliche Teilpatches in der angegebenen Reihenfolge angewandt; beide Wege ergeben denselben Baum. Der Gesamtpatch wurde außerdem rückwärts geprüft. Details: [replay.json](replay.json).

**Gesamtpatch und Teilserie sind alternative Anwendungswege.** Nicht beide auf denselben Arbeitsstand anwenden. Mehrere Korrekturen bearbeiten gemeinsame Import-, Kalender- und Katalogdateien. Ein einzelner Issuepatch kann daher Vorgänger aus dem Index benötigen. Insbesondere gehören die späteren Ergänzungen zu #823 und #826 sowie die aktualisierten Quellhashes aus #829 zur fertigen Serie. Auf einem späteren Hauptzweig zunächst den vollständigen Patch mit `git apply --check` prüfen und neue Änderungen erhalten; keine erzwungene Anwendung.

## Befunde und Änderungen

### Daten und Wiederherstellung

**#823 – Kalenderidentitäten bei ergänzender Wiederherstellung.** Gleiche externe UIDs in verschiedenen Kalenderquellen wurden zusammengeführt. Windows konnte zusätzlich bei doppelten UIDs abbrechen und Notizen mit leerer UID duplizieren. Beide Implementierungen trennen jetzt Quellen- und lokale ID-Namensräume. Eine unabhängige Gegenprüfung fand anschließend den Kalenderwechsel desselben lokalen Termins: Die eindeutige lokale Identität bleibt auch bei geänderter Quelle erhalten, ohne alte Providermetadaten zurückzuholen. Nicht eindeutig auflösbare lokale IDs werden als Konflikt vor einer Übernahme abgewiesen. 37 gemeinsame Sollvektoren prüfen beide Implementierungen, Wiederholung und unveränderte Eingaben.

**#826 – Kalenderidentitäten beim normalen Synchronisieren.** Ein unveränderter oder während des Abgleichs bearbeiteter Termin konnte verschwinden; seine Notiz konnte einem anderen Kalender zugeordnet werden. Termine, Aufgaben und Löschmarkierungen werden jetzt anhand der vollständigen Quellenidentität abgeglichen. Der weitere Gegencheck deckte den reinen Kontaktlauf auf: Kalenderduplikate dürfen einen unveränderten, nicht beteiligten Kalender weder verkleinern noch den Kontaktlauf blockieren. Dazu wird die tatsächliche Startauswahl vor dem Speicher-ACK gebunden. Unerwartete Änderungen an unbeteiligten Kalenderdaten bleiben weiterhin abgewiesen. Die tatsächlichen beiden Oberflächen bestehen 56 Fälle einschließlich der Windows-Transaktionswiederholung.

**#824 – „Alles“ im Wiederherstellungsdialog.** Die Oberfläche versprach ergänzenden Datenerhalt, obwohl die nativen Implementierungen bei vollständiger Auswahl den Snapshot vollständig ersetzen. Die Oberfläche zeigt dieses Verhalten nun eindeutig an und verhindert eine widersprüchliche Verfahrenswahl. Der Hinweis steht auch im Handbuch. Geprüft wurden beide tatsächlichen DOM-Oberflächen in sechs Sprachen.

### Import, Stabilität und unnötige Arbeit

**#817 – UTF-16-CSV.** Gültige Dateien mit Byte-Order-Mark wurden bereits anhand der noch nicht dekodierten Nullbytes abgewiesen. Der Parser dekodiert zuerst und prüft danach auf tatsächlich ungültigen Text. Defekte Unicode-Daten und nicht unterstützte Binärformate werden weiter abgelehnt. Die 32 gezielten Pythonfälle sowie der tatsächlich projizierte Mac-Importhelper sind geprüft.

**#818 – volle automatische Sicherungsordner.** Bei 1.000 vorhandenen Einträgen wurde bei jedem Versuch zunächst ein neues Archiv verschlüsselt und geschrieben, bevor die begrenzte Verzeichnisprüfung scheiterte. Beide Desktoppfade prüfen die freie Aufnahmekapazität vor der teuren Arbeit. 999 vorhandene Einträge lassen noch einen weiteren zu; ein voller Ordner wird ohne neues Archiv abgewiesen. Der Windows-Hosttest prüft die Kapazitätslogik; die echte Windows-DPAPI-Archivschreibung bleibt ausdrücklich eine native Prüfung.

**#819 – Notes-Zeitstempel.** Sekundenbruchteile wurden als Millisekundenzahl interpretiert. Beispielsweise wurde `.123456` zu einem Versatz von 123,456 Sekunden. Die Parseränderung erhält die richtige Zeit bis zur Millisekundenauflösung und verwirft ungültige oder unvollständig gelesene Datumswerte.

**#822 – Google-Keep-Erkennung.** Allgemeines JSON oder HTML wurde zu früh als Keep gelesen; beispielsweise ging `body` aus einer gewöhnlichen JSON-Notiz verloren. Keep-spezifische Strukturmerkmale steuern jetzt die Auswahl. Allgemeine Inhalte gelangen zu den vorgesehenen Fallbacks; tatsächliche Keep-Exporte bleiben positiv geprüft.

**#821 – Notes-Ordnerimport.** Ein flacher Ordner mit 5.001 Dateien umging die vorhandene Mengenbegrenzung. Ein gemeinsames Budget gilt jetzt für den vollständigen Vorgang, einschließlich Unterordnern, Eingabedaten und dekodierten Notizfeldern. Ein Grenzfehler beendet die Vorbereitung vor der Übernahme. Das Handbuch erläutert die Grenzen und den vollständigen Abbruch in allen 20 Sprachen. Das ist **keine feste Obergrenze für den gesamten Android-Heap**: Der Systemprovider und einzelne Parser können ihre Listen bereits vor der nachgelagerten Budgetprüfung materialisieren.

**#825 – verschachtelte Archive.** ZIP-Inhalte unter anderen erlaubten Dateiendungen setzten Entpackgrenzen zurück. Tatsächliche innere ZIP-Signaturen werden nun vor einer erneuten Parserausführung erkannt und entsprechend der bestehenden Handbuchregel abgelehnt. Flache Archive und eigenständige unterstützte Samsung-Exporte bleiben lesbar.

**#830 – Downloadgenerator.** Ein mehrzeiliger RegEx entfernte neben der gewünschten URL auch die noch benötigte F-Droid-Konstante. Die Änderung beschränkt den Ersatz auf die jeweilige Zuweisungszeile. Nachbarkonstanten und wiederholbare Erzeugung sind geprüft.

### Übersetzungen und Handbuch

**#820 – Linux-Kataloge.** Aktive Wiederherstellungs- und GTK-Texte fehlten nach früheren abgeschlossenen Korrekturen in den Katalogen. 94 fehlende Übersetzungen wurden ergänzt, aktive bedingte Meldungen richtig markiert und nicht mehr benutzte Schlüssel entfernt. Alle weiterhin benötigten Übersetzungen wurden gegen die Basis verglichen.

**#827 – kanonische Handbuchkataloge.** Neun aktuelle Schlüssel fehlten; drei überholte Texte blieben in POT/PO stehen. Die passenden Übersetzungen waren in den Laufzeitabbildungen vorhanden und wurden unverändert in die kanonischen Kataloge übernommen. Dieser Befund bedeutet deshalb nicht, dass sämtliche betroffenen Seiten vorher englisch angezeigt wurden. Der abschließende Katalogaudit enthält 463 Schlüssel und 19 vollständige Übersetzungskataloge ohne fehlende, leere oder fuzzy Einträge.

**#828 – Portugiesisch.** Die Verneinung wurde in beiden Desktopkatalogen von `No` zu `Não` berichtigt. Der tatsächliche Gerätestatusdialog beider Oberflächen wurde mit neu erzeugten Katalogen geprüft.

**#832 – Speicherverbrauch der Handbuch-Prüfdiagnose.** Bei einer veralteten großen Handbuchkopie erzeugte `assert.deepStrictEqual` einen riesigen Buffer-Diff. Der beobachtete Diagnoseprozess erreichte 7.936.720 KiB MaxRSS und wurde beendet. Die neue Prüfung vergleicht weiterhin jedes Byte, gibt aber nur die konkrete Datei und eine kurze Fehlermeldung aus. Gleiche Ein-MiB-Dateien, ein abweichendes letztes Byte und eine fehlende Datei sind geprüft. Der Befund betrifft die Prüfdiagnose; ein entsprechender Absturz der Handbuchoberfläche wird nicht behauptet.

### Plattformverträge und geschlossene Befunde

**#831 – Windows-WebBridge.** Drei bereits verwendete Webcam-Befehle und fünf benötigte Medienfelder fehlten im äußeren Validator. Reguläre Befehle wurden vor dem vorhandenen nativen Handler abgewiesen. Der Patch ergänzt die konkret benötigten Typen; die engere Aktions-, Zustands- und Berechtigungsprüfung bleibt erhalten. Positive und negative Nachrichten wurden durch die tatsächlichen C#-Parser ausgeführt.

**#829 – Paritätsprüfung.** Der Quellparser erkannte einen aktuellen Spread nicht, und die Fixture war veraltet. Der Sender schreibt die normalisierten Felder ausdrücklich; unbekannte dynamische Spreads bleiben verboten. Sieben Windows-Medienadapter und die Webcam-Routen werden anhand realer Sender, Dispatcher und Handler zugeordnet. Der Vergleich umfasst 153 Befehls- und 97 Rückrufverträge. Das belegt den Quellvertrag, keine identische vollständige native Implementierung. Eine alte Linux-Sicherungsordnerhilfe wird nur so lange ausgeklammert, wie sie tatsächlich unbenutzt ist; ihre Wiederanbindung lässt das Gate erneut anschlagen.

**#790 – vorhandenes Issue erneut geprüft.** Die Mac-Quellprüfung verlangte weiterhin einen alten Tabletstand, obwohl dessen Bau auf aktuelle gemeinsame Quellen umgestellt worden war. Der bestehende Befund wurde wieder geöffnet und die Prüfung an den aktuellen Quellvertrag angepasst; dafür wurde kein doppeltes Issue erzeugt.

## Patchindex

Die Reihenfolge ist Bestandteil der Lieferung. Jeder Eintrag nennt die zugehörigen vorhandenen Issues; die genauen Basis-/Ergebnisinformationen und SHA-256-Werte stehen im Manifest.

| Reihenfolge | Issues | Vollständiger Teilpatch |
| --- | --- | --- |
| 01 | [#817](https://github.com/maik3531/Magnolie-Organizer/issues/817) | [Fix UTF-16 CSV imports before binary detection (Refs #817)](series/01-fix-utf-16-csv-imports-before-binary-detection-refs-817.patch) |
| 02 | [#818](https://github.com/maik3531/Magnolie-Organizer/issues/818) | [Reject full backup folders before creating new archives (Refs #818)](series/02-reject-full-backup-folders-before-creating-new-archives-refs-818.patch) |
| 03 | [#818](https://github.com/maik3531/Magnolie-Organizer/issues/818) | [Refs #818: preflight Windows automatic-backup capacity before archive writes](series/03-refs-818-preflight-windows-automatic-backup-capacity-before-archive-writes.patch) |
| 04 | [#819](https://github.com/maik3531/Magnolie-Organizer/issues/819) | [Refs #819: Preserve fractional seconds in note import timestamps](series/04-refs-819-preserve-fractional-seconds-in-note-import-timestamps.patch) |
| 05 | [#822](https://github.com/maik3531/Magnolie-Organizer/issues/822) | [Refs #822: Recognize Keep exports before selecting lossy note readers](series/05-refs-822-recognize-keep-exports-before-selecting-lossy-note-readers.patch) |
| 06 | [#821](https://github.com/maik3531/Magnolie-Organizer/issues/821) | [Refs #821: Bound the complete folder note import before persistence](series/06-refs-821-bound-the-complete-folder-note-import-before-persistence.patch) |
| 07 | [#825](https://github.com/maik3531/Magnolie-Organizer/issues/825) | [Refs #825: Reject nested note archives by contents before recursive import](series/07-refs-825-reject-nested-note-archives-by-contents-before-recursive-import.patch) |
| 08 | [#820](https://github.com/maik3531/Magnolie-Organizer/issues/820) | [Refs #820: complete current Linux catalog sources and recovery translations](series/08-refs-820-complete-current-linux-catalog-sources-and-recovery-translations.patch) |
| 09 | [#824](https://github.com/maik3531/Magnolie-Organizer/issues/824) | [Refs #824: show exact replacement for complete journal restore](series/09-refs-824-show-exact-replacement-for-complete-journal-restore.patch) |
| 10 | [#821](https://github.com/maik3531/Magnolie-Organizer/issues/821), [#92](https://github.com/maik3531/Magnolie-Organizer/issues/92) | [Refs #821 #92: Explain current note import limits in every handbook language](series/10-refs-821-92-explain-current-note-import-limits-in-every-handbook-language.patch) |
| 11 | [#790](https://github.com/maik3531/Magnolie-Organizer/issues/790) | [Refs #790: verify current tablet checkout in the Mac source gate](series/11-refs-790-verify-current-tablet-checkout-in-the-mac-source-gate.patch) |
| 12 | [#823](https://github.com/maik3531/Magnolie-Organizer/issues/823) | [Preserve additive restore identities across calendar sources (Refs #823)](series/12-preserve-additive-restore-identities-across-calendar-sources-refs-823.patch) |
| 13 | [#827](https://github.com/maik3531/Magnolie-Organizer/issues/827) | [Refs #827: synchronize handbook catalogs with current source appendices](series/13-refs-827-synchronize-handbook-catalogs-with-current-source-appendices.patch) |
| 14 | [#830](https://github.com/maik3531/Magnolie-Organizer/issues/830) | [Refs #830: Preserve adjacent setup constants when generating download URLs](series/14-refs-830-preserve-adjacent-setup-constants-when-generating-download-urls.patch) |
| 15 | [#828](https://github.com/maik3531/Magnolie-Organizer/issues/828) | [Refs #828: translate Portuguese No in both desktop catalogs](series/15-refs-828-translate-portuguese-no-in-both-desktop-catalogs.patch) |
| 16 | [#826](https://github.com/maik3531/Magnolie-Organizer/issues/826) | [Keep calendar sources distinct during synchronization replies (Refs #826)](series/16-keep-calendar-sources-distinct-during-synchronization-replies-refs-826.patch) |
| 17 | [#831](https://github.com/maik3531/Magnolie-Organizer/issues/831) | [Refs #831: admit existing native media and webcam bridge envelopes](series/17-refs-831-admit-existing-native-media-and-webcam-bridge-envelopes.patch) |
| 18 | [#829](https://github.com/maik3531/Magnolie-Organizer/issues/829) | [Refs #829: compare current media adapters without masking bridge gaps](series/18-refs-829-compare-current-media-adapters-without-masking-bridge-gaps.patch) |
| 19 | [#826](https://github.com/maik3531/Magnolie-Organizer/issues/826) | [Refs #826: isolate contact-only sync from unselected calendars](series/19-refs-826-isolate-contact-only-sync-from-unselected-calendars.patch) |
| 20 | [#832](https://github.com/maik3531/Magnolie-Organizer/issues/832) | [Refs #832: bound handbook byte-mismatch diagnostics without weakening equality](series/20-refs-832-bound-handbook-byte-mismatch-diagnostics-without-weakening-equality.patch) |
| 21 | [#823](https://github.com/maik3531/Magnolie-Organizer/issues/823) | [Refs #823: preserve stable local identities across restored calendar source changes](series/21-refs-823-preserve-stable-local-identities-across-restored-calendar-source-change.patch) |
| 22 | [#829](https://github.com/maik3531/Magnolie-Organizer/issues/829) | [Refs #829: refresh parity source hashes after final calendar corrections](series/22-refs-829-refresh-parity-source-hashes-after-final-calendar-corrections.patch) |
| 23 | [#113](https://github.com/maik3531/Magnolie-Organizer/issues/113) | [Refs #113: record continued code review, patch handoff and verification limits](series/23-refs-113-record-continued-code-review-patch-handoff-and-verification-limits.patch) |

## Tatsächlich erzielte Nachweise

Die folgenden Zeilen sind einzelne Prüfläufe mit unterschiedlichem Umfang. Sie werden nicht zu einer vermeintlich eindeutigen Gesamtzahl addiert.

| Bereich | Nachweis |
| --- | --- |
| Abschließende Integration | 11 Prüfkommandos erfolgreich: 110 fokussierte Pythonfälle, fünf .NET-Gruppen mit ausdrücklich ausgewiesenem DPAPI-Skip, 56 Sync-Fälle über beide Oberflächen, Journal-/Paritäts-/Diagnoseprüfungen und .NET-Bau |
| Wiederherstellung #823 | 37 gemeinsame Vektoren in Python und C#; zusätzlicher Pythonlauf mit vorhandenen Schutz-/Commitprüfungen: 110 bestanden; bestehende C#-Journalgruppe bestanden |
| Synchronisierung #826 | 56/56 Fälle in beiden tatsächlichen Frontends; bestehende MCP-Läufe getrennt je Plattform, Kontaktbereinigung mit kompiliertem C#-Planer und Kontaktkonflikte bestanden |
| Notes-Import | 20 JUnit-Gruppen am tatsächlichen Kotlin-Produktcode bestanden; unabhängig erneut geprüft |
| Downloadgenerator | 9/9 Tests, einschließlich QR-Dekodierung, Nachbarkonstanten und Wiederholbarkeit |
| Tablet-Systemimporte | 38 Kotlin-Gruppen und 46 UI-Prüfungen im Host bestanden; Provider-/Speichergrenzen synthetisch |
| Linux-Lokalisierung | 10 Python-Testgruppen, alle 19 Kataloge; 39 tatsächliche Frontend-/Sprachfälle bestanden |
| Handbuchkataloge | 9/9 Katalogtests; 463 Schlüssel; 19 Kataloge mit passender MO-/JS-Ableitung; 20 redaktionelle Sprachvarianten |
| Vollständiges Handbuch | Unveränderter vollständiger Lauf bestanden: 20 Sprachen, eigenständig/eingebettet, beide Plattformvarianten; 170 englische und 170 deutsche Seiten; Quell- und gerenderte Sprachkataloge |
| Mac-Quell-/Helperprojektion | 7 Kandidatquelltests, 18 tatsächliche Importhelpertests und 28 Projektionsprüfungen bestanden, ohne Skips |
| Windows-Brückenkorrektur | 2 neue Parsergruppen, bestehende gemeinsame Medienpräferenzen und Telefon-Protokollgruppe bestanden; Medien-UI und 29 Quellordnerfälle bestanden |
| Handbuch-Fehlerdiagnose | 3/3 Helperfälle; exakte Bytegleichheit bei kurzen Fehlermeldungen |
| Patchanwendung | Gesamtpatch und vollständige Teilserie ergeben exakt denselben erwarteten Git-Baum; Rückwärtsprüfung bestanden |

Die vollständigen Logs und die Quellbindungen stehen unter [logs](logs), [manifest.json](manifest.json) und [replay.json](replay.json). Umgebungsabhängige absolute Arbeitsverzeichnisse sind in den veröffentlichten Logs ersetzt; Status, Assertions und Fehlermeldungen wurden nicht verändert. Eine erfolgreiche historische Suite wird nur für ihren protokollierten Quellstand behauptet. Die abschließenden gezielten Integrationsprüfungen decken die danach geänderten Kalender-/Bridgepfade ab.

## Wiederholung wichtiger Prüfungen

Vorher die regulären Abhängigkeiten und abgeleiteten Sprach-/Zeitzonen-/Webressourcen nach den vorhandenen Plattform-Bauanweisungen vorbereiten. Die Kataloggeneratoren sind Teil der Quelle; vorbereitete Ausgaben aus einem älteren Checkout sind kein Ersatz. In der Hostumgebung wurden die bereits vorhandenen .NET-8-, Kotlin-/JUnit-, gettext-, Python- und jsdom-Werkzeuge verwendet.

```sh
python3 -m pytest -q magnolie-organizer/pruefungen/test_csv_unicode_import.py magnolie-organizer/pruefungen/test_cloud_backup_capacity.py magnolie-organizer/pruefungen/test_restore_identity.py
python3 -m pytest -q tools/test_mobile_downloads.py
python3 magnolie-handbuch/werkzeuge/kataloge_bauen.py
python3 -m pytest -q magnolie-handbuch/pruefungen/katalog_test.py
python3 magnolie-handbuch/pruefungen/katalog_audit.py
node magnolie-handbuch/pruefungen/editorial_test.js
node magnolie-handbuch/pruefungen/handbuch_test.js
```

Aus `magnolie-organizer-windows`:

```sh
dotnet run --project tests/CoreTests.csproj -c Release -- 'Device file native media UI'
dotnet run --project tests/CoreTests.csproj -c Release --no-build -- 'Additive restore'
dotnet run --project tests/CoreTests.csproj -c Release --no-build -- 'Wiederherstellungsjournal'
dotnet run --project tests/CoreTests.csproj -c Release --no-build -- 'Cloud-Ordner'
node tests/linux-live-parity.js
node tests/full-parity-contract.js
node tests/sync-calendar-identity.js
node tests/journal-selection.js
node tests/handbook-source-diagnostics.js
```

Die Notes-Regressionsklassen heißen `LeserZeitTest`, `EinfuhrErkennungTest`, `EinfuhrOrdnerTest` und `EinfuhrVerschachtelteArchiveTest`. Der dokumentierte Hostnachweis verwendet die tatsächlichen Importquellen mit ausdrücklich synthetischen Android-/Ablagegrenzen; er ersetzt keinen vollständigen Gradle-/APK-/Androidlauf.

## Geschlossene Issues, Fehlalarme und Grenzen

Geschlossene Einträge wurden anhand ihrer Quellen und vorhandenen Regressionsfälle nachgeprüft, unter anderem #436, #442, #565, #761, #450, #601, #92, #799 und #800. #813/#814 wurden auf die Linux-Kataloge und die aktuelle Offline-Wiederherstellung übertragen; daraus entstand der bestätigte Rest #820. #790 wurde bei erneutem Befund wieder geöffnet.

Die alten roten Mac-Logs wurden auf fehlendes `msgfmt` und eine nicht korrekt angebundene bereits vorhandene jsdom-Abhängigkeit zurückgeführt. Die betroffenen Suiten bestehen nach korrekter Vorbereitung ohne Änderung ihrer Assertions. Ein nicht existierender C#-Testfilter und ein Host-Socketverbot wurden nicht als Produktfehler ausgegeben. Die lautlosen Handbuchläufe waren kein Beweis eines Hängers: Der unveränderte volle Lauf brauchte 388,220 Sekunden und endete erfolgreich. Die separate große Buffer-Fehlerdiagnose ist dagegen in #832 konkret erfasst.

Die neuen Codekorrekturen wurden in dieser Runde **nicht als installierte Windows-, Linux-, macOS- oder Android-Pakete abgenommen**. .NET unter Linux ist kein Windows-GUI-/DPAPI-Nachweis; JSDOM ist keine WebView2-/WKWebView-/GTK-Geometrie- oder Druckabnahme. Reale CalDAV-Anbieter, Telefonkameras, Mikrofone und persönliche Daten wurden für diese Reviewnachweise nicht benutzt. Technisch vollständige Kataloge sind keine muttersprachliche Prüfung aller Übersetzungen.

Die zugehörigen Issues bleiben für die tatsächliche Einpflege und die dort genannten restlichen Abnahmen offen. Der übergreifende Stand ist in [#113](https://github.com/maik3531/Magnolie-Organizer/issues/113) verlinkt. Der Review bestätigt die beschriebenen Fehler und Korrekturen; er behauptet weder eine vollständige native Gesamtabnahme noch Fehlerfreiheit jeder Projektfunktion.
