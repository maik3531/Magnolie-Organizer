# Geprüfter Nachtrag zu #844 nach der unabhängigen Übernahme

## Quelle und Umfang

Der Nachtrag `a64624071e700920907bcab7dd14d62fc93e0b9a` basiert exakt auf
`1f1f3225ab50fe38902bc8e790454fd944f8b693`; sein Tree ist
`afe90d4ded1b70f889462ef055c5bedfdd5d5c18`. Er erhält den übernommenen
#844-Fix `8c99834367cc59c7bf936dd630e86a3194304f96`. Der frühere, nicht
freigegebene Parallelentwurf bleibt unverändert unter `../unmerged-candidate`
erhalten und gehört ausdrücklich nicht zu dieser Patchfolge.

Vier konkrete Reste wurden am übernommenen Stand bestätigt und eng behoben:

1. **Markierte Geburtstage/Jahrestage verloren ihre erkannte Farbe.** Beide
   Codecs berechneten die Farbe für Termine/Aufgaben; ihr eigener
   Jahrestagszweig ließ sie weg. Der C#-Kalenderfallback erfasste diese Einträge
   ebenfalls nicht. Jetzt folgen sie derselben Rangfolge: gültige eigene
   Magnolie-Farbe, Standardfarbe der Komponente, bekannte Kalendervorgabe.
   Die Jahres-/Kalenderansichten, Liste und Druckmodelle verwenden die
   vorhandene Akzent- und Kontrastfunktion. Geburtstagstyp, Symbol, jährliche
   Semantik und jahrlose Daten bleiben erhalten. Es gibt keinen neuen Picker.
2. **Eine unveränderte eigene Farbübersteuerung entfernte fremde Parameter.**
   `COLOR;X-SOURCE=owned-synthetic:red` neben einer eigenen Farbe `#112233`
   wurde bereits ohne Bearbeitung verworfen. Der Nachtrag vergleicht die
   aktuelle Farbe mit der aus den erhaltenen Originalzeilen ableitbaren
   wirksamen Farbe. Dafür braucht er kein neues gespeichertes Merkmal.
   Wirkliches Ändern/Löschen aktiviert die alte Farbe weiterhin nicht erneut;
   unbekannte Komponentenfarben und verschachtelte Daten bleiben undurchsichtig.
3. **Alte Import-Payloads konnten den UID-Aliasabgleich abbrechen.** Die neue
   optionale `icsCalendarColor`-Eigenschaft war nach Normalisierung vorhanden,
   jedoch `undefined`. Die Kopierschleife rief darauf `JSON.parse(undefined)`
   auf. Sie übernimmt jetzt nur vorhandene Werte. Ein fehlendes Feld lässt
   den aktuellen Metadatenwert stehen; ein ausdrücklicher leerer String wird
   weiterhin übernommen. Die bestehende starke UID-/RID-Prüfung bleibt erhalten.
4. **Ungültiges/unvollständiges ICS erreichte nicht mehr den vorgesehenen
   Fehlerpfad.** Die neue Schleifenvariable `_` überschattete Python-gettext
   in der ganzen Funktion. Ein reiner Variablenrename stellt den vorhandenen
   `ValueError`-Pfad wieder her; der echte bestehende Nextcloud-Negativtest
   war vorher rot und ist nachher grün.

## Tatsächlich ausgeführte Prüfungen

| Prüfung | Vorher | Nachher | Nachweis |
| --- | --- | --- | --- |
| 25 neue Python-Fälle mit gemeinsamem Vertrag | 22 fehlgeschlagen, 3 bestanden | 25 bestanden | `before/python-canonical.log`, Teil von `after/python-verified.log` |
| Bestehende Python-Kategoriefarben plus negativer ICS-/DAV-Pfad | Negativfall wirft `UnboundLocalError` | 21 Farbprüfungen und 1 Negativfall bestanden | `before/invalid-ics.log`, `after/python-verified.log` insgesamt 47/47 |
| Bestehende Python-Geburtstags-Deduplizierung/Bereinigung | Nicht erneut als Baseline ausgeführt | 15/15 bestanden | `after/birthday-python.log` |
| C#-Build mit gesperrten Abhängigkeiten | Bestehende, gebundene Vorher-Assembly verwendet | Build erfolgreich, 0 Warnungen/Fehler | `after/csharp-build-final.log` |
| C#-Farbgruppen | 12 echte Vorher-Codec-Diagnosen gespeichert | 3/3 Gruppen; neue Gruppe enthält 12 Speichern/Wiederöffnen/Export-, 12 Ändern/Löschen- und 1 Mischkalenderfall | `before/csharp-canonical.json`, `after/csharp-category.log` |
| Neue DOM-Modellfälle beider Desktopeditionen | Je 3/12 bestanden | Je 12/12, zusammen 24/24 | `before/ui-canonical-*.log`, `after/ui-model-verified.log` |
| Tatsächlicher vollständiger Datenweg | Nicht als ganze Pipeline ausgeführt | 48/48 | `after/pipeline/pipeline-manifest.json` |
| Bestehende Farb-, Geburtstags- und UID-Alias-DOMprüfungen | Alias-Regression beidseitig rot; neue Dublettenprobe rot | Alle drei Skripte jeweils in beiden Editionen bestanden | `after/category-ui-prepared.log`, `after/birthday-display.log`, `after/legacy-alias.log` |

