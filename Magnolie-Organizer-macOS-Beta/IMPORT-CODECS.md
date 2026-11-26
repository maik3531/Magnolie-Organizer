# Aktuelle Dateiimporte auf dem Mac — Refs #785, #121

## Quellumfang und getrennte Zuständigkeiten

Die aktuelle gemeinsame Importseite bot bereits Formate an, für die der Mac-Host
nur einen ICS-Reader besaß. Eine neuere UI-Projektion allein schließt diese Lücke
nicht. Dieser Patch stellt die tatsächlichen aktuellen Desktopparser als einen
lokalen, begrenzten Helper bereit. Die native Dateiauswahl, erneute Prüfung der
ausgewählten Datei, Vorschau, Buchbindung und Speicherquittung gehören zum
getrennten Host-/UI-Anschluss desselben Issues.

| Headerformat | Tatsächlich wiederverwendeter Parser | Dateien und Sammlungen |
| --- | --- | --- |
| `ics` | `import_rohdaten_lesen` → `ics_lesen` | ICS, VCS, LCS; Termine, Jahrestage, VTODO; erhaltene Serien-/Alarm-/VTIMEZONE-Rohfelder |
| `lotus` | `lotus_csv_lesen` oder unverändertes `magnolie_or6.read_or6` | CSV und binäres OR6; die im aktuellen Desktopvertrag unterstützten Sammlungen |
| `vcf` | `vcf_lesen`, bei CSV `lotus_csv_lesen` | vCard 2.1/3.0/4.0 und CSV, strukturierte Kontaktfelder und erhaltene Originalzeilen |
| `claws` | `claws_xml_lesen` oder `ldif_lesen` | Claws-XML, LDIF und LDI |
| `ldif` | dieselbe Desktoproute mit internem Format `claws` | LDIF/LDI, einschließlich der bestehenden Claws-Erkennung |
| `muell` | `muell_import_lesen` | eigene ICS-/CSV-Vorschau; noch kein gespeicherter Müllterminplan |

Die ersten fünf Routen verwenden auch die vorhandene ZIP-Auswahl. Es wird kein
Archiv ins Dateisystem entpackt. Die Desktopgrenzen bleiben erhalten: höchstens
128 Dateieinträge, 16 MiB pro unterstütztem Eintrag, 32 MiB insgesamt und
Kompressionsverhältnis 200. Verschlüsselte Einträge werden abgewiesen. Die
Müllvorschau bleibt ein eigener Vertrag; ihr `muellToken` wird ausschließlich im
Host gebunden und ist kein Helperparameter.

Das Paket enthält keine Magnolie-Notes-Begleitapp, keinen Telefontransport,
keinen KDE-Verbindungsadapter und keine Hintergrundsynchronisation. Der kleine
projizierte Teil aus `magnolie_phone_region.py` verarbeitet ausschließlich
Telefonnummernfelder eines Kontakts. `magnolie_social_profiles.py` erkennt
passive vCard-URL-Metadaten. Beide eröffnen keine Verbindung. Dateien, die etwa
mit KDE Connect oder AirDrop ankommen, können anschließend bewusst ausgewählt
werden. Diese externen Wege werden dadurch weder ersetzt noch ausgeschlossen.

## Eine Parserquelle und eine nachprüfbare Projektion

`tools/project_import_helper.py` liest Python-ASTs, ohne das Desktopprogramm
zu importieren oder auszuführen. `ImportHelper/closure-policy.json` benennt
die geprüften Entrypoints, Definitionen, globalen und lokalen Imports sowie
die wenigen Mac-Kontextadapter. Die aktuelle Auswahl enthält:

- 93 Definitionen aus `magnolie-organizer/bin/magnolie-organizer`;
- 20 Definitionen aus `magnolie_recurrence.py`;
- ausschließlich `normalize` aus `magnolie_phone_region.py`;
- das unveränderte vollständige `magnolie_or6.py` und das reine
  `magnolie_social_profiles.py`.

Die ausgewählten Funktionen werden mit ihren originalen Quellzeilen und
Dekoratoren erzeugt. Eine neue unbekannte globale Abhängigkeit, ein zusätzlicher
Import oder dynamische Codeausführung lässt den Bau scheitern. Codex muss dann
die Ursache prüfen und eine Erweiterung der Closure ausdrücklich im Patch
belegen. Es wird keine ältere Parserfassung still beibehalten.

