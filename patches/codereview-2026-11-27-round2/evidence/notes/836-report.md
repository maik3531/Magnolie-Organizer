# Notes #836: Fehler beim Öffnen eines Anhangs

## Ergebnis

Enger Fehlerpfad-Fix auf Basis `1543858e251d7e29ebeafb67d2605991c1d442d5`, Commit `f2f429807186760248c5ddf4c2af3f22f4e1f568`,
Zweig `review/round2-notes-20261127`. Ausschließlich `AnhangDatei.kt`, der zugehörige
MainActivity-Klickhandler und `AnhangOeffnenTest.kt` sind geändert.
Keine Änderung an main und keine Paketveröffentlichung.

Die unveränderte Produktfunktion ließ Cache-/Datei-/Providerfehler aus dem
Compose-Klickhandler entweichen. Dekodierung, Verzeichnisarbeit und Schreiben
liefen dabei synchron auf dem aufrufenden UI-Thread. Der innere bisherige
`runCatching` schützte nur `startActivity`, nachdem sämtliche Vorbereitung
bereits abgeschlossen sein musste.

## Reproduktion

Erster unabhängiger Aufruf tatsächlicher unveränderter Produktklassen
`AnhangDatei` und `AnhangPruefung` mit einem vollständigen 1×1-PNG:

- Normaler Cache: `true`, genau ein Viewer-Start.
- Eigene temporäre `.neu`-Datei als Symlink auf `/dev/full`: ungefangene
  `IOException: No space left on device`; kein Viewer-Start.
- Eigener Cachepfad durch eine Datei blockiert: ungefangene
  `FileNotFoundException: Not a directory`; kein Viewer-Start.

Kein Datenträger wurde gefüllt. Der Symlink existierte nur im eigenen, danach
entfernten Probeverzeichnis. Pillow hat das verwendete PNG zusätzlich tatsächlich
dekodiert (1×1, LA, Pixel 255/255). Log: `attachment-open/before.log`.

## Änderung

- Die vollständige Öffnungsoperation behandelt erwartete Ausnahmen mit `false`;
  die vorhandene lokalisierte Fehlermeldung im Editor wird dadurch erreichbar.
- Dekodierung, Cache-I/O und `FileProvider`-URI-Erzeugung laufen innerhalb von
  `withContext(Dispatchers.IO)`. Nach dessen Rückkehr startet der Viewer im
  aufrufenden Coroutinekontext. Der reale Editor startet die Operation in seinem
  bereits vorhandenen `rememberCoroutineScope`, also auf Main.
- `CancellationException` wird ausdrücklich weitergereicht. Abbruch während der
  Vorbereitung erreicht den anschließenden Viewer-Start nicht.
- Jeder Lauf verwendet eine eigene temporäre Datei, damit die neu mögliche
  parallele Vorbereitung denselben `.neu`-Pfad nicht gleichzeitig beschreibt.
  `finally` räumt diese Datei auch nach Schreib-/Renamefehlern auf. Die endgültige
  Datei wird weiterhin erst nach vollständigem Schreiben ersetzt.
- MIME-/Bytegrenzen, sicherer Dateiname, bestehender Cacheordner, 24-Stunden-
  Bereinigung sowie ausschließlich das bestehende Leserecht und die bisherigen
  Intentflags bleiben erhalten. Kein neues Schreibrecht wird erteilt.

## Tatsächliche Prüfungen

| Prüfung | Basis | Patch |
| --- | --- | --- |
| Identische 13 JUnit-Gruppen | 8/13 bestanden; 5 gezielte Fehler | 13/13 bestanden |
| Vier vorhandene Dekodier-/Namensgruppen | 4/4 | 4/4 |
| Dateisystem-Schreibfehler bei 32-Byte-Prozesslimit | `IOException: File too large` entweicht | `false` |
| Bestehende Cachedatei beim Schreibfehler | `keep` unverändert | `keep` unverändert |
| Temporäre Dateien nach Schreibfehler | 1 | 0 |
| Patchformat | — | `git diff --check` sauber |

