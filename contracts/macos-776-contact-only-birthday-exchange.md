# Kontaktgeburtstage beim Austausch mit Linux/Windows (#776)

## Ausgangspunkt und reproduzierter Fehler

Basis: `a26bb1302f3f5b772b83c9530f3098df34262f20` (integrierter Stand) nach dem getrennten
Diagnosepatch #778; gemeinsame Produktquellen aus
`616069f15fed21d8d8d05c8ef795f4ed21bd059c`. Der Kontaktkopiervertrag stammt
aus #775. Dieser Stand ist ein Vorschlag zur Codex-Prüfung und Übernahme,
keine Paketfreigabe.

Vor der Produktänderung wurden beide tatsächlichen Desktop-Oberflächen über
den bestehenden `desktop-state-regressions.js`-Bootpfad geladen. Eine mit
`nativeContactImport.version = 1`, `copyKind = "public-fields"` und
`birthdayPolicy = "contact-only"` markierte Kontaktkopie enthielt den
ausdrücklich bekannten Geburtstag `1604-02-29`. Daneben stand ein unverknüpfter
Geburtstagsjahrestag mit gleichem Namen und Datum `1990-02-28`.

Beide unveränderten Quellen erzeugten bei `App.init`:

```json
{
  "birthday": "--02-29",
  "anniversaries": [
    {"id": "namesake", "kontaktId": "mac-copy", "datum": "--02-29"}
  ]
}
```

Das bekannte Jahr ging verloren; zugleich wurde ein fremder Jahrestag anhand
des Namens verknüpft und dessen Datum überschrieben. Die Herkunftsfelder
blieben zwar als unbekannte Felder erhalten, ihre Geburtstagspolitik wurde
von der gemeinsamen Logik nicht beachtet. Die bisherige Mac-Projektion
korrigierte nur die erzeugte Mac-Oberfläche.

## Gemeinsame Korrektur

`magnolie-organizer/web/anwendung.js` und
`magnolie-organizer-windows/app/web/anwendung.js` implementieren jetzt
denselben engen Vertrag:

- Nur die drei genau passenden Marker aktivieren einen Geburtstag, der am
  Kontakt gespeichert bleibt. Herkunftsmetadaten erteilen keine Sync-Rechte.
- Normalisierung, Namenserkennung und Verknüpfung erzeugen keinen impliziten
  Jahrestag. Bereits ausdrücklich verknüpfte Jahrestage bleiben unabhängig.
- Das vorhandene Kontaktformular zeigt ein separates Datumsfeld mit dem
  Hinweis, dass daraus kein Kalendereintrag entsteht. Ungültige oder noch
  unvollständige Eingaben behalten Entwurf und Fokus und verändern keine Daten.
- Der gemeinsame Mutator und MCP behandeln `birth_date` unabhängig von
  ausdrücklich angeforderten `anniversaries`. Ein bewusst bearbeiteter
  Jahrestag ist weiterhin möglich.
- Die Kontaktkarte zeigt das Datum. Der ODS-Export verwendet den aktiven
  Kontaktgeburtstag und ersetzt ein leeres Datum nicht durch einen fremden
  namensgleichen oder verknüpften Jahrestag.
- Auch der tatsächlich geprüfte JSON-Kontaktimport über `mergeKontakte`
  verwendet den Vertrag. Dort bestand eine zusätzliche Umwandlung des
  Jahres 1604, die sonst trotz korrigierter Buchnormalisierung erhalten bliebe.
- Kontakte ohne passenden Marker behalten die bisherige Geburtstags- und
  Jahrestagslogik.

Die Mac-Projektion prüft jetzt **16 genaue kanonische Codeanker** und übernimmt
die gemeinsame Implementierung unverändert. Die doppelte Mac-Editor- und
Markerfunktion entfällt. Ein alter vollständiger Quellstand ohne diesen
Vertrag wird ausdrücklich abgewiesen. Historische Kalender-Adapterorakel und
ihre bytegenauen Inversentests bleiben erhalten; sie gelten nicht als Beleg für
eine vollständige aktuelle Oberfläche aus alten Produktquellen.

Zwei neue MsgIDs sind in beiden POTs sowie allen 19 PO-Katalogen beider
Desktop-Ausgaben enthalten. Die getrackten Windows-JS-Kataloge wurden mit dem
vorhandenen Generator erzeugt. Sie enthalten je zwei neue Übersetzungen;
`de.js` enthält zusätzlich die bereits zuvor in `de.po` vorhandene Übersetzung
`Restore media` → `Medien wiederherstellen`. Andere bestehende Nachrichten
und Pluralregeln blieben unverändert. PO/POT-Dateien wurden nur ergänzt.

## Tatsächlich ausgeführte Prüfungen

Umgebung: Linux, Node **24.22.3**, JSDOM **26.1.0**, GNU gettext **0.21**.
Die Tests verwenden tatsächliche Produktdateien, Formulare, Importprüfung,
MCP-Dispatch, Speichernachrichten und Wiederherstellungs-Callbacks.
Native Checkpoint-/Speicherantworten sind synthetisch.

