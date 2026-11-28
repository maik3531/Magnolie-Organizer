# #855 – Einrichtung mit allen 20 Sprachkatalogen nachgeprüft

Die bislang wegen fehlendem `msgfmt` und nicht erzeugten JavaScript-Katalogen
offene vollständige Sprachmatrix des vorhandenen Einrichtungstests ist jetzt
ausgeführt: **88/88 Fälle über beide Desktopoberflächen, 20 Sprachen**.
Der Test lief sowohl mit dem eingecheckten Windows-Nativkatalog als auch mit
dem aus den gebundenen PO-Quellen regulär neu erzeugten Nativkatalog erfolgreich.
Das sind zwei Eingabekonfigurationen derselben 88 Fälle, keine 176 verschiedenen
Prüfanforderungen.

## Genaue Quellen und Umfang

- Produktbasis: `1749c92eb42801c38eaba31b272d8c0e27be9164`.
- Geprüfter #855-Ergebnisbaum: `f4f94a2c2cf73a064448d3208f31d471e150dbe4`.
- Unverändertes Prüfprogramm: `magnolie-organizer-windows/tests/setup-holidays.js`.
- SHA-256 des Prüfprogramms vor und nach dem Lauf:
  `401a75060f7a90f4cf12f962c6097bb089eff7debc471be29b71bea150d4209a`.
- Keine Assertion, keine Sprachliste und kein Produkttext wurden abgeschwächt
  oder geändert. Die originale Matrix bestimmt ihre Sprachen weiterhin aus
  `magnolie-organizer/po` zuzüglich Englisch.
- 40 sprachabhängige Einrichtungsläufe (20 Sprachen × zwei Oberflächen) und
  48 weitere vorhandene Ablaufprüfungen. Die früheren 50 Fälle waren die
  auf Englisch begrenzte Teilmatrix; jetzt ist das Originalprogramm gelaufen.
- Spracheinstellungen: `en`, `ar`, `be`, `cs`, `da`, `de`, `es`, `fr`, `hi`,
  `hsb`, `it`, `ja`, `nb`, `nl`, `pl`, `pt`, `ru`, `tr`, `uk`, `zh_CN`.

Die Testkopie wurde aus dem angegebenen Git-Baum exportiert. Alle 159
exportierten Eingabedateien besitzen nach Katalogerzeugung und beiden Testläufen
weiterhin exakt ihre ursprünglichen SHA-256-Werte. Hinzu kamen ausschließlich
die benötigten 38 generierten Webkataloge. Die Hauptarbeitskopie wurde nicht
geändert.

## Tatsächliche Ausführung

GNU gettext `msgfmt` **0.23.1**, Node **24.22.3**, JSDOM **26.1.0**,
Python **3.12.14**, Linux. Die beiden vorhandenen `po_zu_js.py`-Generatoren
kompilierten jeweils alle 19 PO-Kataloge. Sie rufen echtes GNU `msgfmt` mit
`--check --check-format` auf; es wurde kein Ersatzparser oder nachgebauter
Katalog verwendet. Der vorhandene Windows-Generator `po_zu_native.py` wurde
ebenfalls unverändert ausgeführt.

Das GNU-Werkzeug wurde aus dem offiziellen Debian-13-Paket
[`gettext_0.23.1-2_amd64.deb`](https://packages.debian.org/trixie/amd64/gettext/download)
lokal entpackt, nicht systemweit installiert. Paketgröße: 1.680.396 Bytes;
SHA-256:
`25293e75989db79a1d4a6b942674b0e7243da54a0985f8d9df1b345d255d262b`.
Die heruntergeladenen Bytes stimmen mit der vom Debian-Paketverzeichnis
ausgewiesenen Prüfsumme überein. Das Werkzeug und seine Bibliotheken sind keine
Bestandteile des Produktpatches oder dieser Übergabe.

## Beobachtete Abweichung des generierten Nativkatalogs

Beim Vergleich trat genau eine schon in der Basis vorhandene Abweichung auf:
Der eingecheckte Windows-JSON-Katalog enthält für Portugiesisch den Wert
`No`; die vorhandene PO-Quelle erzeugt korrekt `Não`. Alle anderen
Nativkatalogeinträge stimmen semantisch überein. Deshalb wurden beide realen
Eingabefassungen mit demselben unveränderten Einrichtungstest geprüft.

Der normale Windows-Bau regeneriert seine Nativkataloge bereits mittels
`Update-WebCatalogs` in `build/Build.ps1`. Diese Beobachtung belegt daher
zunächst einen veralteten generierten Quellbestand, **keinen nachgewiesenen
Fehler eines regulär gebauten oder ausgelieferten Pakets**. Die PO-Quelle
enthält bereits die richtige Übersetzung; es wurde dafür kein Produktpatch
erfunden. Die erste zu strenge Prüfannahme des externen Hilfsrunners
(generierter und eingecheckter Katalog müssten vollständig identisch sein)
ist in `initial-precheck.txt` dokumentiert.

## Belege und Wiederholung

- `receipt.json`: Ergebnisse, Versionen, Sprachen, Quellen- und Ausgabehashes.
- `commands.json`: alle tatsächlichen Generator- und Testaufrufe samt Exitcodes.
- `setup-holidays-all-languages.log`: Originaltest mit eingechecktem Nativkatalog.
- `setup-holidays-rebuilt-native-all-languages.log`: Originaltest mit frisch
  erzeugtem Nativkatalog.
- `source-manifest.json` und `source-preservation.json`: Bindung und Erhalt der
  159 exportierten Eingabedateien.
- `native-catalogue-diff.json`: vollständige einzelne Nativkatalogabweichung.
- `gettext-provenance.json`: Downloadadresse, Paketbindung und Werkzeugversion.
- `run-validation.py`: reproduzierbarer externer Ablauf, unveränderte
  Produktgeneratoren und unverändertes Testprogramm.

Auf einer isolierten Kopie des genannten Ergebnisbaums mit JSDOM 26.1.0 und
lokal entpacktem GNU-gettext-Paket:

```sh
python run-validation.py \
  --source /path/to/isolated-candidate \
  --gettext-prefix /path/to/extracted-gettext \
  --node-modules /path/to/node_modules \
  --output /path/to/evidence
```

Die Generatoren erzeugen die fehlenden Webkataloge in dieser isolierten Kopie.
Für die zweite Variante wird der Nativkatalog vorübergehend durch das echte
Generatorergebnis ersetzt und anschließend bytegenau zurückgesetzt.

## Grenzen

Dies schließt die zuvor fehlende **Sprachmatrix des vorhandenen
Einrichtungs-Regressionsprogramms**. Es ist keine sprachwissenschaftliche
Prüfung sämtlicher Texte, keine vollständige RTL-/Layoutabnahme und kein
nativer GTK-/WebView2-Test. Die Brücke und die Datensicherung werden im
vorhandenen JSDOM-Prüfhost kontrolliert. Es wurden keine installierbaren
Produktpakete gebaut, installiert oder veröffentlicht.
