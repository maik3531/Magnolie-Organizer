# #838 – Zeichenblatt-Fehleranzeigen und gültige Wiederholung

Geprüfte Ausgangsbasis: `1543858e251d7e29ebeafb67d2605991c1d442d5`.
Arbeitszweig: `review/round2-ui-20261127`.
Quellwurzel: `$REVIEW_WORKSPACE/round2-ui`.

## Lieferung

1. `4a4cdef33f784990c495bc6fd32ca634f0e5d59c` – entfernt vier unbenutzte
   `catch (_)`-Bindungen in jedem Desktopfrontend. Die vorhandenen
   Übersetzungsaufrufe können dadurch die beabsichtigte Fehlermeldung anzeigen.
   Enthält den UI-Regressionsprüfer, seine Runnerregistrierung und Testdoku.
2. `08887a810befd4cda824a8bd6f504c95c4b3068a` – zeigt nach erfolgreichem
   JSON-Import den geladenen Dateinamen an, sodass ein Fehler des vorherigen
   Versuchs nicht stehen bleibt. Der echte FileReader-Retry prüft diese Anzeige.

Beide Commits referenzieren #838. Keine neuen Übersetzungstexte, keine
Produktversionsänderung, kein Main-Merge, keine externe Mutation durch diesen
Teilauftrag. ARBEITSSTAND und Patchserie übernimmt der Integrationsverantwortliche.

## Reproduktion und Nachweis

Eigene Registerkarte → Zeichenblatt → Öffnen → `broken-drawing.json` mit den
11 Bytes `{"version":` auswählen. Auf der Ausgangsbasis löst der tatsächliche
FileReader den Produktcallback aus. Nach dem JSON-Parsefehler verdeckt die
Catch-Bindung die Übersetzungsfunktion; Ergebnis ist `TypeError: _ is not a
function`. Die beabsichtigte Fehlermeldung fehlt, der alte KDE-Connect-Hinweis
bleibt sichtbar. Beide Frontends sind unabhängig reproduziert; Zeichnung und
Speicheraufrufe bleiben unverändert.

`drawing-errors-before.json` und `reproduce-drawing-errors.cjs` halten diesen
Ausgangsnachweis fest. `838-regression-before.log` zeigt den neuen Prüfer vor dem
Produktfix mit Exitcode 1. `838-regression-after.log` dokumentiert 16/16 Fälle
nach dem ersten Commit. Die bei der Wiederholung gefundene veraltete Statuszeile
ist in `drawing-status-after-retry.json` sowie im roten
`838-retry-status-before.log` dokumentiert. `838-retry-status-after.log` zeigt
16/16 Fälle nach dem zweiten Fix, einschließlich korrektem Dateinamen.

## Bestandene Prüfungen

- Neuer `drawing-error-feedback.js`: 16/16 Szenarien (vier Bedienfolgen ×
  Englisch/Deutsch × Windows/Linux). Ungültiges JSON sowie nicht unterstützte
  Zeichenblattversion, Exportfehler, Gesamtblattrotation und Einbetten in eine
  Notiz. Lokalisierte Meldung, unveränderte Daten, keine zusätzlichen
  Speicher-Timer/-aufrufe oder Exporte bei Fehler und erfolgreiche Wiederholung.
- Bestehender `drawing-sheet.js`: beide Desktopprojektionen bestanden nach dem
  ersten Commit; `838-existing-drawing-sheet.log`.
- Bestehender `time-zone-settings.js`: 12/12 protokollierte Fälle bestanden nach
  dem ersten Commit, einschließlich des zuvor in #425 korrigierten
  Regionalfehlerpfads; `838-existing-time-zone-settings.log`.
- `git diff --check` vor beiden Commits ohne Befund; abschließend sauberer Zweig.

## Ausführungsgrenzen und Wiederholung

Die Tests laden die tatsächlichen Desktop-Webquellen in den bestehenden
JSDOM-Harness. JSON läuft durch den echten FileReader. Die kurze Beobachtung
des `onload`-Callbacks verhindert ausschließlich, dass JSDOM seine Ausnahme
stillschweigend verwirft. Canvas-Ausgabe wird wie im vorhandenen Zeichenblatt-
Integrationstest ersetzt. Für das defekte Hintergrundbild simuliert eine
native Decodergrenze `complete=true` und `naturalWidth=0`; die produktive
`MagnolieZeichnen.ready()`-Implementierung bleibt unverändert. Dies sind keine
nativen Windows-/Linux-Paketabnahmen, keine Pixelvergleiche und kein Release-Gate.

Vorhandene Werkzeuge wurden wiederverwendet. Normative Zeitzonen wurden mit
`magnolie-organizer/werkzeuge/zeitzonen_erzeugen.py` für beide Webwurzeln erzeugt;
deutsche Kataloge mit den jeweiligen `werkzeuge/po_zu_js.py` aus den jeweiligen
`po/de.po` bzw. `app/po/de.po`. Diese abgeleiteten Ressourcen sind keine
getrackten Produktänderungen.

Prüfbefehl aus der Quellwurzel:

```sh
NODE_PATH=$REVIEW_TOOLS/node_modules \
  node magnolie-organizer-windows/tests/drawing-error-feedback.js
```

Die beiden bestehenden Prüfprogramme verwenden denselben `NODE_PATH`.
Es wurden keine Abhängigkeiten neu installiert.
