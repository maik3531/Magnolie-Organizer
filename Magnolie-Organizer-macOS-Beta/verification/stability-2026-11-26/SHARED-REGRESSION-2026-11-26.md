# Gemeinsame Regression für spätere stabile Übernahme — 26. November 2026

Geprüft wurde die isolierte, unveränderte Kopie von **c8a7690d5eb4e002ebadb1d0aab03c8780af9e0b**. Der Produktcode ist **215d89029df02df2dce78f35412785ec9f9b36d8**; dazwischen liegen ausschließlich fünf Dokumentations-/Belegdateien. Die nachträgliche Quellprüfung bestätigt erneut **3912 gebundene Dateien**. Der isolierte Git-Status ist leer.

## Ergebnisse

| Prüfung | Tatsächliches Ergebnis | Grenze |
|---|---|---|
| Gemeinsame Python-Auswahl | **444 Tests + 14 Untertests**, 0 Fehler/Skips; davon **131 OR6-Fälle in 18 Dateien** | Kein nativer Mac-Picker oder Apple-Konto |
| Mac-Quellvertrag / Runtime / AirPlay / Helper | **7 / 21 / 25 / 17 Tests** bestanden | Runtime-Vertrag auf Produkt 215d890; kein hier gebautes Mac-Binary |
| Mac-Host | **35 unterschiedliche Fälle abgedeckt**: 34 im Erstlauf, letzter nach historischer Git-Objektreparatur | Kein redundanter vollständiger zweiter 35er-Lauf; originale Logs erhalten |
| Tatsächlicher OR6-Helper → projizierte UI | **90 Checks** bestanden | Synthetischer Transport und Speicher-ACK |
| Linux-Parser-/Abgleichscript | **1137 ausgegebene erfolgreiche Prüfungen**, Ende erfolgreich, 24,815 s | Headless-Script mit echtem PyGObject/GTK; kein realer GUI-Lebenszyklus |
| Import-/Export-Vertrag | **26 ausgegebene Prüfungen**, erfolgreich | Gemeinsamer Dateicodecvertrag |
| Vollarchivformat | Erfolgreich | Implementiert keinen fehlenden nativen Mac-Vollarchivadapter |
| Linux-Gesamt-DOM / Windows-Web-Smoke | Beide erfolgreich | jsdom; kein GTK-/WebView2-Produktlauf |
| Alt-Android-ICS-Wiederimport | Beide aktuellen Linux-/Windows-UIs erfolgreich | Echter Python-Codec, synthetischer Save-ACK; kein C#-Codecbeleg |
| Zeitzonen | 597 Zonen; 37 Uhrkontexte / 370 Localeformate; 44 Projektorchecks; 9 TZif- + 1 CRLF-Checkout-Test | Bestehende Host-/Source-Verträge |

Die 19 Kalendervektoren wurden vorbereitet; Swift-Kalenderexport und Swift-Editor-Core liefen hier ausdrücklich nicht. Im Mac-Host sind unter anderem 15 kanonische und 9 Phone-Kommunikationspayloads, 20 opaque-JSON-, 101 Alt-ICS- und 107 Systemkonto-UI-Checks enthalten. Diese verschachtelten Checks dürfen nicht als zusätzliche unittest-Fälle addiert werden.

## Vorbereitung, frühere Abbrüche und verbleibende Umgebungsgrenze

Die Teilkopie enthielt zwei historische Referenzobjekte aus 067c389 noch nicht. Beide Originaldateien wurden von GitHub geladen, gegen die im Git-Baum erwartete Objekt-ID geprüft und ausschließlich im isolierten Git-Objektspeicher ergänzt. Der betroffene Mac-Hosttest besteht danach; aktuelle Quellen wurden nicht geändert.

GNU gettext wurde als echtes, anhand des offiziellen Debian-Index gehashtes Paket privat entpackt. Kataloge, Zeitzonenassets und Erinnerungs-WAV entstanden durch die Originalgeneratoren. Fehlende reine Python-Abhängigkeiten liegen nur in privaten Verzeichnissen. Der vollständige Parserlauf nutzt das bereits vorhandene System-Python 3.13.5 mit PyGObject 3.50.0, GTK 3.24.49 und GLib 2.84.4; die übrigen Python-Tests nutzen 3.12.14. Node ist 24.22.3, jsdom 26.1.0.

Der paketübliche Wrapper `dbus-run-session` scheiterte vor dem Test mit **Operation not permitted** beim Öffnen des Sitzungsbus-Sockets. Der ebenfalls dokumentierte direkte Parseraufruf bestand anschließend vollständig. Dies ist kein bestandener Debian-Paket-/Sitzungsbustest. Alle früheren Abbrüche durch fehlenden Katalog, GI-Kontext, Klang, QR-Paket und historische Blobs bleiben mit Befehlen, Laufzeit und Loghash im JSON erhalten.

