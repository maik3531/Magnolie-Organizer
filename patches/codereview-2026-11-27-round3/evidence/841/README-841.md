# #841: Leserichtung bei regionaler arabischer Systemsprache

## Ursache und enge Korrektur

Beide Desktop-Laufzeitkerne normalisieren `ar-EG` zu `ar-eg` und finden über
den primären Sprachcode korrekt den vorhandenen arabischen Katalog. Die
Richtungsprüfung verglich dagegen ausschließlich mit dem ganzen String `ar`.
Die normale `App.init`-Verarbeitung einer Systemauswahl setzte daher die vom
nativen Bootstrap zunächst gewählte Richtung `rtl` wieder auf `ltr`, obwohl
die Oberfläche arabisch blieb.

Der Patch bestimmt die Richtung aus dem primären Teil des tatsächlich
verwendeten Dokument-Sprachcodes. Damit verwendet er dieselbe Regel wie der
vorhandene Handbuch-Laufzeitkern. Sprachwahl, Katalogsuche, Pluralregeln und
fehlende-Katalog-Rückfall bleiben unverändert.

## Quellbindung

- Basis: `0cdd6f992e094cd724203713da3bf145c36958fc`.
- Geprüfter Quellcommit: `f24d6456e4c505e819a2a8f34e459b3c194d8a5e`.
- Quellbaum: `8dfc86802cb3eced889528005981ec9ade4e1194`.
- Zwei Produktzeilen in den kanonischen Linux-/Windows-`i18n.js`-Dateien.
- Regression `regional-language-direction.js` im vorhandenen Windows-Webtestlauf
  registriert; sie prüft beide tatsächlichen Desktopquellen, auch im
  eigenständigen Windows-Quellarchiv mit eingebetteter Linuxquelle.

## Tatsächlich geprüfte Fälle

Acht Fälle je Desktopquelle, alle mit vollständigem `index.html`, echtem
`i18n-start.js`, `anwendung.js`, normativem Zeitzonenmodul und `App.init`:

1. Ausdrückliche Auswahl `ar` als positive Kontrolle.
2. `ar-EG`.
3. Großschreibung und Unterstrich `AR_sa`.
4. Sprach-, Schrift- und Regionscode `ar-Arab-EG`.
5. Systemauswahl mit `navigator.languages = ["ar-EG", "en-US"]`.
6. Deutsche Systemauswahl als LTR-Kontrolle.
7. Englischer Rückfall nach arabischem Bootstrap.
8. Fehlender arabischer Katalog: sichtbare englische Texte und LTR bleiben erhalten.

Die Kataloge wurden aus den tatsächlichen jeweiligen PO-Dateien mit
`werkzeuge/po_zu_js.py` und GNU gettext 0.23.1 erzeugt. Die Eingangsbelege
verwenden keine nachgebildete Übersetzungsfunktion und keine handgeschriebene
arabische Testübersetzung als Laufzeitersatz.

Vorher: **8 bestanden / 8 fehlgeschlagen**, Prozessstatus 1. Nachher:
**16 bestanden / 0 fehlgeschlagen**, Prozessstatus 0. Die bekannten arabischen
Texte wurden parallel mitgeprüft, damit ein Rückfall auf englische Texte den
Richtungstest nicht scheinbar erfüllen kann.

Zusätzlich bestanden die vorhandene `regional-time-input.js` in jeweils
20 Sprachen auf beiden Desktopquellen und `localization-completeness.js`.
Letztere benötigt wie der normale Bau die Erzeugung des nativen Katalogs:
die einzige Änderung gegenüber dessen bereits vorhandener Ableitung war
`pt / No: No → Não` aus #828. Diese Vorbereitung ist in
`localization-preparation.json` mit beiden Prüfsummen festgehalten; die
abgeleitete Datei wurde anschließend wiederhergestellt und ist nicht Teil
des #841-Patches.

## Reproduktion

Vorhandene Projektabhängigkeiten: Node, `jsdom` 26.1.0, Python 3 und GNU
gettext. Zuerst die üblichen Kataloge und das normative Zeitzonenmodul mit
den bestehenden Projektgeneratoren erzeugen. Anschließend vom Repositoryroot:

```sh
node magnolie-organizer-windows/tests/regional-language-direction.js
node magnolie-organizer-windows/tests/regional-time-input.js
MAGNOLIE_PYTHON=python3 node magnolie-organizer-windows/tests/localization-completeness.js
```

Der zusätzliche `arabic-regional-direction.cjs`-Runner nimmt den zu prüfenden
Repositoryroot als erstes Argument entgegen. Derselbe Runner wurde vor und
nach dem Fix ausgeführt; sein ausführliches JSONL-Protokoll enthält Istwerte,
Sollwerte und Resultate für jeden Fall.

## Grenzen

Die Tests führen den tatsächlichen UI-Code in JSDOM mit einer aufzeichnungs-
losen synthetischen nativen Brücke aus. Sie belegen Initialisierung,
Übersetzungswahl und DOM-Leserichtung. Sie sind keine native
GTK-/WebView2-/macOS-/Android-Abnahme, keine Pixel-/Geometrieprüfung und keine
Paketfreigabe. Die Mac-/Tablet-Projektionen übernehmen den gemeinsamen
Laufzeitkern bei ihrer regulären Erzeugung; ihre native Darstellung wurde
hier nicht geprüft.
