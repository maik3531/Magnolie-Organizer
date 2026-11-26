# Fortsetzung der nativen Mac-Verifikation

Stand: 26. November 2026. Zugeordnet zu #121, #783, #785, #786 und dem
konkreten nativen Compilerbefund #788, Runtimebefund #789 und Prüftreiberbefund #793. Der
plattformübergreifende Quellarchivbefund #787 wird separat korrigiert.

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
| Minimum OS der Mach-O-Dateien | 12.7 |
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

Anschließend laufen die CoreTests aus dem Standalone-Quellarchiv. Der gesamte
Windows-Paketlauf ist dadurch noch nicht als erfolgreich belegt. Die
Python-Prüfungen sind ebenfalls kein vollständiger Debian-/RPM-Bau oder
Installationsnachweis.

## Neue Issue-Belege der Fortsetzung

Die drei gezielten Folgekommentare wurden veröffentlicht beziehungsweise
fortgeschrieben und jeweils mit identischem vollständigem Text zurückgelesen:

- [#787: Desktop-Archivkorrektur und nativer Windows-Regressionserfolg](https://github.com/maik3531/Magnolie-Organizer/issues/787#issuecomment-7187382569)
- [#788: native Bestätigung der beiden Swift-Compilerfixes](https://github.com/maik3531/Magnolie-Organizer/issues/788#issuecomment-7187382083)
- [#789: privater Runtimefix, Tests und genaue native Folgeprüfung](https://github.com/maik3531/Magnolie-Organizer/issues/789#issuecomment-7188020232)

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
