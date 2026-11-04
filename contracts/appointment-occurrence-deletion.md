# Einzelnes Terminserien-Vorkommen löschen (Refs #379)

Beide Desktop-Editoren unterscheiden ausdrücklich **Nur dieses Vorkommen löschen**
von **Terminserie löschen**. Die Einzelaktion bezieht sich auf das ursprünglich
angeklickte Vorkommen, nicht auf nachträglich bearbeitete Datumsfelder. Abbruch
ändert nichts; eine zwischenzeitlich geänderte Terminversion führt zum Konflikt.

Die Einzelaktion erhält Master, UID, Wiederholungsregel und spätere Vorkommen.
Sie erzeugt keinen Serien-Löschtombstone. Lokale einfache Serien verwenden die
bestehenden datumsbezogenen `icsAusnahmen`; iCalendar-Serien erhalten ein gezieltes
`EXDATE` anhand der ursprünglichen `icsOccurrence`-Identität. DATE bleibt DATE,
absolute DATE-TIME verwendet UTC, floating DATE-TIME bleibt floating in der vom
bestehenden Expander verwendeten eigenen Zeitzone. Unterschiedliche Uhrzeiten
eines Tages werden bei iCalendar nicht gemeinsam ausgeschlossen.

Der Papierkorbeintrag hat weiterhin `art: appointment`, archiviert den bisherigen
Master und nennt dessen ID in `parent_id`. `appointment_occurrence` enthält nur
das hinzugefügte Feld (`icsAusnahmen` oder `icsRoundtrip`) und seinen exakten Wert.
Die Normalisierung erhält diesen Beleg. Wiederherstellen entfernt ausschließlich
diese Ausnahme, erhält andere Ausnahmen und zwischenzeitliche Titeländerungen
und erzeugt keinen zweiten Serienmaster. Fehlender Beleg, verschwundener oder
schreibgeschützter Master oder veränderte Serienidentität/-regel sperren Restore,
statt historische Daten über den aktuellen Stand zu schreiben. Endgültiges
Entfernen dieses Papierkorbeintrags entfernt nicht die aktuelle Serienausnahme.

Bei deaktiviertem Papierkorb bleibt die ausdrückliche Bestätigung
„Papierkorb deaktiviert: Die ausgewählten Einträge endgültig löschen?“ erhalten.
Die Einzelaktion erweitert weder bestehende Feldgrenzen noch Read-only-Rechte.
Eine alte strukturierte Serie mit mehreren individuellen Uhrzeiten wird nicht
durch eine ungenaue Datums-Ausnahme verändert; ohne echte projizierte
iCalendar-Instanzidentität wird ebenfalls keine Einzelaktion angeboten.

Nachweis: 26 duale Desktop-Quellhostfälle einschließlich Abbruch, erster Instanz,
DATE/UTC/TZID/floating, fremder floating-Anzeigezone, zweier Uhrzeiten pro Tag,
Papierkorb-Rundlauf, fehlendem Restorebeleg, geänderter Serie, Read-only und
gesonderter Serienlöschung. 44 vorhandene native iCalendar-/Zeitzonenfälle,
vollständige Linux-UI, Windows-Web-Smoke und duale Zustandsregressionen bestanden.
Vier neue Texte sind in allen 19 vorhandenen Sprachen beider Desktops enthalten.
Das ist keine installierte Paket-/Live-Provider-Abnahme und keine Aussage über
die noch unbekannte konkrete Kalenderquelle des weitergeleiteten Nutzerberichts.
Die native Provider-/Randfallabnahme und die bewusst ausgesparten alten
Mehrfach-Uhrzeiten werden unter #382 weitergeführt.

## Optionaler Ersatztermin (Refs #383)

Die Bestätigung der Einzel-Löschung bietet jetzt optional **Ersatztermin anlegen**.
Der Schalter ist anfangs aus; ohne Auswahl bleibt es bei der reinen Ausnahme.
Datum und gegebenenfalls Uhrzeit werden ausdrücklich gewählt. Die angezeigte
Uhrzeit und Zeitzonenbeschriftung verwenden die eigene Zeitzone. Der Ersatz wird
als **eigenständiger einmaliger Termin** mit neuer ID/UID angelegt; der Dialog
erklärt ausdrücklich, dass die Serie ihren bisherigen Rhythmus behält.

Vor der ersten Mutation werden Ausnahme, aktueller Serienstand und vollständiger
Ersatz geprüft. Abbruch, ungültige Eingabe, zwischenzeitliche Änderung oder eine
nicht existierende lokale Uhrzeit lassen die Ausgangsdaten unverändert. Dauer
(auch sekundengenau oder über eine Zeitumstellung), ganztägige Tageslänge und
gewöhnliche Terminfelder bleiben erhalten. Zeitgebundene Ersatzeinträge speichern
ihre exakten neuen UTC-Zeitfelder im üblichen iCalendar-Roundtrip; sie übernehmen
keine Serienregel, Serien-UID oder historischen Providerbindungen.

Der Papierkorbbeleg archiviert zusätzlich den geplanten Ersatzeintrag.
Wiederherstellen entfernt beide zusammen nur bei einem unveränderten,
weiterhin lokalen Ersatzeintrag und unveränderter Serienform. Ein bearbeiteter,
fehlender, bereits synchronisierter oder einem Provider zugeordneter Ersatz
bleibt mitsamt Ausnahme gesperrt, statt fremde Änderungen oder unsicher
veröffentlichte Termine zu löschen. Der native Provider-/Rücknahme-Rest bleibt
in #382; keine plattformübergreifende Providertransaktion wird behauptet.

28 duale Ersatzterminfälle prüfen lokale/UTC/TZID-Quellen, deutsche Bedienung,
präzise Dauer, ganztägige Länge, DST-Lücke/-Dauer, Abbruch, ungültige und veraltete
Eingabe, gekoppelte Rücknahme, Provider-HOLD und tatsächliches Wiederöffnen.
Die bestehenden Einzel-Löschfälle und Desktopregressionen bleiben zusätzlich
geprüft. Drei neue Texte sind in allen 19 Sprachen beider Desktops enthalten.
