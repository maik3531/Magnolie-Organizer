# Nachtrag zu Issue #846

**Der konkret gemeldete MCP-Importfehler ist durch den vorhandenen #844-Guard der finalen Patchserie bereits behoben.** Dafür ist kein zusätzlicher Produktpatch nötig. Die vollständige Windows-Quellarchiv-CI bleibt als eigener Abnahmenachweis offen.

## Geprüfter Umfang

[Issue #846](https://github.com/maik3531/Magnolie-Organizer/issues/846) und beide aktuellen Kommentare wurden vollständig gelesen. Die Basis bleibt `7a490dd87e94eec08d7f09cb95a04b34bf4621c2`; der geprüfte Endstand ist `f3ea06e275ce6cd7547106096cfd96d27cf57e15`.

Das vorhandene Programm `magnolie-organizer-windows/tests/mcp-import-review.js` und sein Harness sind auf beiden Ständen bytegleich. Ausgeführt wurde ausschließlich dieses unveränderte Programm, getrennt für beide kanonischen Desktop-Webquellen, unter **Node 24.22.3 und JSDOM 26.1.0**.

| Stand | Windows-Webquelle | Linux-Webquelle |
|---|---|---|
| Basis `7a490dd8` | Rot: `operation_failed`, Zeile 221 | Rot: `operation_failed`, Zeile 221 |
| Final `f3ea06e2` | Vollständiges Programm PASS | Vollständiges Programm PASS |

Der Nachherlauf bestätigt den persistierten Abschluss, alte UID und lokale Identität, lokalen Alarm, Aufgabenverweis, unbekannte Fremdmetadaten und die Mehrdeutigkeitskontrolle ohne unerlaubtes Speichern. Die vier Läufe stehen mit Befehlen, Laufzeit, Quellhashes und Logs im [Ausführungsmanifest](846/execution-manifest.json). Der [Reproduktionsrunner](846/run-mcp-comparison.py) benötigt explizite Checkout-, Node-, Modul- und Ausgabepfade.

Die Baseline enthielt keine generierten Zeitzonenassets. Temporäre, auf Bytegleichheit geprüfte Webdateikopien ergänzten deshalb die bereits vorhandenen kanonischen Assets für den Lauf. Beide Checkouts blieben vor und nach dem Vergleich sauber; Produkt- und Testdateien wurden nicht geändert.

## Ursache und Überschneidung mit späterem main

Die Normalisierung erzeugt bei fehlender optionaler Kalenderfarbe eine vorhandene Eigenschaft mit dem Wert `undefined`. Im historischen Aliaszweig wurde diese Eigenschaft anschließend über JSON kopiert. Unser bereits gelieferter #844-Teil in `c534e008` schützt genau diese Kopie mit `t[feld] !== undefined`. Derselbe Aliaszweig wird beim Anwenden des geklonten MCP-Importentwurfs verwendet.

Der nach dem eingefrorenen Prüfstand gemeldete [Upstream-Commit f8ad956e](https://github.com/maik3531/Magnolie-Organizer/commit/f8ad956ec4c9a71cd4d857c3218177c481407c85) wurde ausschließlich anhand seines Diffs abgeglichen. Er beseitigt fehlende Farbwerte bereits in der Termin- und Aufgabennormalisierung. **Die Überlappung betrifft die fehlende Kalenderfarbe im historischen Android-Serienalias.** Die Implementierungen sind unterschiedlich; der spätere Commit ersetzt weder unsere Jahrestagsfarben noch den Erhalt unveränderter Farbparameter oder die gettext-Korrektur.

Der spätere Commit ergänzt außerdem eine spezifische MCP-Prüfung zur erhaltenen Farbherkunft. Dieser zusätzliche Assert ist nicht Teil der hier unverändert ausgeführten 7a/f3-Testdatei. Die [Issue-Kommentare](846/github-sources.json) melden Node-22- und Bun-Prüfungen des Upstream-Fixes; diese Angaben bleiben fremde Nachweise.

## Basis und verbleibende Abnahme

**Die ausgewiesene Basis der Patchserie und ihrer `git apply --check`-Prüfung bleibt `7a490dd8`.** Dieser Nachtrag führt keinen weiteren Apply-Check und keinen Rebase aus. Bei einer Übernahme gegen einen späteren `main` muss `f8ad956e` mit dem überschneidenden #844-Teil abgeglichen werden; die übrigen #844-Korrekturen bleiben gesondert zu beurteilen.

Bun war in der verfügbaren Laufzeit nicht vorhanden und wurde nicht installiert. Es gibt hier keinen eigenen Bun-Lauf, keine installierte native Anwendung und keine Paketfreigabe. Offen bleibt insbesondere die vollständige Windows-Quellarchiv-CI des korrigierten Stands gemäß #846/#113. Es wurden keine Issues geschlossen oder andere GitHub-Änderungen vorgenommen.

Der strukturierte Abschluss steht in [846-followup.json](846-followup.json).
