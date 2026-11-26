# Fortsetzung der nativen Mac-Verifikation

Stand: 26. November 2026. Zugeordnet zu #121, #783, #785, #786 und dem
konkreten nativen Compilerbefund #788, Runtimebefund #789, Prüftreiberbefund #793
und den tatsächlichen Host-/Swift-Folgebefunden #796/#797 sowie dem
App-Signaturbefund #802. Der
plattformübergreifende Quellarchivbefund #787 wird separat korrigiert.

## Veröffentlichte Korrekturfolge und aktueller Prüfstand

Der abgeschlossene native [Lauf #97 / 45807249788](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45807249788)
bestätigt genau `215d89029df02df2dce78f35412785ec9f9b36d8` mit dem
#802-Helper-Bundle auf ARM64 (`139865644275`) und Intel (`139865643788`).
**Beide Mac-Jobs und der Gesamtworkflow sind erfolgreich.** Bestanden sind
Runtimebau, Host-/Swift-Tests, Helper- und äußere App-Signaturen, der echte
Start-/Speicher-/Beenden-/Wiederöffnungsablauf sowie Entwicklungspaketierung
und Upload. `target=macos` ließ den Tabletjob aus. Der Lauf dauerte
29 Minuten 57 Sekunden und endete am 26. November 2026 um 12:34:46 Uhr
Europe/Berlin. Die vollständige UI-, Monterey-, Konto- und Geräteabnahme
bleibt davon getrennt.

Der davor abgeschlossene [Lauf #95 / 45799895334](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45799895334)
prüfte genau `3c0b4bb410a5ab514e3deae7fb665a692eb436c2` auf ARM64
(`139840088084`) und Intel (`139840088529`). Beide haben alle Host-/Swift-
Prüfungen bestanden und zeigen erst beim äußeren App-Signieren den konkreten
Layoutrest #802. Die endgültige Einordnung steht im eigenen #95-Abschnitt.
Ein späterer reiner Dokumentationscommit ist kein zusätzlich geprüfter
Codecommit.

| Folge | Reviewbarer Commit | Zweck |
| --- | --- | --- |
| #788 | [`bdd1345d`](https://github.com/maik3531/Magnolie-Organizer/commit/bdd1345d3bec68144dbcf627a3ca7bd03073c64b) | Native Swift-Kompilierblocker |
| #787 | [`68926657`](https://github.com/maik3531/Magnolie-Organizer/commit/689266570cda17f463132a182c02d78ea732dfbd) | Enge Belegausschlüsse in Desktop-Quellarchiven |
| #789 | [`cc9dc29a`](https://github.com/maik3531/Magnolie-Organizer/commit/cc9dc29a606658b7937eb7261409564c96f93775) | Geprüfte CPython-Buildlinks und private statische liblzma |
| #793 | [`8c01f75b`](https://github.com/maik3531/Magnolie-Organizer/commit/8c01f75b2ae6a9e753b9c23b0e3c65a7d7826c66) | Kanonisierung unmittelbar eigener Prüftempwurzeln |
| #796 | [`d790d7fc`](https://github.com/maik3531/Magnolie-Organizer/commit/d790d7fc40ddc9f9a0c6869a3378ef53b69f7daa) | Echter Zeitzonenbootstrap im Kommunikationsharness |
| #797 | [`3c0b4bb4`](https://github.com/maik3531/Magnolie-Organizer/commit/3c0b4bb410a5ab514e3deae7fb665a692eb436c2) | Originale Remindertextwerte und genaue Notes-/Faltungstests |
| #802 | [`215d8902`](https://github.com/maik3531/Magnolie-Organizer/commit/215d89029df02df2dce78f35412785ec9f9b36d8) | Eigenes signiertes CPython-Helper-Bundle und isolierter statischer Launcher |

Die Commits bilden eine aufeinander aufbauende Folge auf dem veröffentlichten
Arbeitszweig. Für die Gesamtprüfung gelten die vollständigen Eltern, nicht
ein isolierter letzter Patch. #794 ist ein gesonderter offener Windows-
Cleanupauftrag und enthält in dieser Fortsetzung keinen Produktfix.

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
vorhanden; eine lokale Swift-Ausführung wird nicht behauptet. Der nachstehende
zweite GitHub-Lauf hat die BetaCore-Kompilierung inzwischen auf beiden
Architekturen bestätigt; nachgelagerte XCTest-/App-Abnahme bleibt gesondert.

### Zweiter Lauf: Compilerfix bestätigt, Importruntime-Baurest sichtbar

[Lauf #92 / 45788423617](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45788423617)
prüft den exakten Folgehead `689266570cda17f463132a182c02d78ea732dfbd`.
Er enthält den #788-Compilercommit
`bdd1345d3bec68144dbcf627a3ca7bd03073c64b` und den getrennten
#787-Archivcommit. Die Jobs sind `139801027926` (ARM64) und `139801028506`
(Intel). Beide haben Quellbindung, Abhängigkeiten, Kataloge und den vorher
roten Swift-/Zeitzonen-Referenzschritt bestanden. Damit sind die zwei
#788-Kompilierblocker tatsächlich auf beiden Architekturen überwunden.

Die nachfolgenden ARM64- und Intel-Bauten haben die gepinnte CPython-Quelle
heruntergeladen, ihren Hash geprüft sowie `configure` und `make` erfolgreich
ausgeführt. Danach scheiterte der Runtimebuilder jeweils an
`ValueError: Linked CPython extension output refused`. Der tatsächliche
native Buildlog beider Architekturen meldet außerdem `checking for lzma.h... no`
und das fehlende Modul `_lzma`. Die erforderliche Modulmenge enthält bereits
`lzma`. Beide Jobs endeten in diesem Schritt mit `failure`; die späteren
XCTest-, Bundle- und App-Smoke-Schritte wurden nicht erreicht. Die sieben
vorangestellten Runtimebuilder-Hosttests bestanden jeweils, deckten diese
beiden tatsächlichen Integrationsfälle aber noch nicht ab.

Dieser konkrete Baurest wird in
[#789](https://github.com/maik3531/Magnolie-Organizer/issues/789) verfolgt:
CPythons reguläre Links aus `build/lib...` auf gleichnamige reguläre Dateien
in seinem eigenen `Modules`-Verzeichnis prüfen und ausschließlich deren Bytes
kopieren; das ausgelieferte Runtimeverzeichnis bleibt symlinkfrei. Den
erforderlichen LZMA-Baustein privat und statisch mit derselben Architektur
und macOS-Untergrenze bauen. Keine Reduzierung der erforderlichen Module
oder Lockerung von Relokation, Signatur, Mach-O- und Dateiinventarprüfung.

Die offiziellen XZ-Quellen wurden vor der Umsetzung konkret verifiziert:

| Eigenschaft | Verifizierter Wert |
| --- | --- |
| Version | XZ Utils / liblzma 5.8.4 |
| Veröffentlichung | 9. September 2026 |
| Quellenarchiv | `xz-5.8.4.tar.xz`, 1.567.192 Bytes |
| SHA-256 | `4ce24038fd4221e0d13bc1a2de7a4db56e90b92b3bf75321f6c14be73f65de4b` |
| Archivinhalt | 655 reguläre Dateien, 49 Verzeichnisse; keine Links, Sondertypen, Pfadausbrüche oder doppelten Namen |
| Bibliothekslizenz | 0BSD, laut `COPYING` und `COPYING.0BSD` der konkreten Quelle |

Primärquellen: [offizielle XZ-Seite](https://tukaani.org/xz/),
[Release v5.8.4 mit Asset-Digest](https://github.com/tukaani-project/xz/releases/tag/v5.8.4),
[CPythons dokumentierte LIBLZMA-Konfiguration](https://docs.python.org/3.15/using/configure.html)
und [CPython 3.15.2 sharedmods-Regel](https://github.com/python/cpython/blob/v3.15.2/Makefile.pre.in).
Ein geprüfter Quelldownload ist noch kein bestandener nativer Runtimebau.

Eine begrenzte echte Bauprobe dieser XZ-Quelle auf Linux hat Configure,
`make -C <build>/src/liblzma -j2` und dessen privates Installationsziel
bestanden. Installiert wurden die statische `liblzma.a`, Header und
Entwicklungsmetadaten; keine CLI-Programme oder Shared Libraries. Die
Option `--disable-tests` existiert in dieser Quelle nicht und wird nicht
verwendet. `--disable-doc` installiert die Lizenztexte nicht; der Mac-Builder
übernimmt deshalb `COPYING` und `COPYING.0BSD` ausdrücklich in sein Inventar.
Dieser Linux-Lauf bestätigt die Baufolge, nicht die Mac-Architektur,
Mindestversion oder Relokation.

### #789: umgesetzte Korrektur und gezielte Regressionen

`ImportPython.json` bindet die zweite Quelle einschließlich Hash, Wurzelname,
Größengrenzen und Lizenzdateien. Beide Archive durchlaufen dieselbe strikte
Quellprüfung. Für XZ ist nur der tatsächlich benötigte HTTPS-Downloadhost
`release-assets.githubusercontent.com` zusätzlich zugelassen; nach jeder
Antwort bleiben Hash- und Größenbindung verpflichtend. CPythons bisherige
URL-Bindung bleibt erhalten.

Der Builder erzeugt nur die statische liblzma-Bibliothek und Header in seinem
temporären Präfix und übergibt CPython deren genaue Pfade. Der vollständige
temporäre Quell-/SDK-Baum wird vor dem Relokationsnachweis entfernt. Für
Extension-Links wird ausschließlich die konkrete CPython-Regel
`../../Modules/<gleicher Dateiname>` zugelassen. Reguläre kopierte Bytes,
beide Lizenztexte und der statische Bibliothekshash werden inventarisiert.

```sh
python3 -B Magnolie-Organizer-macOS-Beta/tests/test_import_python_bundle.py -v
```

Die erweiterte Suite besteht lokal mit **13/13 Tests**. Die sechs zusätzlichen
Tests prüfen tatsächliche Dateisystem-Linkfälle, zweite Quellen-/Download-
Grenzen und die Zusammensetzung des Builders mit kontrollierten Compiler-
Ausgaben. Fremde/absolute/umbenannte/defekte/verkettete Links, ausgetauschte
Verzeichnisse, Shared-Library-Ausgaben, verlinkte Header und Nichtarchive
werden abgewiesen. Die Orchestrierungsprüfung bestätigt gemeinsame Apple-
Flags, die exakten statischen Linkpfade, kopierte Lizenzen und Entfernung der
Quellverzeichnisse vor der Relokation. Sie simuliert Compiler-/Apple-Werkzeuge
ausdrücklich und ist selbst kein nativer Mac-Baunachweis.

Ein unabhängiger Review hat die Korrektur mit CPythons tatsächlichen
`configure.ac`-/`Makefile.pre.in`-Regeln und der echten XZ-Bauprobe abgeglichen;
kein blockierender Befund. Die bestehende native Workflow-Schnittstelle bleibt
kompatibel. Der tatsächliche Mac-Folgelauf dieses Korrekturstands unter
[#93 / 45791918626](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45791918626)
prüft genau den veröffentlichten Commit
`cc9dc29a606658b7937eb7261409564c96f93775`; ARM64-Job `139812810788`, Intel-Job
`139812811365`. **Beide Architekturen haben den tatsächlichen Runtime-Schritt
bestanden.** Die gesicherten Runtime-Manifeste bestätigen jeweils:

| Nachweis | ARM64 und Intel |
| --- | --- |
| Interpreter | CPython 3.15.2, jeweilige native Architektur |
| Isolierter Start / erforderlicher Modulabschluss | Bestanden, einschließlich `lzma` nach Entfernen der Bauquelle |
| Inventar | Je 704 Dateien und 52 geprüfte Mach-O-Dateien |
| Deklariertes Mach-O-Deploymentziel | 12.7; keine Laufzeitabnahme auf macOS 12.7 |
| Dynamische Abhängigkeiten | Nur zulässige Apple-Systembibliotheken |
| `_lzma` | Nur `/usr/lib/libSystem.B.dylib`; private liblzma 5.8.4 statisch eingebunden |
| XZ-Lizenzdateien | Beide vorhanden, mit den originalen Quellhashes inventarisiert |
| Native UI validiert | Nein; gesonderter späterer Schritt |

Die je 13 Runtimebuildertests bestanden auch auf den beiden echten Mac-Hosts.
Quellbindung und beide Zeitzonenreferenzphasen waren ebenfalls erfolgreich.
Die Jobs scheiterten erst im nachfolgenden Host-/Apple-Prüfschritt an dem
nachstehend getrennten Testpfadbefund. Die komplette App-Abnahme wurde
dadurch noch nicht erreicht.

## #793: eigene temporäre Prüfwurzeln auf macOS

Im Setup von `tests/test_import_helper.py` ruft der Treiber
`project_snapshot` mit einer selbst erzeugten temporären Wurzel auf. Die
strikte Funktion `safe_path` prüft auch alle Eltern und weist den macOS-
Temppfad über `/var` zurück, weil er über den Systemalias `/private/var`
führt. Beide tatsächlichen Jobs meldeten
`ValueError: Symlinked projection path refused`; es wurden in dieser Suite
**0 Tests** ausgeführt. XCTest, Bundlebau, App-Smoke und Paketierung wurden
übersprungen. Der Nachweis ist dem begrenzten Folgeissue
[#793](https://github.com/maik3531/Magnolie-Organizer/issues/793) zugeordnet.

Der Fehler wurde zusätzlich unter Linux mit einem tatsächlich angelegten
Elternsymlink und einer darunter selbst erzeugten `TemporaryDirectory`
reproduziert. Die Korrektur betrifft ausschließlich unmittelbar selbst
erzeugte temporäre Wurzeln der Prüftreiber. Rootlinks und Nichtverzeichnisse
werden zuerst abgewiesen; anschließend wird die eigene Wurzel kanonisiert,
bevor Unterpfade erzeugt werden. `safe_path`, Benutzerargumente, allgemeine
Projektions-/Quellpfade und die Ablehnung innerer Links bleiben unverändert.

Die gemeinsame Funktion `canonical_temporary_root` wird nur an den frisch
selbst angelegten Tempwurzeln der zehn betroffenen Check-Runner,
`project_ui.verify`, der `ProjectionTests` und `ImportHelperTests` eingesetzt.
Der Produktionspfad `safe_path` bleibt textgleich. Die drei gezielten
`ProjectionPathTests` bestehen lokal, auch mit dem Tempstamm selbst unter
einem echten Elternsymlink. Sie zeigen den vorherigen Fehler, danach echte
Dateiprojektion und Verifikation sowie die unveränderte Ablehnung von
Root-, Verzeichnis-, Datei- und defekten Links. Alle 14 geänderten Python-
Dateien wurden syntaktisch geparst; die Diffprüfung bestand.

```sh
python3 -B Magnolie-Organizer-macOS-Beta/tests/test_import_helper.py ProjectionPathTests
```

Die vollständigen ImportHelper-/Hostgruppen wurden auf diesem Linux-
Arbeitsplatz wegen fehlender gettext-/Parserabhängigkeiten nicht erneut
ausgeführt. Der anschließende native Folgelauf enthält diese unveränderten
Prüfungen und bleibt für ihren aktuellen Erfolg maßgeblich.

## Lauf #94: Pfadfix bestätigt, vollständige Swift-Folgebefunde

[Lauf #94 / 45794303684](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45794303684)
prüfte genau `8c01f75b2ae6a9e753b9c23b0e3c65a7d7826c66`, ARM64-Job
`139820902702`, Intel-Job `139820902276`. Beide Architekturen haben erneut
Zeitzonenreferenzen, 13 Runtimebuildertests und den privaten Runtimebau
bestanden. Danach bestanden die zuvor blockierten **17 ImportHelper- und
Pfadtests** tatsächlich: 71,581 Sekunden auf ARM64, 103,606 Sekunden auf Intel.
Dies bestätigt #793 nativ. Die 14 Parsergruppen enthalten die originalen
27 OR6-Fixtures; die drei Pfadtests sind darin getrennte zusätzliche Gruppen.

Freeze, frische UI-Projektion, aktueller Quellabgleich und **90 OR6→UI-
Prüfungen** bestanden ebenfalls. Der UI-Transport bleibt dabei synthetisch;
die tatsächliche Python-Helferlaufzeit wurde dagegen nativ ausgeführt.
Der Quellabgleich meldet 27 Assertions, 30 gemeinsame Suchfälle und 181
nicht angebundene Desktopbefehle. Diese Umfänge überlappen und werden nicht
addiert. Die Kryptoreferenzen entsprechen dem aktuellen gemeinsamen Codec.

Der nachfolgende Hostlauf führte je 35 Tests aus: 571,514 Sekunden auf ARM64
und 736,119 Sekunden auf Intel, jeweils vier Fehlerergebnisse und ein Skip.
Ein fehlerhaftes Verfahren in der Kommunikationsprüfung sowie drei
wiederholte Swift-Gesamtläufe erklären diese vier Ergebnisse. Die
Swift-Suiten kompilierten vollständig und führten jeweils **498 Tests** aus;
je nach Kontext blieben vier beziehungsweise fünf bewusst bedingte Skips.
Dieselben fünf Fehlassertionen liegen in genau drei Testfällen. Wiederholte
Ausführung wird nicht als zusätzliche unabhängige Fehlerzahl gezählt.
App-Bundlebau, der separate App-Smoke-Schritt und Paketierung wurden wegen
des Hostfehlschlags noch nicht erreicht.

### #796: Kommunikationsprüfer aus einem frischen Checkout

Der erste tatsächliche Kommunikationsfehler ist
`ReferenceError: MagnolieTime is not defined`. Der Rohcheckout deklariert
`normative-timezones.js`, enthält diese erzeugte Datei aber noch nicht.
Der Prüfer übersprang sie und rief anschließend abhängige UI-Funktionen auf.

Der Folgefix verwendet ausschließlich für den Standardaufruf ohne
Webpfadargument den vorhandenen gemeinsamen Zeitzonengenerator samt
Payload-/Provenienz-/Lizenzprüfung. Ein ausdrücklich übergebener Webpfad
muss seinen eigenen Bootstrap enthalten, auch wenn er zufällig derselbe
kanonische Quellpfad ist. Scriptreihenfolge und Pflichtskripte werden geprüft.

Der ursprüngliche Fehler ist lokal reproduziert. Danach bestehen **15/15
Kommunikationspayloads** gegen die bytegleiche historische Fixture. Ein
separat übergebener Originalwebpfad mit echtem Bootstrap besteht ebenfalls;
fehlender Bootstrap und falsche Reihenfolge werden gezielt abgewiesen.
Die zusätzliche Hostregression entfernt den Bootstrap nur aus der eigenen
temporären Projektion und verlangt einen Fehler. Beide historischen
Kommunikations-/Telefonfixtures bleiben unverändert. Der zunächst als
möglich betrachtete Unterschied leerer Adressfelder wurde durch den
tatsächlichen Lauf widerlegt; es wurde keine Golden-Datei angepasst.

Lokal: Node 24.22.3, jsdom 26.1.0 isoliert aus vorhandenem npm-Cache, keine
vollständige zweite Hostumgebung. Der neunteilige projizierte Telefonpfad
und die neue integrierte Negativprüfung sind im nachstehend dokumentierten
Lauf #95 auf beiden Architekturen bestanden. Der konkrete Folgeauftrag ist
[#796](https://github.com/maik3531/Magnolie-Organizer/issues/796).

### #797: drei konkrete Text-/Testfälle der nativen Swift-Suite

| Fall | Tatsächliche Ursache und enger Fix |
| --- | --- |
| Geschützte Apple-Notes-Bodies | Der Test verwechselte die erlaubte Reason-ID `apple-note-plaintext-unavailable` mit einem Bodyfeld. Er prüft nun die serialisierte Objektstruktur, genau einen Ausschluss, erlaubte Schlüssel/Reasons und leere Vorschlagsnotizen. Produktpolicy und tatsächliche Bodyablehnung bleiben unverändert. |
| UTF-8-Kalenderfaltung | Die Fortsetzungszeile beginnt mit `20 CC 81`. `String.dropFirst()` entfernte das Leerzeichen und die kombinierende Marke als einen Character, wodurch der Test aus 572 Bytes fälschlich 570 machte. Der Test entfernt nun exakt das ASCII-Faltungsbyte. Produktfaltung und 75-Oktett-Grenze bleiben unverändert; vier direkte Grenzfixtures ergänzen den Roundtrip. |
| Erinnerungstitel mit führendem U+FEFF | Die Editorprüfung kennt FEFF bereits. Ihre bisherige Snapshotkopie las jedoch JSON erneut über Darwin-Foundation ein; dort ist der Verlust dieses Zeichens innerhalb von Stringwerten dokumentiert. Die vorhandene begrenzte Validierung erzeugt nun zugleich eine native Wertkopie vor der Editorprüfung. |

Die Reminderkopie baut Dictionaries und Arrays neu auf und materialisiert
Text aus dessen UTF-8-Bytes. String- und Schlüsselbudgets werden vor zusätzlicher
Kopie beziehungsweise Kindrekursion geprüft. Zahlen-/Booltypen, Finitheit,
Feld-/Array-/Knoten-/Tiefenlimits und die 16-MiB-Grenze bleiben erhalten;
Evidence- und Revisionformat ändern sich nicht. Die neuen Regressionen
prüfen FEFF-Ausschluss, Originaltitelbytes, unterschiedliche Revisionen und
Isolation gegenüber nachträglichen Änderungen von `NSMutableString` und
`NSMutableArray`, zusätzlich zum bestehenden Dictionaryfall. CRLF-/CR-/
NUL-/DEL- und Editorregeln bleiben unverändert streng.

Quellen für die gezielte Einordnung:
[RFC 5545, Abschnitt 3.1](https://www.rfc-editor.org/rfc/rfc5545.html#section-3.1)
und [swift-foundation #300](https://github.com/swiftlang/swift-foundation/issues/300).
Der [Folgeauftrag #797](https://github.com/maik3531/Magnolie-Organizer/issues/797)
unterscheidet die zwei Testkorrekturen vom Reminder-Produktfix. Ein
unabhängiger Review fand nach enger Budgetkorrektur keinen verbleibenden
Quellbefund. Lokal fehlt Swift; Lauf #95 hat die Änderungen anschließend
auf beiden Architekturen nativ bestätigt.
Dies ist keine pauschale Erledigung der übrigen offenen #511-JSON-Fälle.

## Lauf #95: Host-/Swift-Fixes bestätigt, äußerer App-Signaturrest

[Lauf #95 / 45799895334](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45799895334)
prüft genau `3c0b4bb410a5ab514e3deae7fb665a692eb436c2`.
Die abgeschlossenen Jobs `139840088084` (ARM64) und `139840088529` (Intel)
bestätigen die neuen #796/#797-Korrekturen tatsächlich:

- Die 17 ImportHelper-/Pfadtests bestehen auf beiden Architekturen
  (ARM64: 69,452 Sekunden).
- Die aktuelle Projektion, 90 OR6→UI-Prüfungen und Kryptoreferenzen bestehen.
- Der Kommunikations-Hosttest besteht einschließlich 15 Standardpayloads,
  neun projizierten Telefonfällen und der integrierten fehlenden Bootstrapdatei.
- Der gesamte Hostlauf endet mit **35 Tests, 0 Fehlern und 1 Skip** in
  594,947 Sekunden auf ARM64 beziehungsweise 800,281 Sekunden auf Intel.
- Die vier Swift-Gesamtläufe (Kalender, Editor UTC, Editor Berlin, Bundlebau)
  führen jeweils **501 Tests ohne Fehler** aus. Sie weisen der Reihe nach
  **4 / 5 / 5 / 6 Skips** aus. Die doppelten Suite-/All-tests-Endzeilen und
  die wiederholten Läufe werden nicht addiert.
- Geschützte Notes-Bodies, exakte lange Faltungszeile, neue direkte
  Faltungsgrenzen, führender FEFF-Titel samt Revisionbindung und mutable
  Text-/Arrayisolation sind ausdrücklich als bestanden protokolliert.

Der [dauerhafte maschinenlesbare #95-Beleg](verification/native-run-95.json)
enthält die Quellbindungen, getrennten Testkontexte und Skips, Log- und
Artefakthashes, beobachteten Umgebungen sowie die genaue Signaturgrenze.
Die CI-Artefakte sind für 14 Tage konfiguriert; diese Zusammenfassung bewahrt
ihre erfassten Ergebnisse und Prüfsummen, ersetzt aber keine App-Abnahme.

Der App-Code kompiliert anschließend. Nach dem Einbau der ebenfalls geprüften
privaten Laufzeit scheitert erst die äußere Signatur:

```text
code object is not signed at all
In subcomponent: ...app/Contents/Helpers/ImportPython/runtime.json
```

Intel meldet an derselben Grenze stattdessen
`Contents/Helpers/ImportPython/LICENSE-XZ-Utils.txt`. Damit ist der gemischte
Code-/Datenbaum als gemeinsame Ursache belegt, kein JSON-Einzelfall.

`codesign --force --sign - <app>` endet mit Exit 1. Der separate App-Smoke und
die Entwicklungspaketierung werden dadurch noch nicht erreicht. Ein fertiges
App-Paket oder erfolgreicher Start wird aus diesem Lauf nicht abgeleitet.

### #802: Code und Ressourcen der privaten Laufzeit trennen

Der gemischte Unix-Präfix unter `Contents/Helpers/ImportPython` enthält neben
Mach-O-Code auch Pythondateien, JSON und Lizenzen. Apple reserviert diesen
Bereich für eingebetteten Code; die gemeldete JSON-Datei ist nur das erste
unzulässige Datenobjekt. Die bisherige Reihenfolge, innere Programme vor der
äußeren App zu signieren, ist bereits richtig.

Der [Folgeauftrag #802](https://github.com/maik3531/Magnolie-Organizer/issues/802)
verwendet ein echtes internes `ImportPython.app`: Interpreter unter
`Contents/MacOS`, direkt ladbare Mach-O-Erweiterungen unter `Contents/PlugIns`,
Standardbibliothek und Lizenzen unter `Contents/Resources` und Bundlemetadaten
in `Contents/Info.plist`. Der statische Python-Kern bleibt erhalten; ein
begrenzter PyConfig-Startpfad setzt ausschließlich bundleinterne Suchpfade.
Eine pauschale Verlagerung aller Programme in Resources oder eine rekursive
Neusignierung ersetzt diese strukturelle Korrektur nicht.

Das SDK-Inventar `runtime.json` bleibt außerhalb des fertig signierten
Helper-Bundles. Es wird erst danach einschließlich `_CodeSignature`-Dateien
erstellt und beim Einbau unter den Ressourcen der äußeren App abgelegt.
Damit entsteht keine zyklische Abhängigkeit zwischen eigener Signatur und
Dateihashes. Vollständige Inventur, Symlinkverbote, isolierter Start,
Modulabschluss, Architekturen, Deploymentziel, Systembibliotheksgrenzen und
strikte abschließende Signaturverifikation bleiben Abnahmekriterien.

Die erweiterte Runtime-Hostsuite besteht mit **21/21 Tests**. Reale temporäre
Dateibäume prüfen falsche Layouts, Mach-O-Typen, versteckten Code in Ressourcen,
Signaturinventur, fehlende oder veränderte Dateien und Bitänderungen beim
Kopieren. Die Orchestrierungsprüfung simuliert Apple-Werkzeuge ausdrücklich;
sie bestätigt die Reihenfolge und finale Byteinventur, keine echte Signatur.

Eine begrenzte lokale C/API-Probe mit CPython 3.12 und einem Linux-Ersatz für
die Apple-Executable-Abfrage prüfte sieben Argument-/Exit-/Pfad-/Isolations-
Szenarien. Eine zusätzlich konkret geprüfte Doppelpunkt-Pfadgrenze zeigte,
dass ein gesetztes CPython-`home` den Pfad am Doppelpunkt aufteilt. Der finale
Launcher setzt deshalb ausschließlich alle expliziten öffentlichen Pfad-
Ausgabefelder; die gezielte Vorher-/Nachher-Probe bestätigt die vollständigen
Prefixe und internen Suchpfade. Die finale Launcherquelle hat SHA-256
`4c9591d11ac184208ad6b5cb5cc087a9e076c4784745ac82f38256145bf02d3e`.
Diese lokalen API-Belege betreffen weder Darwin noch den statischen
CPython-3.15-Bau. Die neue C-Datei, der unveränderte ursprüngliche
CPython-Bauinterpreter und das zusätzliche originale Make-Linkrezept wurden
unabhängig geprüft; kein verbleibender Quellreviewblocker.

Primärquellen: [Apple: Bundle-Inhalte](https://developer.apple.com/documentation/bundleresources/placing-content-in-a-bundle),
[Apple: fremde Codestrukturen einbetten](https://developer.apple.com/documentation/xcode/embedding-nonstandard-code-structures-in-a-bundle)
und [Apple: verschachtelten Code signieren](https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/Procedures/Procedures.html)
sowie [CPython 3.15: öffentliche Initialisierungskonfiguration](https://docs.python.org/3.15/c-api/init_config.html).
Der neue Layoutstand wurde im eigenen tatsächlichen ARM64-/Intel-Lauf #97
geprüft. Dessen nachstehende native Ergebnisse ersetzen die vorherige
Beschränkung auf Quellreview und simulierte Apple-Werkzeuge.

## Lauf #97: tatsächliche Helper- und App-Abnahme

[Lauf #97 / 45807249788](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45807249788)
verwendet genau `215d89029df02df2dce78f35412785ec9f9b36d8`.
Der ARM64-Job `139865644275` und der Intel-Job `139865643788` sind
erfolgreich abgeschlossen. Der Gesamtstatus `completed/success` wurde
zusätzlich unmittelbar über die GitHub-API und die Laufübersicht bestätigt.

| Prüfstufe | ARM64 | Intel |
| --- | --- | --- |
| Nativer Zeitzonenvergleich und aktueller Quellstand | Bestanden | Bestanden |
| Neue private Laufzeit: Bau, Helper-Signatur, Relokation | Bestanden | Bestanden |
| Runtimebuilder-Regressionen | 21 Tests, 0 Fehler | 21 Tests, 0 Fehler |
| ImportHelper-/Pfadprüfungen | 17 Tests, 0 Fehler | 17 Tests, 0 Fehler |
| Hostsuite | 35 Tests, 0 Fehler, 1 Linux-spezifischer Skip | 35 Tests, 0 Fehler, 1 Linux-spezifischer Skip |
| Vier Swift-Kontexte | Je 501 Fälle, 0 Fehler; 4/5/5/6 Skips | Je 501 Fälle, 0 Fehler; 4/5/5/6 Skips |
| Debug-Appbau und äußere App-Signatur | Bestanden | Bestanden |
| Tatsächlicher Start, Speichern, Beenden, Wiederöffnen | Bestanden | Bestanden |
| Entwicklungspaket und CI-Upload | Bestanden | Bestanden |

Auch hier sind die wiederholten Swift-Kontexte keine zusätzlichen einzigartigen
Tests. Die kleineren Prüfgruppen überschneiden sich mit der Hostsuite und
werden nicht zu einer künstlichen Gesamtsumme addiert.

### Tatsächlicher Bundle-Lebenszyklus

Die heruntergeladenen `bundle-smoke.json` beider Architekturen bestätigen alle sieben
verpflichtenden Booleans als `true`: `bundleLaunch`,
`pidBoundVisibleWindow`, `normalQuit`, `freshNormalizedProfileSaved`,
`reopen`, `reopenedProfileAtomicallySaved` und `profileDataPreserved`.
Das ist ein echter Start der gebauten `.app` über LaunchServices mit einem
prozessgebundenen sichtbaren Fenster. Der Prüfer verlangt das reguläre
Save-before-quit, ein normalisiertes frisches Profil, das zweite Öffnen und
einen erneuten atomaren Speicherabschluss mit anderer Dateiinode und
semantisch erhaltenen Profildaten. Die Dateirechte werden ebenfalls geprüft.

Der erste und wiedergeöffnete Profilinhalt sind jeweils bytegleich:

- ARM64: `0e18503bbc173cb3a661ccd6fc0c1cd7838cee9c623132902b6699268f9adb24`
- Intel: `5a3fff7e4c5e34e26593e9db4005b656ecec71f8a935e22984e1b93acfe5281c`

Beide tatsächlichen Bildschirmaufnahmen wurden angesehen: sichtbarer
gerenderter Organizer-Einband, Datumszeile, Schaltflächen und Beta-
Statusbereich. Die bestehenden Hinweise zu noch nicht implementierten
Desktopbefehlen sind ebenfalls sichtbar (`telefon_stand` auf ARM64,
`update_pruefen` auf Intel; dort zusätzlich der Hinweis zu Erinnerungen
nur bei geöffneter/entsperrter App). Die Bilder belegen den Startbildschirm,
keine Bedienung von Editor, Dateiauswahl, Import, Systemkonten oder Geräten.

### Tatsächlicher Quell- und Runtimebeleg

Beide `sources.json` sind bytegleich und binden Port- sowie Desktopquellen an
den tatsächlichen Testcommit. Ihr SHA-256 ist
`6cbb85bcdc2ab56739c605ca9c470404a890e77af9046a7ecbecf46a59f717fc`.
Die vollständige Inventur von 3.910 Dateien wurde unabhängig gegen die
Git-Objekte dieses Commits geprüft; spätere lokale Berichtsänderungen wurden
dabei nicht verwendet.

Beide nativen Runtime-Manifeste haben Schema 2, die jeweilige Architektur,
706 inventarisierte Helperdateien einschließlich `Info.plist` und
`CodeResources` sowie 52 Mach-O-Dateien. Der endgültige Launcher-Quellhash
stimmt. `bundleLayout`, `executableBound`, `isolated` und `moduleClosure`
sind jeweils `true`; CPython 3.15.2 läuft nach Entfernen der Bauquelle mit
internen Pfaden. Alle erfassten Mach-O-Mindestversionen sind 12.7 und die
dynamischen Abhängigkeiten bleiben auf Apple-Systembibliotheken beschränkt.

Die frühen Umgebungsdateien sind Voraussetzungenaufnahmen vor den Tests.
Ihr ursprüngliches `nativeMagnolieTestsExecuted=false` wird nicht umgedeutet:
Die nachfolgenden Testlogs und Smoke-Belege weisen die spätere Ausführung
gesondert nach. Beobachtete Systeme: ARM64 macOS 15.8.2 / Build 24H232 und
Intel macOS 15.7.9 / Build 24G830; beide SDK 15.5 und Apple Swift 6.1.2.

### Heruntergeladene Entwicklungskandidaten und unabhängiger Byteabgleich

Beide äußeren CI-Artefakte wurden heruntergeladen und gegen Größe und
GitHub-Digest geprüft. Die enthaltenen eigentlichen App-ZIPs stimmen jeweils
mit ihrer `SHA256SUMS` überein:

| Architektur | CI-Artefakt | Äußere ZIP-Bytes | Inneres App-ZIP: Bytes / SHA-256 |
| --- | --- | ---: | --- |
| ARM64 | [15112160240](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45807249788/artifacts/15112160240) | 24.622.479 | 23.985.094 / `4c79ed1c2272f02d403ad07887f5e24948ab41ceaa2a7ebfea60024fcff181a0` |
| Intel | [15114016468](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45807249788/artifacts/15114016468) | 25.444.840 | 24.198.307 / `0ee0ab9fca6ec2aa58b5427a47f44c4007f0f4ee9147b1d7870f229ddddc6ade` |

Die äußeren SHA-256-Digests sind auf ARM64
`05ae0dda0d82ce7f36da050bc93d4ae2f15b444c693b24548584e3ac2ba78af9`
und auf Intel
`d6a46d5cce35369dc1a53d2561e8ff67b0b5577bedd7b13ad3b77fecc64624bb`.
Die 14-tägige CI-Aufbewahrung endet laut GitHub am 10. Dezember 2026 um
12:24:04 Uhr beziehungsweise 12:34:37 Uhr Europe/Berlin. Dies sind temporäre
Entwicklungsartefakte und keine veröffentlichten Releases.

Ein zusätzlicher unabhängiger Byteaudit bestand für jedes Paket mit
43 Prüfungen ohne Abweichung. Er prüfte die tatsächlichen Archivmitglieder,
eindeutige sichere Pfade, Source-/Freeze-/Build-Konsistenz, 534 versionierte
Projektionsinputs gegen Git, 19 erzeugte Sprachkataloge, den gebundenen
phonenumbers-Wheelhash und alle 1.312 gepackten Projektionsoutputs. Die
bewusste Verschiebung des ImportHelper-Verzeichnisses aus UI in die
nativen Ressourcen wurde dabei berücksichtigt.

Die 706 fertig signierten Runtime-Dateien stimmen jeweils bytegenau mit
dem Inventar überein. Hauptprogramm, Python-Executable und die 51
Mach-O-Bundle-Plugins haben tatsächlich die jeweilige CPU-Architektur.
Der äußere `CodeResources` enthält genau den verschachtelten Helperverweis;
der Helper referenziert alle 51 Plugins. Je 1.967 aufgeführte Ressourcen-
Hashes passen zu den tatsächlichen Bytes. Der Linux-Byteaudit führt
`codesign` oder die App nicht erneut aus: Die native Signaturgültigkeit
und Ausführung stammen aus dem erfolgreichen Mac-Lauf.

Der [dauerhafte maschinenlesbare #97-Beleg](verification/native-run-97.json)
bewahrt diese Ergebnisse, genaue Testkontexte, Profil- und Artefakthashes,
Run-/Job-/Artefaktlinks sowie die getrennten Byteaudit- und Sichtprüfungen.
Die ausführlichen ursprünglichen CI-Logs und Paketbytes bleiben eigenständige
Quellen; ein nachfolgender reiner Berichtscommit ändert den getesteten
Produktstand `215d89029df02df2dce78f35412785ec9f9b36d8` nicht.

### Grenzen des neuen Erfolgs

Der Kandidat ist ein ad-hoc signierter Debug-/Entwicklungsbau. Die vorhandenen
Angaben `nativeAcceptance=false`, `nativeUIValidated=false`,
`montereyRuntimeValidated=false` und `productionRelease=false` behalten ihre
jeweilige Bedeutung. Die echten Mac-Runner verwenden macOS 15; die in Mach-O
deklarierten 12.7 sind kein Lauf auf Monterey. Apple-Konten, TCC-Freigaben,
Gerätegegenstellen und vollständige produktive UI-Abläufe wurden damit
weiterhin nicht abgenommen.

## #787: bestätigte Auswirkung auf Desktop-Quellarchive

Der [Windows-Lauf 45782763765](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45782763765)
auf dem übernommenen Head scheiterte in `Release.Common.ps1` bereits an der
Vertragsauswahl. Der ursprüngliche Python-Aufruf `sync_contracts()` wurde
zusätzlich auf den tatsächlichen aktuellen Verträgen geprüft und scheiterte
ebenfalls. Die rekursive Auswahl erfasste Mac-Patches, Git-Bundle und Logs,
obwohl für Produktverträge nur JSON/Markdown vorgesehen sind.

Der Folgepatch schließt in der Windows-Auswahl und den beiden bytegleichen
Python-Selektoren ausschließlich diese direkten Belegverzeichnisse aus:

- `contracts/macos-issue-publication-2026-11-26/`
- `contracts/macos-verification-2026-11-26/`

Die vorhandene dynamische Aufnahme neuer regulärer Verträge bleibt erhalten.
Ähnliche/nachgeordnete Namen, andere Datumssuffixe und sonstige unerwartete
Dateitypen erhalten keine Ausnahme. Ein Symlink beziehungsweise Junction an
der Ausschlussgrenze wird vor dem Überspringen abgewiesen. Fehlende oder
beschädigte Pflichtverträge und nachträglich ins ZIP eingeschleuste Belege
bleiben Fehler.

Tatsächlicher lokaler Nachweis:

```sh
python3 -B magnolie-organizer/pruefungen/test_contract_evidence.py -v
```

Vor der Korrektur reproduzierten die gemeinsame und eigenständige Variante
den Fehler. Danach bestanden **7/7 Tests**. Eine zusätzliche isolierte
Projektion der tatsächlichen Vertragsmenge bestätigte **138/138 Dateien**
mit identischen Bytes und Modi sowie den kanonischen und eigenständigen
Projektionsabgleich. Die Selektorkopien sind bytegleich. Ein unabhängiger
Diffreview fand keinen blockierenden Befund.

`magnolie-organizer-windows/tests/release-packaging.ps1` enthält die nativen
Windows-Regressionen einschließlich Junction und ZIP-Injektion. Mangels
PowerShell auf diesem Linux-Arbeitsplatz wurde dieser Teil hier nicht lokal
ausgeführt. Der tatsächliche [Windows-Folgelauf 45788221321](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45788221321)
auf `689266570cda17f463132a182c02d78ea732dfbd` hat ihn inzwischen bestanden.
Das [Live-Log, Job 139800326781 / Schritt 9 / Zeile 33](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45788221321/job/139800326781#step:9:34)
meldet ausdrücklich:

```text
Windows source, private-path, new-fixture, provenance and flat-checksum fixtures passed.
```

Der anschließende CoreTestlauf aus dem Standalone-Quellarchiv endete mit
**551/552 bestandenen Gruppen**. Die Gruppe
`Media support draft / original Windows WLAN reader and withdrawal` scheitert
beim Löschen ihrer eigenen `phone.db` in
`PhoneCameraParentTests.Fixture.Dispose()`; der Dateipfad ist noch geöffnet.
Der gesonderte Folgeauftrag [#794](https://github.com/maik3531/Magnolie-Organizer/issues/794)
ordnet den Befund zu #505/#506 ein. Ein zusätzlicher eigener SQLite-Pool für
`Mode=ReadWrite` ist aufgrund der Quellen eine konkrete, noch nicht gezielt
nativ bestätigte Ursache; ein laufender Reader wird nicht behauptet.

Der Gesamtworkflow endete deshalb mit `failure`; ZIP-/Installerbau und
Artefaktupload wurden übersprungen. Der ursprüngliche #787-Archivblocker
und seine Regression sind dagegen nachweislich behoben. Die Python-Prüfungen
sind ebenfalls kein vollständiger Debian-/RPM-Bau oder Installationsnachweis.

## Neue Issue-Belege der Fortsetzung

Die sieben gezielten Folgekommentare wurden veröffentlicht beziehungsweise
fortgeschrieben und jeweils mit identischem vollständigem Text zurückgelesen:

- [#787: Desktop-Archivkorrektur und nativer Windows-Regressionserfolg](https://github.com/maik3531/Magnolie-Organizer/issues/787#issuecomment-7187382569)
- [#788: native Bestätigung der beiden Swift-Compilerfixes](https://github.com/maik3531/Magnolie-Organizer/issues/788#issuecomment-7187382083)
- [#789: privater Runtimefix, Tests und genaue native Folgeprüfung](https://github.com/maik3531/Magnolie-Organizer/issues/789#issuecomment-7188020232)
- [#793: eigener Tempstamm der Prüftreiber, Regressionen und Mac-Folgeprüfung](https://github.com/maik3531/Magnolie-Organizer/issues/793#issuecomment-7188363385)
- [#796: Kommunikationsbootstrap, unveränderte Fixtures und nativer Folgelauf](https://github.com/maik3531/Magnolie-Organizer/issues/796#issuecomment-7189199517)
- [#797: Reminder-Wertkopie, genaue Swift-Tests und nativer Folgelauf](https://github.com/maik3531/Magnolie-Organizer/issues/797#issuecomment-7189199900)
- [#802: korrektes Helper-Bundle, isolierter Launcher und nativer Folgelauf](https://github.com/maik3531/Magnolie-Organizer/issues/802#issuecomment-7190273542)

Die ursprünglichen 31 Übergabekommentare und deren eingefrorene
Publikationsbelege wurden dabei nicht verändert.

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

Die offenen Implementierungsaufträge sind weiterhin getrennt zu behandeln:

- [#785](https://github.com/maik3531/Magnolie-Organizer/issues/785): Gesamtarchiv,
  macOS-taugliche lokale Quellen und vollständige Bedienung des produktiven
  Datei-/OR6-Imports.
- [#786](https://github.com/maik3531/Magnolie-Organizer/issues/786): weitere
  Abgleichsfelder/Serien, Neuanlagen, Löschungen, automatische Läufe, geführte
  Wiederaufnahme und vollständiger Apple-Notes-Rückabgleich.
- [#511](https://github.com/maik3531/Magnolie-Organizer/issues/511): originale
  Unicode-JSON-Schlüssel und unbekannte Erweiterungen über den gesamten
  nativen Buch-/Speicher-/Exportpfad; die enge Reminderwertkopie erledigt
  diesen Auftrag nicht pauschal.
- [#465](https://github.com/maik3531/Magnolie-Organizer/issues/465): ausdrücklich
  gewählte exakte Reparatur bereits gespeicherter Ausnahme-Duplikate mit
  erhaltenen Referenzen und tatsächlichem Save/Reopen-Nachweis.

Die Issues waren bei der erneuten direkten Abfrage in dieser Fortsetzung
weiterhin offen. Ihre bestehenden ursprünglichen Beschreibungen, späteren
Patchkommentare und Abnahmegrenzen sind gemeinsam zu lesen.