Der Host übergibt Sprache, konkrete Zeitzone und `homeCountry`. Der Helper liest
keine Linux-Profile, Systemkonten oder Benutzereinstellungen. `file:`-Fotos und
Netz-URLs geben ihm keine Dateiberechtigung. Die vorhandene lokale Fotooption
ist in dieser Route ausgeschaltet; zusätzliche Kontextadapter verweigern
externe Lesezugriffe auch bei einem versehentlichen internen Aufruf.

Die reine Datenbibliothek **phonenumbers 9.0.38** verwendet exakt den vorhandenen
AppImage-Pin aus `magnolie-organizer/werkzeuge/appimage_bauen.sh`:
SHA-256 `f3cbeb1a42bf226060c60fc6277f5431755d325eddc23fbf2c72ef7e156113c6`.
Nur ein expliziter Prepare-Befehl lädt das offizielle Wheel. Es liegt im
ignorierten `.import-dependencies`-Verzeichnis. Inputinventur, Projektion und
installierte App greifen nicht aufs Netz zu. Die Wheelbytes erscheinen im
SourceFreeze unter dem stabilen Namen
`macos-import-dependencies/phonenumbers.whl`; Parsermanifest, entpackte Dateien
und mitgelieferte Apache-Lizenz sind an diese Bytes gebunden.

Die 19 Übersetzungskataloge werden mit dem vorhandenen `po_zu_js.py` und GNU
`msgfmt` aus den tatsächlich erfassten PO-Bytes erzeugt. Deshalb muss `msgfmt`
auch bei Generate/Verify im Baupfad verfügbar sein.

## Zeitzonen

Der Projektor serialisiert die bereits geprüften normativen Daten aus
`port-adapters/timezones/tzdb-2026egtz.json` zurück in TZif v3: **439 vollständige
Regelsätze für 597 Namen**. Es kommt keine neue Zeitzonenarithmetik hinzu.
Historische Typen, Übergänge und der originale POSIX-Footer bleiben erhalten.
Die Payload-, Provenienz- und Lizenzhashes sind dieselben wie im bestehenden
Mac-Port. Ein Rücklesen mit dem vorhandenen `build-tzif.py::parse_tzif` prüft
jeden Regelsatz; die vorhandenen unabhängigen Zeitpunktfixtures werden mit
Python `ZoneInfo` ausgewertet.

Der Helper setzt seinen einzigen TZif-Pfad auf das überprüfte `zones/` im
Bundle. Unbekannte Namen erteilen keinen Zugriff auf Systemdateien oder ein
optional installiertes `tzdata`-Paket. Eingebettete VTIMEZONE-Definitionen
behalten die Priorität des gemeinsamen Parsers.

## Stdio-Protokoll 1

Der native Host startet genau einen Prozess mit `-I -S -B`:
`Contents/Helpers/ImportPython/bin/python3.15`, danach der feste Skriptpfad
`Contents/Resources/ImportHelper/helper.py`. Es gibt keinen Shellaufruf,
keinen wählbaren Interpreter und keinen System-Python-Fallback. Der private
Runtimebau und seine noch erforderliche Mac-Abnahme sind in
[IMPORT-RUNTIME.md](IMPORT-RUNTIME.md) beschrieben.

Stdin enthält eine UTF-8-JSON-Kopfzeile, LF und anschließend unveränderte
Quelldateibytes. Die Kopfzeile hat **genau** diese Felder:

| Feld | Vertrag |
| --- | --- |
| `schema` | Integer `1`, kein Boolean |
| `format` | eines der sechs oben genannten Formate |
| `name` | Anzeigename der ausgewählten Datei, kein Pfad; höchstens 1024 UTF-8-Bytes |
| `language` | aufgelöster Sprachcode mit optionaler Region/Schrift, z.B. `de`, `en-us`, `zh-hant-de`; höchstens 64 Bytes |
| `timeZone` | konkrete gebündelte IANA-Zone; höchstens 128 Bytes, kein `system` |
| `homeCountry` | einer der 249 kanonischen ISO-3166-1-Zweibuchstabencodes; kein leerer Wert |
| `byteLength` | exakte Ganzzahl zwischen 0 und 33.554.432 |
| `sha256` | SHA-256 der folgenden Bytes, 64 kleine Hexzeichen |