| Prüfung | Ergebnis |
| --- | --- |
| `tests/contact-copy-birthday.js` | **321 Assertions**, 160 je Desktop-UI plus Prüfung beider Quellen; Exitcode 0 |
| `tests/birthday-display.js` | Bestehende Geburtstagsregressionen auf Linux- und Windows-UI bestanden; Exitcode 0 |
| Mac `test_additive_system_contact_copy_contract` | **246 UI-Prüfungen**, dazu 16 absichtlich zerstörte Anker abgewiesen; Exitcode 0 |
| Mac `test_occurrence_identity_current_ui_and_published_adapter_preserve_distinct_instances` | **29 UI-Prüfungen**, historische und aktuelle Adapterinversen sowie Abweisung des alten Vollstands; Exitcode 0 |
| Standard-PO-Compiler | **38 Kataloge** mit `msgfmt --check --check-format` kompiliert; beide neuen Schlüssel überall übersetzt; beide POTs enthalten jeden Schlüssel genau einmal |
| Generierte Windows-Kataloge | 19 Nachrichtenmengen und Pluralregeln gegen den Basiscommit geprüft; nur die oben genannten Ergänzungen |
| `git diff --check` | Bestanden |

Der neue Desktop-Test deckt Daten mit bekanntem Jahr, ohne Jahr, mit explizitem
Jahr 1604, den 29. Februar und ein leeres Datum ab. Er prüft tatsächlich
gesendete Speicherbytes und deren Wiederöffnung, Backup- und Journalrestore,
den regulären Editor samt ungültiger Eingaben, MCP samt Save-ACK, den bestätigten
JSON-Import, ODS-Datumswerte, Kontaktkarte und Druck ohne Mutation. Unverknüpfte
Namensvettern, ausdrücklich verknüpfte Jahrestage, passive Herkunft, öffentliche
Quellfelder, weitere unbekannte Felder und bestehende Erinnerungsregeln bleiben
erhalten. Ein gewöhnlicher Kontakt wird im bisherigen Ereigniseditor bearbeitet.

Die eingefrorene synthetische Austauschfixture liegt unter
`magnolie-organizer-windows/tests/resources/system-contact-copy-exchange-v1.json`.
Sie entspricht bytegenau der #775-Fixture unter
`Magnolie-Organizer-macOS-Beta/Tests/BetaCoreTests/Fixtures/system-contact-copy.json`
am Basiscommit. Der Desktop-Test benötigt dadurch auch im eigenständigen
Windows-Quellpaket keinen Mac-Entwicklungsordner.

Wiederholung aus dem Repository-Stamm nach Vorbereitung der vorhandenen
JSDOM-/gettext-Abhängigkeiten und der üblichen generierten Zeitzonendateien:

```sh
python magnolie-organizer/werkzeuge/zeitzonen_erzeugen.py
python magnolie-organizer/werkzeuge/zeitzonen_erzeugen.py --output magnolie-organizer-windows/app/web
node magnolie-organizer-windows/tests/contact-copy-birthday.js
node magnolie-organizer-windows/tests/birthday-display.js
python -m unittest discover -s Magnolie-Organizer-macOS-Beta/tests -p test_host.py -k additive_system_contact_copy_contract
python -m unittest discover -s Magnolie-Organizer-macOS-Beta/tests -p test_host.py -k occurrence_identity_current_ui_and_published_adapter_preserve_distinct_instances
git diff --check
```

Für externe bereits vorhandene Abhängigkeiten wurden `NODE_PATH` auf das
Desktop-`node_modules` und `MACOS_BETA_JSDOM` auf dessen `jsdom/lib/api.js`
gesetzt. Der bestehende `po_zu_js.py`-Generator kompiliert die Kataloge; Linux-
Webkataloge sind generierte Eingaben und müssen vor den UI-Prüfungen vorliegen.

## Weitere Befunde und offene Abnahme

Der zusätzliche Lauf von `tests/localization-completeness.js` **besteht nicht**:
`de: key set differs from POT`, weil `Restore media` schon am Basiscommit in
beiden deutschen PO-Dateien steht, aber in beiden POTs fehlt. Dieser
unabhängige Bestandsfehler wurde gemeldet und wird hier nicht durch Änderungen
an Medienfunktionen oder durch Abschwächen des Tests verdeckt. Die oben
aufgeführten Prüfungen der zwei neuen Übersetzungen bestehen separat.
`python -m pytest -q .../test_windows_pot_source_coverage.py` konnte mangels
installiertem pytest keine Tests ausführen und wird nicht als bestanden gezählt.

Die native Installation, reale Datenträgerdauerhaftigkeit und Bedienung unter
Linux/Windows sowie Swift/AppKit/WKWebView und Contacts.framework auf Intel-
und Apple-Silicon-Macs wurden hier nicht abgenommen. Es wurde kein Windows-
Quellarchiv oder installierbares Paket gebaut. Eine sprachliche Abnahme aller
19 Übersetzungen durch Muttersprachler wird aus der Compilerprüfung nicht
abgeleitet.

Bereits von alten Versionen veränderte oder erzeugte Jahrestage werden nicht
anhand von Namen nachträglich gelöscht oder repariert. Alte installierte
Versionen ohne diesen Patch kennen den Vertrag weiterhin nicht. Die Prüfung
belegt den lokalen Buch-/JSON-Vertrag und die genannten UI-Wege, keine neue
providerseitige Kontakt- oder Telefonsynchronisation. #779 bleibt eine getrennte
Austauschprüfung für Aufgaben und Notizen.
