# Internationalisierungsvertrag

Dieser Vertrag trennt übersetzbare Darstellung von dauerhaft stabilen Daten.
Er gilt für Oberfläche, Python-Kern, Importe, Synchronisation, Sicherungen und
Magnolienbaum.

## Basissprache und Kataloge

- Englische `msgid` sind die Basissprache.
- Deutsch wird vollständig in `po/de.po` gepflegt.
- Fehlende Übersetzungen fallen auf den englischen `msgid` zurück.
- Python verwendet kompilierte MO-Kataloge, WebKit einen daraus erzeugten
  JavaScript-Katalog.
- Sichtbare Texte werden als vollständige Sätze übersetzt; Anzahltexte
  verwenden Pluralformen.
- Pluralregeln werden als begrenzte Gettext-Ausdrücke interpretiert. Kataloge
  dürfen niemals mit `eval()` oder `Function()` JavaScript erzeugen; ungültige,
  überlange oder zu tief verschachtelte Regeln fallen auf `n != 1` zurück.

## Unveränderliche Werte

Folgende Werte dürfen weder übersetzt noch von der aktiven Sprache abhängig
gemacht werden:

- JSON-Schlüssel und gespeicherte Enum-Werte
- Befehle der WebKit-Brücke und Namen der `App`-Rückrufe
- D-Bus-Namen, Aktionen und Anwendungskennungen
- CLI-Optionen und Umgebungsvariablen
- Desktop-IDs, Systemd-Unit-Namen, Symbolnamen und Dateipfade
- ICS-, vCard-, LDIF-, XML-, MIME- und Lotus-Kompatibilitätsschlüssel
- Magnolienbaum-Nachrichtentypen, HTTP-Pfade und kryptografische Kennungen
- Anbieter-IDs für Karten, Wetter, soziale Medien, Flatpak und Snap

Benutzerdaten und importierte Texte werden niemals automatisch übersetzt.

## Regionale Einstellungen

Sprache, Formatgebiet, Stundenformat und Zeitzone sind getrennte Werte:

- `language`: Oberflächensprache oder `system`
- `formatLocale`: Datums-, Zahlen- und Sortierregeln oder `system`
- `hourCycle`: `system`, `h12` oder `h23`
- `firstDayOfWeek`: `locale`, `monday`, `sunday` oder `saturday`
- `weekRule`: zunächst `iso`
- `temperatureUnit`: `system`, `celsius` oder `fahrenheit`
- `timeZone`: IANA-Zeitzone oder `system`

Linux übernimmt für bestehende Installationen weiterhin das deutsche
Bestandsprofil. Windows folgt bei neuen Installationen zunächst den
Systemeinstellungen. Beide Plattformen speichern eine ausdrückliche Auswahl
früh und getrennt von den verschlüsselbaren Benutzerdaten in `locale.json`.

## Datenmigration

- Bestehende Termine mit Uhrzeit bleiben schwebende lokale Uhrzeiten.
- Ganztägige Termine bleiben reine Datumswerte.
- Bestehende Namen wie `Allgemein` oder `Lose Notizen` werden nicht umbenannt.
- Datenfassung 3 speichert kontrollierte Werte als stabile englische IDs,
  darunter Wiederholungen, Jahrestags- und Feiertagsarten, Papierkorbarten,
  Typografie-, Ansichts-, Erinnerungs-, Wetter-, Sortier- und Traywerte.
- Deutsche Werte aus älteren Datenfassungen bleiben als historische Aliase
  lesbar. Freie Jahrestagsarten, Kontaktbezeichnungen und andere Benutzerdaten
  bleiben unverändert.
- ICS, vCard, Lotus und andere Fremdformate werden an ihren Grenzen auf die
  stabilen IDs abgebildet. Wo bestehende Fremdprogramme sie benötigen, werden
  zusätzliche Legacy-Felder ausgegeben; autoritativ sind die ID-Felder.
- Fachliche Dubletten- und Zusammenführungsschlüssel verwenden eine
  locale-unabhängige Unicode-Kanonisierung statt der aktiven Anzeigesprache.
- Ein Sprachwechsel darf gespeicherte Daten oder Synchronisationsnutzlasten
  nicht verändern.

## Freigaberegeln

Eine neue Sprache darf nur ausgeliefert werden, wenn ihr Katalog syntaktisch
gültig ist. Deutsch darf nur mit vollständigem, nicht als unscharf markiertem
Katalog veröffentlicht werden. Vor jeder Freigabe laufen die deutschen
Regressionstests sowie sprachneutrale Daten-, Import- und Protokolltests.
