# #844: verbleibender Farbnachtrag auf der endgültigen Basis 7a490dd8

**Für die angepasste Lieferung gilt Commit
`c534e008f39785e1cd98ab5473ec9421a6828845` auf
`7a490dd87e94eec08d7f09cb95a04b34bf4621c2`.** Sein Tree ist
`d771358a8564b2ea6ac498b9f5c9d3af09cf349b`. Der vorherige #844-Nachtrag
`a6462407` auf `1f1f3225` und seine Nachweise bleiben als historische
Zwischenfassung erhalten; die beiden Fassungen nicht nacheinander anwenden.

## Präzise Anpassung an die unabhängige Nextcloud-Übernahme

Upstream `7a490dd8` erkennt bestimmte Nextcloud-Geburtstage, gibt ihnen Farben
und exportiert Jahrestagsfarben bereits. Diese Teile werden nicht erneut
implementiert. Bei der Anpassung wurden vier Konflikthunks aufgelöst:

- Die neue Nextcloud-Erkennung, Auswahl des Geburtsdatums, Behandlung abgetrennter
  Serienausnahmen sowie der ursprünglichen Jahresregel bleiben erhalten.
- Beide inzwischen übernommenen Jahrestags-Farbexporter bleiben bytegleich.
- Die Farbmetadaten werden zusätzlich allen bereits erkannten markierten
  Jahrestagen zugewiesen. Auf der neuen Basis geschah das nur im besonderen
  `providerDate`-/`provider_datum`-Zweig.
- Der verbleibende unveränderte parametrische `COLOR`-Erhalt, der optionale
  UID-Aliasfeld-Guard, der Python-gettext-Rename und die geprüfte sichtbare
  Darstellung aus #844 werden beibehalten.

[upstream-preservation.json](upstream-preservation.json) enthält zwölf genaue
Erhaltungsbindungen. Darunter sind die echten Python-/C#-Nextcloud-Helfer,
Exporter, Detached-Prüfung und bestehenden Testdateien. Die neue
`birthday-display.js` enthält vollständig die übernommenen Tests plus vier
#844-Zeilen. Es wurde keine Geburtstags-Typregel erweitert.

Der [unabhängige abschließende Review](independent-review.json) ist an den
endgültigen Commit und seine Produktdateien gebunden. Er bestätigt zwölf eigene
Erhaltungsprüfungen ohne offenen Befund. Das war eine statische Gegenprüfung der
Konfliktauflösung; sie wird nicht als erneuter Lauf der fachlichen Tests gezählt.

## Erneut auf diesen Quellen ausgeführt

| Prüfung | Ergebnis |
| --- | --- |
| Neue 25 Farbregressionen auf unverändertem `7a490dd8` | **22 fehlgeschlagen / 3 bestanden** |
| Neue und bestehende fokussierte Python-Farbprüfungen sowie negativer ICS-/DAV-Pfad | **47/47 bestanden** |
| Bestehende Python-Geburtstagsbereinigung/Deduplizierung | **15/15 bestanden** |
| Unverändert übernommene Nextcloud-Pythonprüfungen | **12/12 bestanden** |
| Tatsächlicher CoreTests-Build mit gesperrten Abhängigkeiten | **Erfolgreich** |
| C#-Farbgruppen | **3/3 bestanden**, darin 25 neue Restfälle |
| Unverändert übernommene C#-Nextcloud-Gruppe | **1/1 bestanden** |
| Neue DOM-Modellfälle | **24/24 bestanden**, je zwölf pro Desktopedition |
| Echter Codec→Frontend→Dateispeicher→Wiederöffnen→Export/Reimport-Datenweg | **48/48 bestanden** |
| Bestehende Kategorie-, Geburtstags- und UID-Alias-DOMskripte | **Alle drei in beiden Editionen bestanden** |

Die 48 Pipelinefälle verwenden dieselben zwölf gemeinsamen Eingaben wie zuvor,
jedoch die neuen tatsächlichen Python-/C#-Codecs. Beide Desktopquellen führen
Import, Normalisierung, Ansichten und serialisierten Save-Request aus. Die
Nutzlast wird anschließend durch die echte Python-Speicherung beziehungsweise
den echten C#-`AtomicStore` geschrieben und wieder geöffnet; danach folgen
Export und Reimport. Dateireadback, Farbwerte, Jahrestagstypen, Datumswerte und
unveränderte Parameter werden geprüft.

Anders als beim vorherigen Lauf führte der portable Runner diesmal auch den
**CoreTests-Build selbst** aus. Im
[Pipeline-Manifest](after/pipeline/pipeline-manifest.json) stehen daher
`build_executed_by_runner=true` und `build_exit_code=0`.

## Wiederholung und Bindung

Die Befehle stehen in [test-commands.json](test-commands.json). Der bereits
geprüfte portable Runner bleibt unverändert unter
[../remainder/run-pipeline.py](../remainder/run-pipeline.py):

```bash
python3 ../remainder/run-pipeline.py --checkout /pfad/zum/checkout --tools /pfad/zu/round3-tools --output /pfad/zu/neuen-ergebnissen
```

Vorher die beiden Zeitzonenassets mit dem Repositorygenerator erzeugen; die
bestehende Kategorie-DOMsuite benötigt außerdem die kanonisch aus den PO-Dateien
erzeugten Linux-Sprachkataloge. Die genaue Vorbereitung steht im unveränderten
[Runner-Handbuch](../remainder/README.md#wiederholung).

[manifest.json](manifest.json) bindet Commit, Tree, Patch, finale Quellbytes,
kompilierte C#-Eingaben und sämtliche Ergebnisdateien. Die Nachweise liefen auf
den danach unverändert committeten Produktbytes. Nur diese auf `7a490dd8`
angepasste Fassung gehört in die neue Patchserie.

## Grenzen

Die Save-ACKs im JSDOM-Harness sind synthetisch; die anschließenden Dateischreiber
und -leser sind echt. Das ist keine installierte GTK-/WebView-, Notes-, Geräte-
oder CalDAV-Serverabnahme. Die frühere hostseitige Named-Pipe-Grenze wurde nicht
erneut getestet und nicht als bestanden übernommen. Beliebige unbekannte
Kalenderkopf-Farbmetadaten bekommen keine neue globale Speicherhülle.

Weitere tatsächliche Nextcloud-Reste werden getrennt unter #845 bearbeitet und
sind nicht in diesem Commit enthalten. Zwei reine Aufruf-/Vergleichshilfenfehler
vor beziehungsweise außerhalb der Produktprüfung stehen transparent in
[harness-notes.json](harness-notes.json); sie führten zu keiner Produktänderung.
