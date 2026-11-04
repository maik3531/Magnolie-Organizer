# Müllkalender und Feiertage (Refs #380)

Ein manuell eingegebener Abstand von beispielsweise sieben Tagen ist eine
Rechenregel, kein kommunaler Abfuhrplan. Er kann deshalb auch Neujahr treffen.
Eine Feiertagsliste enthält weder den tatsächlichen Ausfall noch den Ersatztermin
der zuständigen Abfuhr. Magnolie darf daraus kein neues Abholdatum erfinden.

Für veröffentlichte kommunale Termine besteht unter **Einstellungen → Kalender →
Müllkalender** die native Auswahl **ICS / CSV importieren…** mit Vorschau und
ausdrücklicher Übernahme. Importierte Einzeltermine und iCalendar-Ausnahmen haben
Vorrang vor einer neu erfundenen Regel: `EXDATE` lässt ein Vorkommen aus, ein
zusätzlich geliefertes `RDATE` setzt den belegten Ersatztermin. Ein `EXDATE` ohne
Ersatz erzeugt keinen geratenen Folgetag. Importierte Gruppen verwenden keine
zusätzlich darübergelegte manuelle Intervallregel.

Sechs duale Desktopfälle prüfen den Unterschied: manuelles Wochenintervall über
Neujahr, kommunales EXDATE mit ausdrücklichem Ersatz am 2. Januar und EXDATE ohne
Ersatz. Quelle und normale Terminliste bleiben dabei unverändert. Das bestätigt
die vorhandene Auswertung, nicht die Richtigkeit einer unbekannten Kommune.

Der weitergeleitete Bericht nennt noch keine Kommune, Quelle, Jahresfassung oder
Importart. #380 bleibt für diese Klärung und die gezielte manuelle
Ausnahme-/Ersatzbedienung im eigenständigen Müllkalender offen. Die neue
Einzel-Löschung normaler Terminserien aus #379 ist kein behaupteter Ersatz für
eine solche Müllkalenderfunktion.