## Offene stabile Gates

- [#785](https://github.com/maik3531/Magnolie-Organizer/issues/785): tatsächliche Mac-Dateiauswahl, Vorschau, dauerhafter Save/Readback und Wiederöffnung; vollständige `.magnolie`-Passwort-/Integritäts-/Recovery-Transaktion sowie echte Mac-Quellenerkennung bleiben getrennte Aufgaben.
- [#786](https://github.com/maik3531/Magnolie-Organizer/issues/786): reale Testkonten in beiden Richtungen, dritter No-op, Konflikt, Rechteentzug, unsicherer Schreibausgang und Neustart ohne Duplikate. Der vorhandene manuelle Feldabgleich bedeutet keine volle automatische Synchronisation. **Historischer Befund im getesteten c8a7690d:** `IPHONE-INTEROPERABILITY.md` behauptete `false`, während `SystemAccounts.swift` für den begrenzten Coordinator `true` lieferte. Dieser Dokumentationsfehler ist im später separat gelesenen 8c860a14 korrigiert; siehe den Abgleich unten.
- [#511](https://github.com/maik3531/Magnolie-Organizer/issues/511): byteverschiedene, kanonisch äquivalente JSON-Schlüssel benötigen weiterhin verlustlose native Darstellung und echte Save/Reopen/Export-Prüfung. Die Schutzablehnung darf nicht gelockert werden.
- [#465](https://github.com/maik3531/Magnolie-Organizer/issues/465): gezielt ausgewählte alte Duplikatpaare samt Referenzen reparieren und nativ wiederöffnen; keine pauschale Buch-Deduplizierung oder UID-Umbenennung.

Keine neue native Mac-/Windows-Abnahme, kein Monterey-12.7-/TCC-/iPhone-/KDE-/Kontodienstnachweis. Der neue Runtime-Plattformguard und die Release-Swift-Prüfung des Hauptagenten sind spätere, getrennt zu belegende Änderungen. Die ursprüngliche Regression änderte keinen Produkt- oder Testcode und führte keine Remote-Mutation, Issue-Schließung, Main-Integration oder Veröffentlichung aus.

## Separater Quellenabgleich mit 8c860a14

Dieser Abschnitt ist ein **nachträglicher lesender Git-/Dokumentationsvergleich**, kein Testlauf auf dem neueren Commit. Die oben berichteten Tests bleiben auf **c8a7690d5eb4e002ebadb1d0aab03c8780af9e0b** und Produkt **215d89029df02df2dce78f35412785ec9f9b36d8** gebunden. Der spätere Vergleichsstand ist **8c860a14f7e10904c1b3a159ae84619c2c24ba82**. [Vollständiger Commitvergleich](https://github.com/maik3531/Magnolie-Organizer/compare/c8a7690d5eb4e002ebadb1d0aab03c8780af9e0b...8c860a14f7e10904c1b3a159ae84619c2c24ba82).

Die vollständigen gemeinsamen Bäume sind byte- und modusgleich: Linux **1000**, Windows **1208**, Notes **983**, Handbuch **164**, `port-adapters` **61** Dateien. Dasselbe gilt für die Mac-Bäume `Sources` **72**, `Projection` **12** und `Resources` **4** sowie **179 bestehende Vertragsdateien**; der bearbeitete Übergabeprompt und der neue Integrationsplan sind als Dokumentation getrennt ausgewiesen.

Von den **3912** ursprünglich gebundenen Dateien sind **3899 unverändert** und **13 geändert**. Insgesamt enthält der Vergleich **23 geänderte oder neue Pfade**:

- **5 geänderte Buildguard-/Guardtest-Dateien:** `airplay_bundle.py`, `import_python_bundle.py`, `build_dev.py` und die beiden zugehörigen Python-Tests.
- **2 neue native Prozessprobes:** `check_native_file_import_process.py` und `native_file_import_probe.swift`.
- **1 geänderter Workflow** mit zusätzlichen nativen/Release-Gates.
- **15 Dokumentations- und Belegdateien** einschließlich des korrigierten #786-Textes.

Die ursprünglichen **21 Runtime- und 25 AirPlay-Tests** sind dadurch nicht zu Tests der neuen Guards geworden. Die neuen Guards, Probes und Workflow-Gates benötigen ihre eigenen Belege. Im JSON stehen die vollständige 23er-Pfadliste (ohne Kürzung), alte/neue Git-Objekte, Dateihashes, die unveränderten Gruppen und die 13 abweichenden ursprünglichen Bindungen.

**#786-Dokumentationsabgleich:** [Der Text in 8c860a14](https://github.com/maik3531/Magnolie-Organizer/blob/8c860a14f7e10904c1b3a159ae84619c2c24ba82/Magnolie-Organizer-macOS-Beta/IPHONE-INTEROPERABILITY.md) nennt jetzt korrekt `systemAccountSyncImplemented: true` für den begrenzten manuellen Feldabgleich und `false` beim fehlgeschlagenen Statusaufruf. Er hält die Grenzen bei vollständiger/automatischer Synchronisation, Provider, TCC und Geräten ausdrücklich fest. Der historische Befund bleibt im erfassten c8a7690d-Bericht erhalten; `SystemAccounts.swift` selbst ist zwischen beiden Commits unverändert.

## Dauerhafte Logs und nachvollziehbare Normalisierung

Der vollständige [JSON-Beleg](shared-regression.json) enthält **44 tatsächliche Befehlslogs mit zusammen 210.698 ursprünglichen Bytes** und **2 zusätzliche Abhängigkeits-Download-/Installationslogs mit 3.627 Bytes**. Alle **46 Logs / 214.325 ursprünglichen Bytes** sind vollständig enthalten, einschließlich fehlgeschlagener Vorbereitung und des blockierten D-Bus-Wrappers. Es wurden keine Passagen entfernt und keine Logauszüge anstelle vollständiger Logs verwendet.

Interne Pfadpräfixe wurden durch `<CHECKOUT>`, `<TEST_ROOT>`, `<RECOVERY_ROOT>`, `<SCRATCH_ROOT>` und `<PRIMARY_RUNTIME>` ersetzt. Die Aliase beschreiben isolierte Prüfumgebung und Werkzeugherkunft; sie sind keine Links oder aktuellen Produktpfade. Das JSON hält die Rollen, Byteanzahlen und SHA-256 der ursprünglichen Präfixe fest, ohne die transienten internen Adressen zu veröffentlichen. Vor dem Speichern wurden sämtliche normalisierten Werte und Logs mit der privaten Präfixtabelle exakt zu ihren ursprünglichen Bytes zurückgeführt und geprüft. Die Originalpräfixe wären für eine spätere Rekonstruktion der Originalbytes erforderlich.

Jeder eingebettete Log nennt **ursprüngliche Größe/SHA-256** und **eigene normalisierte UTF-8-Größe/SHA-256**. Letztere werden über den nach JSON-Dekodierung erhaltenen `normalizedText` berechnet; sie sind unmittelbar aus dieser Datei prüfbar. Die ursprünglichen Ergebniszahlen, Fehler, Zeitstempel, Laufzeiten und Quellcommits wurden nicht verändert.

Die ursprünglichen **63 Belegreferenzen** sind einzeln klassifiziert: **46 normalisierte Logs eingebettet**, **17 Originalartefakte ausschließlich über ihren Hash referenziert** — 8 Wheels und 9 Nicht-Log-Dateien (Quellinventar, JUnit, Issue-Snapshot, Befehlsjournal, Vorbereitungs-/Restaurierungsmetadaten und zwei private Erfassungsprogramme). Teilweise daraus übernommene strukturierte Fakten sind kein Ersatz für deren Originalbytes. Die separat aufgeführten generierten Buildinputs sind ebenfalls nur gehasht; sie gehören nicht zu dieser 63er-Zählung.

Die Prüfung der Logtexte ergab keine Zugangsdaten, privaten Homepfade oder signierten Download-URLs. Gedruckte Kartenadressen sind fest im öffentlichen `test_parser.py` enthaltene synthetische Testdaten. Weitere gedruckte HTTPS-Quellen betreffen das öffentliche Python-Wheel und pytest-Dokumentation. Es wurde kein vollständiges Umgebungsabbild eingebettet.

## Herkunft und Prüfumfang der Sicherung

- Ursprünglicher strukturierter Capture `shared-regression-report.json`: **92.061 Bytes**, SHA-256 `d7110e97754a3d96bc26c8fabb159d9aa2f56c117081776036ca1f27ca5f6e48`.
- Ursprüngliche Lesefassung `SHARED-REGRESSION-REPORT.md`: **5.931 Bytes**, SHA-256 `3b9f7bf8264458f4a865cf426c812a05e9579ded49e239bc4bec942ca63c642e`.
- **44 Befehle**, sämtliche ursprünglichen Outcomes, ursprüngliche und normalisierte Loghashes sowie **63 Referenzen** sind im [dauerhaften JSON](shared-regression.json) enthalten. `captureFilename` bezeichnet darin einen Capture-Identifier, keine nebenliegende Datei.
- Die dauerhafte Übernahme prüft JSON, Werttreue, eingebettete Loghashes und lokale/commitgebundene Links. Sie führt keine Produktprüfung erneut aus und ändert weder Quellanker noch ursprüngliche Endwerte. Main-Integration, Issue-Schließung und Release sind nicht Teil dieser Sicherung.