Der Helper normalisiert Sprachcodes auf Kleinbuchstaben und Bindestriche. Er
nutzt einen exakt passenden Katalog, danach den Basissprachkatalog und sonst
die englischen Quelltexte. `zh` und `zh-*` verwenden den vorhandenen `zh-cn`-
Katalog, entsprechend `NativeLocalization.ResolveLanguage` des aktuellen
Windowsprogramms. IANA-Aliasse sind zulässig, sofern sie zu den 597 Namen der
gebündelten normativen Registry gehören, beispielsweise `US/Eastern`.

Die Kopfzeile einschließlich LF ist auf **8192 Bytes** begrenzt. Doppelte oder
zusätzliche Felder, nicht endliche JSON-Zahlen, Steuerzeichen, falsche Längen
und falsche Hashes werden abgewiesen. Nach genau `byteLength` Bytes muss EOF
folgen; ein angehängter zweiter Request ist unzulässig. Der Host muss den
Eingabekanal schließen und besitzt einen 60-Sekunden-Watchdog.

Stdout enthält genau eine UTF-8-JSON-Antwort mit abschließendem LF, insgesamt
höchstens **100.663.296 Bytes (96 MiB)**. Die gesamte Antwort wird auf die Grenze
geprüft, bevor sie ausgegeben wird. Bei Erfolg:

```json
{
  "schema": 1,
  "ok": true,
  "format": "lotus",
  "name": "selected.or6",
  "sourceSHA256": "SHA256 der tatsächlich gelesenen Quelldateibytes",
  "parserManifestSHA256": "SHA256 der tatsächlich geprüften manifest.json",
  "result": { "termine": [], "aufgaben": [], "kontakte": [], "notizen": [] }
}
```

Die beiden erläuternden Hashstrings oben stehen für die echten 64-stelligen
Hexwerte. `result` ist die vorhandene Desktopantwort einschließlich ihrer
Zähler, Auslassungen und Berichte; die tatsächlichen Sammlungen hängen vom
Format ab. Ein Fehler liefert `ok: false`, keinen `result` und
`error: {code, message}`. Die Hashfelder sind `null`, solange sie noch nicht
geprüft werden konnten. Die Meldung ist auf 512 Zeichen begrenzt.

Fehlercodes sind `invalid_header`, `unsupported_format`, `input_too_large`,
`input_length`, `input_identity`, `invalid_timezone`, `bundle_invalid`,
`parse_failed` und `output_too_large`. Ein erfolgreich übertragenes
Fehler-Envelope hat Exitcode 0; Prozessabbruch, Timeout, fehlendes EOF oder
fehlende/ungültige Ausgabe bleiben Hostfehler. Der native Host prüft Quellhash
und Manifesthash nochmals. Eine Parserantwort ist noch keine Speicherquittung.

## Nativer Host, gemeinsamer Merge und tatsächliche Speichergrenze

`FileImportHost` löst den vorhandenen `import`-Befehl ab. Die WebView sendet
nur die Formatart und für Mülltermine den bestehenden Vorgangstoken; sie
bestimmt keinen Quelldateipfad und kein auszuführendes Programm. Der Host
wartet auf die aktuelle Buchspeicherung und einen bestätigten
`pre-file-import`-Wiederherstellungspunkt, bevor der native Picker erscheint.
Ein Abbruch löst die vorbereitete Operation wieder auf.

`FileImportProcess.readSelected` öffnet die konkrete Auswahl mit `O_NOFOLLOW`,
prüft eine reguläre Datei und maximal 32 MiB und vergleicht Größe, Identität
sowie Änderungszeiten nach dem Lesen. Der aktuelle Bytehash gehört zur
Operation; eine spätere erneute Dateiauswahl ist ein neuer Import. Sprache,
Heimatland und konkrete normative Zeitzone werden nach dem vorbereitenden
Save erfasst und vor Übergabe des Ergebnisses erneut verglichen.