Die neun neuen Gruppen prüfen Erfolgsfall mit Threadwechsel und unveränderten
Intentrechten, unbrauchbaren Cache, Cache-Berechtigungsfehler, Providerfehler,
fehlenden Viewer, Renamefehler mit Tempbereinigung, acht parallele Öffnungen,
explizite CancellationException und Abbruch bei noch blockierter Vorbereitung.

Für den separaten Schreibfehler wurde ausschließlich ein eigener Java-Unterprozess
auf `RLIMIT_FSIZE=32` begrenzt und `SIGXFSZ` dort ignoriert. Das echte Java-
Dateischreiben wird dadurch nach 32 Bytes mit `IOException` beendet. Keine
systemweite Grenze und keine Produktdatei wurde verändert. Anders als ein bloßer
fehlender Ordner prüft dieser Fall auch bereits erzeugte, teilweise geschriebene
Temporärdateien.

## Grenzen und Plattformabgrenzung

Es wurden Kotlin 2.4.21, die bereits vorhandenen JUnit-/Coroutine-Abhängigkeiten,
der vorhandene JDK-Compiler als Java-Modul und das echte lokale Dateisystem
verwendet. Kein neuer SDK-/Dependency-Stack wurde eingerichtet.

Android `Context`, `Intent`, `FileProvider` und die einfache Anhang-Datenklasse
sind im Hostlauf ausdrücklich Boundary-Seams. Die Assertions der neuen
Robolectric-Testklasse wurden unverändert ausgeführt; ausschließlich ihre
Runner-/SDK-Annotationen wurden für die Hostprojektion entfernt. Das ist kein
Robolectric-Lauf und keine Android-/FileProvider-/Berechtigungs-/APK-Abnahme.
Der bestehende Produktdecoder und die korrigierte Öffnungs-/Coroutinefunktion
wurden aus den tatsächlichen Quelldateien kompiliert, nicht nachimplementiert.
MainActivity wurde hinsichtlich des kleinen Scope-Anschlusses geprüft, aber nicht
als ganze Compose-App gebaut. Die native Bestätigung des Dialogs, Toasts,
Activity-Lebenszyklus und echten Providers bleibt ein gesonderter Prüfpunkt.

Linux `Fenster.bei_notiz_anhang_datei` und Windows
`BridgeDispatcher.HandleAttachmentFileAsync` besitzen eigene Implementierungen;
bei der Quellengegenprüfung liegen ihre Dateioperationen bereits innerhalb der
jeweiligen OSError-/IOException-Fehlerbehandlung. Dieser Notes-Fix wird deshalb
nicht als Desktopfix ausgegeben. Der Tablet-Bau übernimmt aus Notes lediglich
`DatenDateiKrypto` und `DateiDauerhaft`, nicht diesen Öffnungspfad. Keine neue
native Desktopprüfung wurde durchgeführt.

## Wiederholung und Belege

`attachment-open/run-regression.py` enthält die vollständige transparente
Hostprojektion, führt die realen Funktionen sowie dieselben Testassertions aus
und endet bei Fehlschlägen ungleich null. Als drittes Argument kann ein eigener
Testquellenbaum angegeben werden, um neue Regressionen auf alter Produktbasis
laufen zu lassen. `attachment-open/base` enthält nur die beiden aus `1543858e251d7e29ebeafb67d2605991c1d442d5`
exakt gelesenen Produktdateien; ihre SHA-256-Werte stehen bei den Logs.

- `attachment-open/before/junit.log`, `attachment-open/after/junit.log`
- `attachment-open/before/write-failure.log`, `attachment-open/after/write-failure.log`
- `attachment-open/before/source-hashes.json`, `attachment-open/after/source-hashes.json`
- `836-attachment-open.patch`, SHA-256 `6bf12f78c6dd97a595dd29717b27b9952f288fd698d5ebf7d8040d14052e3cc5`

Die vollständige geordnete Lieferung und ihre abschließende Quellbindung stehen im zentralen Patchindex.
