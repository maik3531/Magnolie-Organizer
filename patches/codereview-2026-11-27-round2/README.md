# Magnolie-Codereview: zweite Patchlieferung vom 27. November 2026

## Ergebnis und Verwendung

Vier neue bestätigte Befunde sind als vollständige Issue-Patches vorbereitet:
#835 bis #838. Hinzu kommt der synthetisch reproduzierte CSV-Teilfall des
vorhandenen Issues #566. Die Lieferung setzt die erste Reviewrunde fort.
Die Produktänderungen sind zur späteren Einpflege mit Codex bestimmt.

| Issue | Bestätigter Fehler und Korrektur | Detailnachweis |
| --- | --- | --- |
| [#835](https://github.com/maik3531/Magnolie-Organizer/issues/835) | Feste ICS-Alarmzeitpunkte werden im Windows-Scheduler und in Linux-Hintergrundpfaden ausgelassen. Die Korrektur bindet Alarme an Komponente, Quelle und vollständigen UTC-Zeitpunkt; Serien, Projektionen, alte Quittierungen und zeitgleiche normale Alarme bleiben konsistent. | [Alarmbericht](evidence/reminders/835-report.md) |
| [#836](https://github.com/maik3531/Magnolie-Organizer/issues/836) | Notes lässt Cache-/Providerfehler beim Öffnen eines Anhangs bis zum UI-Klickhandler entweichen und bereitet Dateien auf dem UI-Thread vor. Vorbereitung läuft auf dem I/O-Dispatcher; erwartete Fehler liefern den bestehenden Fehlerdialogpfad, Coroutine-Abbruch bleibt erhalten und Tempdateien werden bereinigt. | [Notes-Bericht](evidence/notes/836-report.md) |
| [#837](https://github.com/maik3531/Magnolie-Organizer/issues/837) | Windows verliert CSV-Abschluss- und Prioritätswerte; Linux liest „Normal“ als niedrige Priorität. Beide Reader verwenden die belegten exakten Werte und erhalten unbekannte Werte neutral. | [CSV-Aufgabenbericht](evidence/data/837/HANDOFF.md) |
| [#566, CSV-Teilfall](https://github.com/maik3531/Magnolie-Organizer/issues/566) | Windows verliert zweite Anschriften und Telefonrollen. Linux erfindet bei bestimmten Spaltenfolgen eine HOME- oder Mischanschrift. Rollen werden zuerst getrennt gelesen; Skalarfelder stammen aus einer tatsächlich vorhandenen Anschrift. | [CSV-Kontaktbericht](evidence/data/566/HANDOFF.md) |
| [#838](https://github.com/maik3531/Magnolie-Organizer/issues/838) | Catch-Bindungen verdecken im Zeichenblatt die Übersetzungsfunktion. Fehler werden dadurch nicht verständlich angezeigt. Beide Frontends erreichen die vorhandenen Meldungen; ein anschließend gültiger JSON-Import aktualisiert auch die Statuszeile. | [Zeichenblattbericht](evidence/ui/838-summary.md) |

Der historische private OR6-/UI-Konflikt in #566 ist durch den belegten
CSV-Teilfall weder erklärt noch insgesamt als behoben ausgewiesen.

## Exakte Quellbindung

| Eigenschaft | Wert |
| --- | --- |
| Anwendungsbasis | `1543858e251d7e29ebeafb67d2605991c1d442d5` |
| Geprüfter Quellcommit nach Anwendung | `ed3ffa936088840e4c3437eab5c37417fd31c86b` |
| Erwarteter vollständiger Git-Quellbaum | `5bf49b5e9250ba2c3f376ccf86d58dc018139c6f` |
| Umfang | 25 geänderte Quelldateien, 7 geordnete Teilpatches |
| SHA-256 des Gesamtpatchs | `79e8ec06b4f0565153413472fc8f4bfce4ff246c01762a638948f6253c302559` |

Dieser Artefaktzweig enthält die Produktquellen der Anwendungsbasis. Die
Korrekturen stehen vollständig in den verlinkten Patches; sie werden hier
nicht als bereits in `main` integriert ausgegeben. Der Review hat `main`
nicht verändert und kein Paket veröffentlicht.

Die erste Lieferung auf `work/codereview-20261127-patches` bleibt unverändert
erhalten. Die zweite Lieferung verwendet den zwischenzeitlich fortgeschriebenen
Hauptzweig als eigene feste Basis. Die Lieferungen deshalb nicht blind
hintereinander auf denselben alten Checkout anwenden.

## Anwendung

Der [Gesamtpatch](magnolie-codereview-round2.patch) und die unten geordnete
Serie sind zwei alternative Wege zum selben Quellstand. Beide wurden in
getrennten Git-Indexes auf der genannten Basis angewendet und ergeben exakt
den angegebenen Git-Quellbaum. Auch die umgekehrte Anwendbarkeitsprüfung des
Gesamtpatchs ist bestanden. Details: [replay.json](replay.json).

In einem sauberen Checkout der genannten Basis, mit `PATCH_DIR` als lokalem
Pfad zu dieser Lieferung:

```sh
git rev-parse HEAD
git apply --check "$PATCH_DIR/magnolie-codereview-round2.patch"
git apply --index "$PATCH_DIR/magnolie-codereview-round2.patch"
git write-tree
```

Alternativ die vollständige Commitserie in der angegebenen Reihenfolge
anwenden:

```sh
git am "$PATCH_DIR"/series/*.patch
git rev-parse 'HEAD^{tree}'
```

Der Git-Commit kann bei `git am` wegen lokaler Committer-Metadaten abweichen;
der vollständige Quellbaum muss mit dem oben genannten Wert übereinstimmen.
Auf einem neueren Hauptzweig zunächst bereits übernommene Fixes und geänderte
Kontextstellen abgleichen. Der Kontaktpatch baut in derselben CSV-Quelle auf
dem Aufgabenpatch #837 auf. Beide Zeichenblattpatches gehören zusammen:
Fehlermeldung und erfolgreiche Wiederholung.

| Reihenfolge | Zugehörige Issues | Vollständiger Teilpatch |
| --- | --- | --- |
| 01 | [#835](https://github.com/maik3531/Magnolie-Organizer/issues/835) | [Refs #835: Deliver absolute calendar alarms once across projections and restarts](series/01-refs-835-deliver-absolute-calendar-alarms-once-across-projections-and-restarts.patch) |
| 02 | [#836](https://github.com/maik3531/Magnolie-Organizer/issues/836) | [Refs #836: contain Notes attachment opening failures off the UI thread](series/02-refs-836-contain-notes-attachment-opening-failures-off-the-ui-thread.patch) |
| 03 | [#837](https://github.com/maik3531/Magnolie-Organizer/issues/837) | [Refs #837: Preserve CSV task priority and completion values](series/03-refs-837-preserve-csv-task-priority-and-completion-values.patch) |
| 04 | [#566](https://github.com/maik3531/Magnolie-Organizer/issues/566) | [Refs #566: Preserve CSV contact addresses within their source roles](series/04-refs-566-preserve-csv-contact-addresses-within-their-source-roles.patch) |
| 05 | [#838](https://github.com/maik3531/Magnolie-Organizer/issues/838) | [Fix localized drawing error feedback (Refs #838)](series/05-fix-localized-drawing-error-feedback-refs-838.patch) |
| 06 | [#838](https://github.com/maik3531/Magnolie-Organizer/issues/838) | [Clear drawing import error after valid retry (Refs #838)](series/06-clear-drawing-import-error-after-valid-retry-refs-838.patch) |
| 07 | [#113](https://github.com/maik3531/Magnolie-Organizer/issues/113), [#835](https://github.com/maik3531/Magnolie-Organizer/issues/835), [#836](https://github.com/maik3531/Magnolie-Organizer/issues/836), [#837](https://github.com/maik3531/Magnolie-Organizer/issues/837), [#566](https://github.com/maik3531/Magnolie-Organizer/issues/566), [#838](https://github.com/maik3531/Magnolie-Organizer/issues/838) | [Refs #113 #835 #836 #837 #566 #838: Record second review handoff and verified host limits](series/07-refs-113-835-836-837-566-838-record-second-review-handoff-and-verified-host-limits.patch) |


Der letzte Dokumentationspatch korrigiert auch den zwischenzeitlich falsch
eingeordneten Exchange-Testlauf: Mit ausdrücklich gesetzter Hostzeitzone
`TZ=Europe/Berlin` und dem vorhandenen `TZDIR` bestehen Basis und CSV-Endstand.
Der rote Lauf war eine Testumgebungsursache; dafür wurde kein Produktfix
vorgenommen. [Ursachenanalyse](evidence/data/exchange-diagnosis/REPORT.md).

## Abgleich mit zwischenzeitlichem Hauptzweig

Am geprüften Hauptzweig-Checkpoint
`244b1d62aa738ea5cd8fa7fc9449ccf62fb7b99d` ist die ursprüngliche
Catch-Korrektur aus #838 bereits parallel übernommen. Sie wird dort nicht
erneut benötigt. Die Statuszeile nach Fehler und anschließend gültigem
JSON-Import blieb jedoch in beiden Frontends fehlerhaft: Die Zeichnung
wurde ersetzt, die alte Fehlermeldung blieb sichtbar.

Die [separate Ergänzung für diesen Checkpoint](evidence/ui/main244-retry/838-retry-only-against-244b1d62.patch)
ändert ausschließlich zwei Produktzeilen. Derselbe echte FileReader-Prüfer
scheitert zuvor in allen vier Kombinationen aus Linux/Windows und Deutsch/
Englisch; mit der Ergänzung bestehen alle vier. Die zum Prüfen geladenen
angepassten Produkttexte werden mit den Patch-Ergebnissen verglichen; `main`
wurde dabei nicht verändert. [Bericht und Anwendung](evidence/ui/main244-retry/README.md).

Die Quelländerungen der ersten vier Serienpatches (#835, #836, #837, #566)
ließen sich auf diesem Checkpoint in der angegebenen Reihenfolge ebenfalls
ohne Konflikt anwenden, wenn `ARBEITSSTAND.md` ausgenommen wird. Dies ist ein
zusätzlicher Anwendbarkeitsnachweis, kein erneuter Lauf aller Tests auf diesem
fortgeschriebenen Hauptzweig. Die Dokumentation muss mit dessen weiterem
Arbeitsstand zusammengeführt werden. [Prüfprotokoll](main-compatibility.json).

### Weitere Übernahmen bis 8d9aec67

Der spätere Hauptzweig `8d9aec671a4c63f999ed7fbe74f8752af6978250` enthält
auch die parallelen Korrekturen für #836 und #837. Der gezielte Quellenvergleich
bestätigt bei Notes alle hier belegten Schutzfunktionen. Dies ist ein
Quellenabgleich der übernommenen Fassung, kein neuer Android-Testlauf.

Bei #837 fehlten in dieser Übernahme weiterhin die bisherigen Prioritäts-
Kurzwerte `H` und `N`: Beide tatsächlichen Reader ordneten sie als normal ein.
Die [gezielte Ergänzung für 8d9aec67](evidence/data/main8d9-hn/837-main8d9-hn.patch)
nimmt nur diese Werte in die exakten Mengen auf, ergänzt zwei vorhandene
Vertragszeilen und präzisiert den Arbeitsstand. Neuere Spaltenaliase bleiben
erhalten. Die direkte Probe besteht nachher in acht von acht Fällen;
die vorhandenen Python- und C#-Aufgabenprüfungen bestehen ebenfalls.
[Bericht und Vorher-/Nachher-Belege](evidence/data/main8d9-hn/README.md).

Der historische Kontaktpatch #566 benötigt nach dieser parallelen Übernahme
eine angepasste Einordnung seiner Helfer und Testregistrierung. Der
[vollständige angepasste Kontaktpatch](evidence/data/main8d9-contacts/566-after-837-main8d9.patch)
folgt unmittelbar auf den H/N-Nachtrag, also auf Quellstand
`14bc2fa1330037120f98b6dc31c76f5690a29eb6`. Kontaktfunktionen und Kontaktvektoren
bleiben zum zuvor geprüften Fix bytegleich; die neuere Aufgaben-/Aliaslogik
bleibt erhalten. Elf Pythonfälle und beide C#-CSV-Gruppen bestehen gemeinsam.
[Bericht und Quellvergleiche](evidence/data/main8d9-contacts/README.md).

Die gezielten Ergänzungen sind für die jeweiligen neueren Hauptzweigstände
bestimmt. Ihre Produktkorrekturen sind bereits in der vollständigen
historischen Serie gegen 1543858e enthalten. Übernahmestand und noch offene
Reste werden zusätzlich in den zugehörigen Issues dokumentiert.

Für die feste neuere Basis `8d9aec67` ist zusätzlich folgende Reihenfolge in
einem temporären Git-Index geprüft: H/N-Nachtrag, angepasster Kontaktpatch,
JSON-Retry-Nachtrag, danach Alarmteilpatch 01 mit ausgenommener
`ARBEITSSTAND.md`. Die beiden ersten Schritte erzeugen exakt die separat
geprüften Quellbäume; alle vier Schritte sind konfliktfrei anwendbar.
Die Dokumentation der Alarmkorrektur steht im Issue und muss beim Einpflegen
mit dem fortgeschriebenen Arbeitsstand zusammengeführt werden. Dies ist eine
Anwendbarkeitsprüfung; der Nachweis wird nicht als neuer vollständiger
Laufzeittest dieser gesamten neueren Komposition ausgegeben.
[Exakte Reihenfolge und Quellbäume](current-integration-replay.json).

## Prüfungen und Aussagegrenzen

Die endgültigen Prüfkommandos, Exitcodes und Logs stehen in
[evidence/final/summary.json](evidence/final/summary.json). Die Berichtszahlen
bezeichnen je nach Prüfer Fälle, Assertions oder Testgruppen; sich
überschneidende Läufe werden nicht zu einer scheinbaren Gesamtzahl addiert.

- Die Alarmtests verwenden die tatsächlichen ICS-Importer, Scheduler,
  Hintergrundprojektionen und real geschriebene Zustandsdateien. Der gemeinsame
  Vertrag enthält 24 Szenarien beziehungsweise 138 C#-Projektionsfälle.
  Zusätzliche Prüfungen sichern Sekunden, Sommerzeit-Doppelstunden,
  Quellenidentität, alte Quittierungen, undatierte Aufgaben, ungültige Angaben,
  vertrauliche Daten und gleichzeitig fällige normale/relative Alarme ab.
- Die CSV-Tests verwenden 27 Aufgaben- und acht Kontaktvektoren sowie
  wiederholte VTODO-/vCard-Ausgabe- und Einlesezyklen. Bestehende OR6-Fälle und
  der umfassende Exchange-Test sind zusätzlich geprüft.
- Notes besteht 13 JUnit-Gruppen mit tatsächlichem Produktdecoder,
  Coroutinefunktion und Dateisystem. Ein echter Schreibfehler durch eine nur
  für den Testprozess gesetzte Dateigrößengrenze liefert nach dem Fix `false`
  und hinterlässt keine Tempdatei. Die vorherige Cachedatei bleibt erhalten.
- Das Zeichenblatt besteht 16 neue UI-Szenarien über Deutsch/Englisch und beide
  Desktopquellen, einschließlich gültiger Wiederholung. Bestehende Zeichenblatt-
  und Zeitzonenprüfungen bleiben grün.

Die .NET-Läufe erfolgten mit tatsächlichen C#-Produktquellen auf dem Linux-Host.
Die Webtests verwenden JSDOM; die Notes-Hostprüfung ersetzt Android-Grenzen
explizit und ist kein Robolectric-, Compose-Gesamtbau- oder APK-Lauf. Native
Windows-/Linux-Benachrichtigungen, installierte Pakete und Android-Provider/
Viewer wurden in dieser Runde nicht abgenommen. Mac und Tablet werden durch
diese Lieferung nicht als geändert oder geprüft ausgegeben.

Bestehende plattformspezifische Nachholfenster wurden nicht vereinheitlicht.
Die Korrektur absoluter Alarme erhält die jeweiligen Ausschluss- und
Nachholregeln. Der Alarmbericht benennt diese Grenze ausdrücklich.

## Vollständigkeit und Prüfsummen

[manifest.json](manifest.json) bindet Gesamtpatch, Einzelpatches, Quellstand
und Nachweise. [SHA256SUMS](SHA256SUMS) enthält die Prüfsummen aller Dateien
dieses Verzeichnisses außer der Prüfsummenliste selbst.

```sh
cd "$PATCH_DIR"
sha256sum --check SHA256SUMS
```

Die veröffentlichten Protokolle enthalten synthetische Testdaten. Absolute
Arbeitsverzeichnisse sind durch lesbare Platzhalter wie `$REVIEW_SOURCE` und
`$REVIEW_TOOLS` ersetzt; die Ergebnisse und Assertions bleiben unverändert.
Die Prüfsummen beziehen sich auf diese veröffentlichten Textdateien.
Historische rote Logs bleiben mit ihrer Ursachenbeschreibung erhalten.
Einzelberichte und ursprüngliche Einzelpatches unter `evidence` dokumentieren
ihre damaligen isolierten Prüfstände. Für die vollständige zweite Lieferung
sind der Gesamtpatch und die oben geordnete `series` maßgeblich.
Die erste Veröffentlichung dieser Lieferung wurde anschließend vollständig
zurückgelesen: 132 Dateien und 906.084 Bytes stimmen überein.
[Rücklesenachweis](evidence/publication/initial-readback.json).