Der feste Interpreter erhält einen anonymen Standardinput-Deskriptor: Der
temporäre Dateiname wird vor dem ersten Schreiben von Quelldaten entfernt.
Damit kann der Elternprozess den vollständigen begrenzten Request übertragen,
ohne bei einem früh beendeten Kindprozess in einer gefüllten Pipe zu blockieren.
Der Deskriptor hat `FD_CLOEXEC`; nur die ausdrücklich verbundene Standardeingabe
geht an den gestarteten Prozess. Stdout ist auf 96 MiB, Stderr auf 64 KiB
begrenzt. Quellinhalt aus Stderr erscheint nicht in der Fehlermeldung. Nach
60 Sekunden wird nur dieser eigene Prozess beendet; wenn nötig folgt SIGKILL.

`FileImportProtocol` prüft die vollständige Antwort einschließlich
Schema-/Boolean-Typen, Quell- und Parsermanifesthash, bytegenauem Dateinamen,
Format und Sammlungstypen. Ein Fehler-Envelope enthält kein Teilresultat.
Der AppKit-/Foundation-Prozesspfad und seine tatsächliche Deskriptor- und
Zeitlimitwirkung sind ausdrücklich noch in der macOS-VM zu prüfen.

Die echte gemeinsame UI übernimmt Normalisierung, Kontaktvorschau und Merge.
Die Operation bindet das konkrete Buch, seinen vollständigen Ausgangsinhalt
und eine begrenzte Vorschaufrist. Erfolgstexte warten auf die bestehende
dauerhafte Save-ACK-Kette. Fehler nach einer Mutation lassen die vorhandenen
Kopien für erneutes Speichern stehen und melden die fehlende Bestätigung;
sie starten keinen zweiten Import. Der Patch korrigiert dafür auch die
Fehlerweitergabe des asynchronen Kontakt-Snapshot-Callbacks.

Mülltermine sind bewusst anders: Die neue Route übergibt an die bestehende
Vorschau und meldet `handedToPreview: true, saveConfirmed: false`. Erst deren
eigenes Anwenden/Speichern kann eine Übernahme bestätigen. Eine erfolgreiche
Parserantwort oder geöffnete Vorschau gilt nie als gespeicherter Terminplan.

Zehn zusätzliche `FileImportProtocolTests` prüfen die vorbereitete native
Grenze, einschließlich Fremdhash, Unicode-Dateiname, kaputtem Envelope und
unzulässigen Bridgefeldern. Sie sind hier **nicht kompiliert oder ausgeführt**.
Der 90-Prüfungen-OR6-Lauf unten führt dagegen die tatsächlichen Python- und
JavaScriptteile aus. Die gemeinsame native Abnahme ist in
[CLOUD-MAC-TESTING.md](CLOUD-MAC-TESTING.md) beschrieben.

## #465 bleibt im ICS-Anschluss erhalten

Für `ics` ergänzt `calendar_evidence.py` ausschließlich im Callback-Envelope
`icsImportMetadata` und gegebenenfalls `legacyAndroidAliases`. Der Sidecar
bindet den Hash der vollständigen ausgewählten Bytes, auch bei ZIP, an die
Terminzahl, Position, Quelle, Wire-UID und vollständige originale RID-Zeile.
Die kanonische Instanz-UID wird gegen die unveränderte gemeinsame
RID-Serialisierung geprüft; die alte Android-Quote-Kennung wird separat
berechnet. Der vorhandene bekannte Alias aus #465 wird als feste Referenz
geprüft. Kein Alias wird in einen Termin oder in die Quellmetadaten geschrieben.
Der Host muss diese Antwort über den bestehenden nativen #465-Callback führen.

## Belegte Prüfungen und verbleibende Abnahme

Auf dieser **Linux-x86_64-Umgebung** wurden die tatsächlichen isolierten
Pythonprozesse geprüft; sie ist keine nachgewiesene macOS-VM und hat weder
Swift noch das Apple-SDK. Die Helpertests laufen hier mit CPython 3.12.14.
Der native Workflow führt denselben Test mit dem privat gebauten CPython
3.15.2 aus. Dieser zusätzliche native Lauf ist vorbereitet, hier nicht ausgeführt.

`tests/test_import_helper.py` bestand **14 Prüfgruppen** einschließlich aller **27**
ursprünglich mit Organizer 6 erzeugten, hashgebundenen OR6-Dateien, aktueller
Desktop-Goldens, ZIP-Grenzen, Müllvorschau, Sprache/Land, Quell-/EOF-Bindung,
Closure-Drift, beschädigter Abhängigkeiten, Codeänderungen im Bundle und
Datei-/Netz-Fotoverweisen. Die OR6-Ausgaben werden vollständig mit dem aktuellen
Originalparser und bekannten unabhängigen Fixturewerten verglichen.

