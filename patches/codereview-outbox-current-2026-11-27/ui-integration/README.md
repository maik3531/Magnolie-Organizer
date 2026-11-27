# Gezielte UI-Integration nach dem Rebase auf da81f59

**Alle drei angeforderten Programme bestanden für beide Desktop-Webquellen.** Geprüft wurde die Überschneidung des verbliebenen #395-Patches mit den bereits übernommenen Änderungen zu #844 und #846. Es wurde keine weitere Suite ausgeführt.

| Programm | Ergebnis | Geprüfter Zusammenhang |
|---|---|---|
| `appointment-organizer-suggestions.js` | **10/10**, fünf Fälle pro Oberfläche | Verdeckte Felder erzeugen keine unbenutzten Optionen; Vorschläge bleiben auf 250 begrenzt, späte/exakte Namen erreichbar, freie Eingaben und bestehende Organisatordaten erhalten. |
| `calendar-colour-remainders.js` | **12/12 Windows-Webquelle und 12/12 Linux-Webquelle** | Farbübernahme und Jahrestagsdarstellung einschließlich Kalender, Planer, Speichern und erneutem Laden im DOM-Harness. |
| `legacy-android-instance-ui.js` | **Beide Webquellen bestanden** | Tatsächlicher aktueller Python-Codec, Legacy-Alias-Wiederimport/Speichern/erneutes Laden, fehlende gegenüber ausdrücklich leerer Kalenderfarbe, Quell-/RID-Grenzen, mehrdeutige Eingaben und gleichzeitige Buchänderung. |

Die Programme liefen unabhängig parallel. Laufzeiten: 3,017 s für Organisatorvorschläge, 8,050 s für Farben und 2,986 s für den Legacy-Alias-Fall; keine Zeitgrenze erreicht. Die protokollierten Einzelzeiten des Dialogöffnens sind Beobachtungen dieser Hostumgebung und kein nativer Leistungsnachweis.

## Quelle und Bindung

- Worktree: `/workspace/scratch/69a9d769e56f/outbox-latest-current`.
- Basis/HEAD während der Prüfung: `da81f594a2709d2c0ba78696b3af4775f38313f8`.
- Geprüft wurden die tatsächlichen Dateien der darauf vorbereiteten Restintegration. HEAD allein bezeichnet nicht den gesamten angewendeten Patchstand; maßgeblich sind die SHA-256-Bindungen im Manifest.
- **197 gebundene Eingabedateien waren vor und nach allen drei Programmen identisch.** Darunter die drei Programme, ihre zwei DOM-Harnessdateien, beide tatsächlichen Webquellen mit geladenen Assets, Verträge, synthetische ICS-Fixture und der aktuelle Linux-Python-Code.
- Die temporär ergänzten generierten Zeitzonenassets wurden anschließend entfernt. `git diff --name-only` meldete danach keine ungestagten Produktänderungen.

`manifest.json` enthält alle Eingabedateien und Prüfsummen vor/nach der Ausführung, die tatsächlichen Argumentlisten, das Arbeitsverzeichnis, die relevanten Umgebungsvariablen, Exitcodes, Laufzeiten und Log-Prüfsummen. Die drei `*.result.json` enthalten zusätzlich die einzelnen Programmnachweise.

## Vorhandene Prüfumgebung und Befehl

Verwendet wurden die bereits vorhandenen Werkzeuge:

- Node **v24.22.3**: `/opt/codex/runtimes/codex-primary-runtime/dependencies/node/bin/node`.
- JSDOM **26.1.0**, `NODE_PATH=/workspace/scratch/7203da5bd564/round3-tools/js/node_modules`.
- Python **3.12.14** für den tatsächlichen Codecaufruf des Alias-Programms.

Es wurde nichts installiert. Geerbte `MAGNOLIE_*`-Selektoren wurden entfernt, sodass kein einzelnes Frontend ausgewählt und kein optionaler nativer Windows-Codec-Datensatz eingeschleust wurde. `MAGNOLIE_PYTHON` wurde anschließend auf den dokumentierten vorhandenen Interpreter gesetzt.

Ausgeführt wurde:

```sh
python /workspace/scratch/69a9d769e56f/outbox-ui-integration-evidence/run_ui_integration.py
```

Der Runner startete ausschließlich die drei in der Ergebnistabelle genannten Dateien über den dokumentierten Node-Pfad. Jeder Prozess war auf 60 Sekunden begrenzt.

Die in einem frischen Worktree fehlenden, ignorierten `normative-timezones.js` wurden ausschließlich für diese Läufe aus `/workspace/scratch/7203da5bd564/open-audit-final-source` übernommen. Alle sieben einschlägigen Generator-/Daten-/Lizenzdateien unter `port-adapters/timezones` waren zwischen vorhandener Assetquelle und aktueller Quelle bytegleich. Assetquelle und Assetprüfsumme stehen im Manifest. Nur die vom Runner hinzugefügten Assets wurden danach wieder entfernt.

## Prüfgrenzen

Die tatsächlichen Linux- und Windows-JavaScript-Oberflächen liefen in JSDOM. Native GTK-/WebView-Darstellung, installierte Pakete, Geräteverbindungen und Freigaben wurden damit nicht geprüft. Die Farbtests verwendeten ihre eingebauten synthetischen DTO-Eingaben. Der Alias-Test verwendete für beide Oberflächen den tatsächlichen Python-Codec; ein nativer Windows-Codec wurde nicht ausgeführt. Save-Quittungen, Brücken und Timer stammen aus den vorhandenen synthetischen Harnesses.

Keine Produktquellenänderung, Abhängigkeitsinstallation, externe Mutation oder Veröffentlichung. Dieser neue, ausdrücklich ausgeführte UI-Nachweis ergänzt den separaten reinen Quell-/Testdiff in `upstream-adoption-review.json` und `.md`.
