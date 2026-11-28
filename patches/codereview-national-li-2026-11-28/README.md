# #853 – Liechtenstein: Staatsfeiertag und Höhenfeuer-Motiv

Basis `f9e2567760f43d479e2a6aef501b91b6395ed256`; main vor Veröffentlichung `ffe6c2f172a3bc005716e9867a3531651a73b164`; beide vollständigen Produktblobs bytegleich `0d8d5b32bd1d07093a3a0a8008b901717540d784`. Eigenständige Erweiterung, keine Änderung von Provider, Rechten, Synchronisierung oder CSS.

[Landesverwaltung, jährliche Termine](https://www.llv.li/de/landesverwaltung/protokoll-der-regierung/jaehrliche-termine), [Landtagsansprache 15.08.2025](https://www.landtag.li/ansprachen) und [offizielle Festseite](https://staatsfeiertag.li/), gelesen 28.11.2026: Staatsfeier am 15. August ab 1940, gesetzliche Beibehaltung 1990; Höhenfeuer und Krone auf Tuass als örtliche Tradition. Eigenes abstrahiertes SVG, kein Wappen oder Fremdgrafik. Nur Land LI, vor 1940 kein Motiv. Bestehender 80x80-Renderer, currentColor, 2px-Linien, unveränderte CSS-/Druckpfade, Vorschau standardmäßig aus.

## Ausgeführt

Je Desktop 86/96 → 96/96 kontrollierte V8-DOM-Double-Fälle auf vollständigem Originalmodul und Kandidat. Die erste Probe hatte einen Testaufbaufehler: Vorschau nach Sperren aufgerufen; korrigiert, im bestehenden ungesperrten Vorschautest geprüft. Historische IT-Fälle an bereits übernommene Codex-Korrektur angepasst. LI-Option/Explizitvorschau, Datum/Land, SVG-Attribute, Zellwechsel und Sperre. Exakter Kontext-Hunk-Rundlauf vorwärts/rückwärts. Kein tatsächliches Git-apply, keine echte Raster-/Kontrast-/Druck-/native Abnahme; Checkout DNS-Fehler. [Patch](national-li-853.patch), [Probe](probe.cjs), [Ergebnisse](results.json). Wiederholung nach isolierter Anwendung: node magnolie-organizer/pruefungen/test-national-li-853.cjs /pfad/zum/checkout. Handbuch/20 Sprachen und Portierung offen. Kein Produktmerge.

## Koordination

#865 PL-Ferien 2026/27 laut ARBEITSSTAND ausgesetzt, gesetzliche Feiertage weiter, Bestand erhalten; #864/#860 warten auf belegte korrigierte API. #128 Codex aktiv Notes-Originalreader (7243941483), Marker 8 nicht bewerben. #691 Baumwerk.kt-Blob d92816ad1df988319aca736651a5d7f176727f98 enthält weiterhin versucht++ vor LAN-Wartezweig und continue ohne Erstattung; alter Patch nicht übernommen, neue Fernwegänderungen erhalten. Desktop-Pumpfix nicht als übernommen bestätigt. Nächster freier Schritt CZ/ES oder Mac/Tablet-Projektion nach Koordinationsabgleich, alternativ #860 unabhängige weitere amtliche Quellen. Sync-Aufsetzpunkt erhalten.
