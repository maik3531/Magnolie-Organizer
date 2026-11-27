# #395: begrenzte Organisatorvorschläge im Terminblatt

## Geprüfter Teilpatch

- Basis: `24927cf94cfe9a7bb5c4f148a38d6b04b0bc732b`
- Commit: `38edd46ef18259e232c786bf2e8e88903f96b655`
- Tree: `14bceb0da8d668f64b882a729201c7c23c65dab9`
- Übergabe: [refs-395-organizer-suggestions.patch](refs-395-organizer-suggestions.patch)
- Bindung der Quellen, Prüfungen und Rückgabecodes: [manifest.json](manifest.json)
- Unabhängiger Review: [independent-review.json](independent-review.json)

Die Produktänderung betrifft ausschließlich die Organisator-Namensvorschläge im
Terminblatt der Linux- und Windows-Oberfläche. Ein zusätzliches Prüfprogramm ist
im vorhandenen Windows-Webrunner registriert; es prüft beide vorhandenen
Desktop-Webquellen. Die bestehende allgemeine UI-Prüfung fokussiert das Feld vor
dem Lesen seiner Vorschläge. `ARBEITSSTAND.md` wurde für die gemeinsame Übergabe
nicht parallel geändert; der passende Text steht in
[ARBEITSSTAND-fragment.md](ARBEITSSTAND-fragment.md).

## Bestätigter Befund und Änderung

Vorher baute jedes Öffnen sofort eine `<option>` pro eindeutigem Kontaktnamen.
Bei einem neuen Termin liegt dieses Feld im zunächst geschlossenen Zusatzbereich.
Die echte Oberfläche erzeugte mit 2.003 synthetischen Kontakten daher jeweils
2.002 unbenutzte Namensoptionen. Fünf reguläre Öffnen-/Schließen-Zyklen zeigten das
auf beiden Desktopquellen. Geschlossen wurde über den tatsächlichen Schließknopf.

Jetzt bleibt die Namensliste beim Öffnen leer. Fokus oder Eingabe erzeugen höchstens
das vorhandene Listenhäppchen von 250 Vorschlägen. Eine nichtleere Suche prüft den
ganzen aktuellen Kontaktbestand. Ein exakter kurzer Name bleibt auch dann sichtbar,
wenn zuvor bereits 250 längere Teiltreffer gefunden wurden. Die leere Fokussuche
endet bereits nach dem ersten Häppchen. Es entsteht kein dauerhafter Kontaktcache.

Namen am Ende der Liste, Firmen ohne Personennamen und frei eingegebene
Organisatoren bleiben nutzbar. Alle E-Mail-Adressen exakt gleichnamiger Kontakte
werden wie zuvor zusammengeführt. Bereits gespeicherte Name-, E-Mail- und
URI-Werte werden durch die Vorschläge nicht ersetzt. Es kommt kein Dialog und
keine weitere Bestätigung hinzu.

## Tatsächlich ausgeführte Prüfungen

| Stand | Ergebnis | Bedeutung |
|---|---:|---|
| Unveränderte Basis, erste acht neue Fälle | 0/8 | Ressourcen-/Suchzustandsanforderungen rot; pro Öffnen 2.002 versteckte Namensoptionen |
| Erster enger Zwischenstand | 8/8 | Begrenzte, bedarfsgesteuerte Vorschläge funktionieren |
| Zusätzlicher exakter Kurzname im Zwischenstand | 8/10 | Später exakter Name fällt noch hinter 250 Teiltreffer |
| Finaler Commit | 10/10 | Fünf Fälle auf beiden Desktopquellen einschließlich der Zusatzkante bestanden |
| Bestehendes `structured-appointment-parity.js`, finaler Commit | PASS | Strukturierte Terminverarbeitung beider Desktopquellen bestanden |

Die acht bzw. zehn Fälle sind keine acht bzw. zehn unabhängigen Produktfehler.
Sie prüfen unterschiedliche Ressourcen- und Erhaltungsbedingungen desselben
engen Teilpatches. Die gezählten DOM-Knoten und die Rohzeiten der fünf Zyklen
stehen in [dom-observations.json](dom-observations.json).

Die Rohzeiten stammen aus Node 24.22.3 und JSDOM 26.1.0 auf dem Linux-Host mit dem
vorhandenen Desktop-Regressionsharness. Dieser verwendet kontrollierte Timer und
synthetische Bridge-Nachrichten. Primärer Nachweis ist die entfernte DOM-Arbeit:
2.002 auf 0 unbenutzte Optionen je Öffnen, höchstens 250 bei Benutzung. Die
Einzelzeiten sind keine universelle Beschleunigungsquote oder native Latenzgarantie.

`before.log` und `baseline-tests-8-cases.source.txt` halten den ersten roten
Prüfstand fest. Der `.source.txt`-Inhalt ist ein Quellsnapshot des damals verwendeten
Tests, kein eigenständiger Runner. `before-exact-match.patch` und
`intermediate-8-cases-binding.json` beschreiben ausschließlich den Zwischenstand;
auszuliefern ist die oben genannte finale Patchdatei.

## Gezielt erneut prüfen

Nach Anwendung des finalen Patches im Repository mit den bereits vorhandenen
Node-/JSDOM-Abhängigkeiten:

```sh
python magnolie-organizer/werkzeuge/zeitzonen_erzeugen.py
python magnolie-organizer/werkzeuge/zeitzonen_erzeugen.py --output magnolie-organizer-windows/app/web
NODE_PATH=/pfad/zu/vorhandenen/node_modules node magnolie-organizer-windows/tests/appointment-organizer-suggestions.js
NODE_PATH=/pfad/zu/vorhandenen/node_modules node magnolie-organizer-windows/tests/structured-appointment-parity.js
```

## Offene Grenzen in #395

Die vorherige unveränderte Volumensuite auf `50b15122` enthält je 50.000 Einträge
in fünf Bereichen. Ihr gemessener Import-/Zeichenblock mit 22,10 Sekunden und
20-Sekunden-Budget ist durch diesen Teilpatch nicht als behoben belegt. Die ganze
250.000-Einträge-Suite wurde für diese gezielte Änderung nicht nochmals ausgeführt.
Der dortige Terminblatt-Messabschnitt entfernt Dialoge unmittelbar per DOM;
die neue kleine Gegenprobe benutzt den regulären Schließweg.

Die Kontaktimportvorschau rendert bereits nur 25 Fälle pro Seite. Sichere Kopien,
kanonische Revisionsprüfungen und mehrere Bereichsmerges sind Teil des gemessenen
Gesamtblocks. Ohne getrennte Phasenmessung wurde keine davon als unnötige Ursache
entfernt. Die vollständige Quellenanalyse steht in
[review-395-source-analysis.json](../review-395-source-analysis.json).

Die nichtleere Namenssuche bleibt linear in der Kontaktzahl; die erzeugten
DOM-Optionen und der Deduplizierungssatz bleiben begrenzt. Native WebKit-/WebView2-
Datalist-Bedienung, der ursprüngliche N100-Bericht und langer Traybetrieb mit
Speicherverlauf bleiben offen. Weder diese kurze Prüfung noch die frühere
Spitzen-RSS-Messung beweisen einen Leak oder dessen Abwesenheit über einen Monat.
Es wurden keine Pakete gebaut oder installiert und keine GitHub- oder
Main-Merge-Aktionen ausgeführt.