`tools/check_file_import.py` führt echte OR6-Bytes durch diesen Prozess in die
tatsächlich erzeugte gemeinsame Mac-UI und bestand **90 Prüfungen**. Der Test
bedient die Kontaktvorschau, prüft den Save-ACK, Wiederöffnung, Wiederimport und
Fehlerzustände. Transport-
und Save-Callbacks bleiben dabei synthetisch; daraus folgt kein Beleg für
AppKit-Dateiauswahl oder reale native Persistenz. Die alte Native-Fixture nutzt
`.invalid`, die die gemeinsame UI bewusst ablehnt. Eine weitere Originaldatei
prüft deshalb separat die erhaltene `.test`-Adresse nach bestätigter Speicherung.

```sh
python3 tools/project_import_helper.py --prepare-dependencies
python3 tests/test_import_helper.py
MACOS_BETA_JSDOM=/absolute/path/to/jsdom/lib/api.js \
  python3 tools/check_file_import.py --js-runtime /absolute/path/to/node
```

GNU `msgfmt` muss im `PATH` stehen; die gemeinsamen UI-Kataloge müssen wie im
bestehenden Mac-Bauablauf vorbereitet sein. Für einen vorhandenen privaten
Interpreter setzt Codex `MACOS_BETA_IMPORT_PYTHON` auf dessen absoluten Pfad.

## Präzise offene Folgearbeiten für Codex

**Vollarchiv `.magnolie`:** Der Befehl `gesamtarchiv_waehlen` und die vollständige
Archivtransaktion sind von den oben implementierten Dateicodecs getrennt.
Maßgebliche Quellen sind `gesamtarchiv_lesen_text`/`gesamtarchiv_lesen` und
`gesamtarchiv_lokales_bewahren` im Linuxprogramm sowie
`magnolie-organizer-windows/GesamtarchivService.cs`. Das Format ist ein
schema-/hashgebundenes Gesamtarchiv, gegebenenfalls zusätzlich verschlüsselt;
es darf nicht als gewöhnliche ZIP- oder OR6-Route behandelt werden. Codex muss
einen nativen Picker, Passwort-/Integritätsprüfung, vollständige Vorschau,
Recovery-Checkpoint, Buch-/Generation-Bindung und die bereits vorhandene
Mac-Restore-Transaktion verbinden. Plattformfremde Integrationsgeheimnisse
dürfen daraus keine Berechtigung erhalten. Prüfungen benötigen vollständige
plattformübergreifende Archive, Fotos/Anhänge, unbekannte Felder, falsches
Kennwort, Manipulation, Konflikt, NACK und tatsächliche Wiederöffnung.

**Lokale Evolution-/Thunderbird-Erkennung:** `import_lokal` und Linux
`_import_lokal_arbeit` sind ein anderer Adapter. Linux-Systemdienste und
Profilpfade sind keine Mac-Berechtigung. Codex muss tatsächlich verfügbare
Mac-Quellen und deren konkrete Auswahl prüfen, Leserechte an den ausgewählten
Quellen binden und danach denselben Vorschau-/Speichervertrag verwenden.
Dateiexporte dieser Programme können bereits über die passenden neuen
Dateirouten importiert werden. Es wird keine funktionierende Mac-Profilsuche
behauptet.

**Systemkonto-Synchronisation:** Apple-Kontakte, -Kalender und -Erinnerungen
benötigen einen eigenen, dauerhaft autorisierten Abgleich mit Konflikt- und
Readbackregeln. Weder die neuen Dateiimporte noch die bestehenden Kopierimporte
belegen diese Synchronisation. Dieser Helper enthält dafür keine Adapter.

Für die native Abnahme nutzt Codex eine tatsächlich verfügbare Apple-macOS-
CI-/Cloudumgebung mit SDK und dokumentiert Architektur, OS, Quellmanifest,
Runtimehash und Ergebnis. Wenn eine solche Umgebung fehlt, bleibt dieser
Schritt ausdrücklich offen. Keine persönliche Mac-Hardware wird vorausgesetzt;
dieser Patch ist keine Paketveröffentlichung.