Die **48 Pipelinefälle** sind 12 gemeinsame synthetische Vektoren × 2 tatsächliche
Codecs × 2 tatsächliche Desktop-JavaScriptquellen. Der Ablauf ist:
ICS-Import → `App.importErgebnis` → Normalisierung/Ansicht → tatsächliche
serialisierte Save-Nutzlast und synthetischer ACK → tatsächlicher nativer
Dateischreiber → kaltes Wiederöffnen → ICS-Export → Reimport. Python benutzt
`speichere_daten`, `atomar_text_schreiben` und `daten_lesen_gepuffert`; C# benutzt
die echten Methoden `AtomicStore.WriteRecoverableJson` und
`ReadRecoverableJson` aus der gebundenen Testassembly. Der wieder geöffnete
Buchinhalt wird zusätzlich auf JSON-Gleichheit geprüft. Diese Nachweise gehen
über einen bloßen direkten Codec-JSON-Roundtrip hinaus.

Die Vorher-C#-Assembly stammt aus Root-Integration `bfac85982ed16b877e0c4f06e4fcb4fcda341125`
mit SHA256 `75db6d7debe0d373bc55af89b2422facdca961d75063324097ce3df9f6827c74`.
Die Kalenderpfade entsprechen der eingefrorenen Basis; die dortige zusätzliche
Codec-Änderung betrifft nur den getrennten CSV-Fix #566. Die Nachher-Assembly hat
SHA256 `b02980688cd11f4bbd1ddcbb1a5af52a9a83c68b9e9c9217a59c9c7baba7a328`.
Quell-, Test-, Vertrags- und Ausgabedateien sind in `manifest.json` gebunden.

## Wiederholung

Voraussetzungen: die vorhandenen Werkzeuge im angegebenen `--tools`-Verzeichnis
(SDK/NuGet, Python/pytest, Node und JSDOM); keine zusätzliche Toolchain.
Zunächst beide kanonischen Zeitzonenassets aus dem gewählten Checkout erzeugen:

```bash
python3 magnolie-organizer/werkzeuge/zeitzonen_erzeugen.py --source port-adapters/timezones --output magnolie-organizer/web
python3 magnolie-organizer/werkzeuge/zeitzonen_erzeugen.py --source port-adapters/timezones --output magnolie-organizer-windows/app/web
```

Der portable Pipeline-Runner führt standardmäßig auch den tatsächlichen
CoreTests-Build aus:

```bash
python3 run-pipeline.py --checkout /pfad/zum/checkout --tools /pfad/zu/round3-tools --output /pfad/zu/neuen-ergebnissen
```

`--skip-core-build` ist nur für eine bereits passend gebaute Assembly gedacht.
Der gespeicherte 48-Fälle-Lauf verwendete diese Option nach dem separat
erfolgreichen Build. Sein Manifest sagt deshalb ausdrücklich
`build_executed_by_runner=false` und `build_exit_code=null`. Der separat
ausgeführte Build hat den belegten Exitcode 0. Der kleine externe Probehost
wird vom Runner selbst gebaut und lädt die echte ausgewählte Produktassembly.

Die fokussierten Regressionsbefehle stehen zusätzlich vollständig in
`test-commands.json`; sie umfassen die drei Python-Testdateien/den gezielten
Negativfall, die drei C#-Farbgruppen und die vier DOM-Skripte. Für die bestehende
Kategorie-DOMsuite werden die Linux-Kataloge kanonisch mit
`po_zu_js.py SPRACHE QUELLE.po ZIEL.js` für jede Sprache aus `po/LINGUAS`
erzeugt (`msgfmt --check --check-format`). Windows-Kataloge sind getrackt.

## Grenzen und erhaltene Fehlversuche

- Die JSDOM-Brücke bestätigt Save-Nutzlasten synthetisch. Die anschließenden
  Dateischreiber/-leser sind echt, aber damit ist keine installierte native
  GTK-/WebView-Oberfläche, keine Geräteverbindung und kein CalDAV-Server freigegeben.
- Eine zusätzlich versuchte C#-Gruppe `Calendar birthday cleanup` konnte den
  Named-Pipe-Teil wegen `SocketException (13): Permission denied` im Prüfhost
  nicht abschließen. `after/birthday-csharp.log` bleibt erhalten; die Gruppe
  zählt nicht als bestanden. Das ersetzt die fehlende native Abnahme nicht.
- Beliebige unbekannte oder nicht vom vorhandenen validierten Headerfeld
  abgedeckte Kalenderkopf-Farbmetadaten erhalten keine neue globale Speicherhülle.
  Sie werden insbesondere nicht in einen falschen VEVENT-Scope verschoben.
  Die vollständige Übertragung solcher Header sowie Notes-/Providerwege bleiben
  außerhalb dieses engen Nachtrags. Der separate Nextcloud-BDAY-Markerfall #845
  gehört ebenfalls nicht zu diesem Patch.
- Erstläufe enthielten zwei nicht kanonische Typmarker in einer neuen Testfixture,
  einen fehlenden Parameter im C#-Testaufruf, einen zunächst vom vorhandenen
  Harness unterdrückten RAF-Renderpfad und fehlende generierte Linux-Kataloge.
  Diese Test-/Vorbereitungsfehler sind in `harness-notes.json` beschrieben; ihre
  Logs wurden erhalten. Die endgültigen Vorher-/Nachherangaben oben verwenden
  die korrigierten, identischen gemeinsamen Eingaben.
- Die unabhängige Gegenprüfung liegt neben diesem Verzeichnis in
  `../independent-final-*.json` und bindet die abschließenden Produktbytes.
  Sie bestätigt die zuvor roten Alt-/Parameter-/Birthday- und Aliasfälle;
  sie ist keine zusätzliche native Paketprüfung.

Für die Veröffentlichung nur die in `publication-files.json` aufgeführten
Quellen, Patches und Nachweise übernehmen; `bin`, `obj`, Caches und temporäre
Buchdateien gehören nicht zur Übergabe.
