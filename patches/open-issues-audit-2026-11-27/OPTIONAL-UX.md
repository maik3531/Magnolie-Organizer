# Optionale Bedienverbesserungen zur Entscheidung

Diese sieben Ideen wurden weder umgesetzt noch als neue Issues angelegt. Sie ergänzen vorhandene Abläufe. Die bestätigten Fehlerkorrekturen und die geforderte Daten-/Dauerbetriebsqualität hängen nicht von einer Entscheidung über diese Erweiterungen ab.

| Vorschlag | Konkreter Nutzen | Kleiner sinnvoller Umfang |
| --- | --- | --- |
| **Sichtbare Suche nach Programmfunktionen** | Wer etwa „Kontakt importieren“, „Drucken“ oder „Sicherung wiederherstellen“ sucht, findet die vorhandene Funktion, ohne deren Platz im Menü kennen zu müssen. | Ein sichtbarer Einstieg, der bestehende Ansichten öffnet. Tastenkürzel höchstens ergänzend. Suchen führt noch keine Aktion aus. |
| **Benannte Such- und Filteransichten** | Häufige Auswahlen wie „Aufgaben für Familie“ müssen nicht jedes Mal neu zusammengestellt werden. | Nur Auswahlbedingungen speichern und aktuelle Treffer neu berechnen; keine weitere Kopie der Daten. |
| **Druckauswahl „Nur Tage mit Einträgen“** | Ein kompakter Monatsnachweis gelingt mit einer Auswahl statt vielen einzelnen Häkchen. | Zusätzlicher Druckfilter neben vorhandener Gesamtauswahl und Einzelwahl. |
| **Benannte Vorlagen für wiederkehrende CSV-Importe** | Spaltenzuordnung und Datumsformat müssen bei gleich aufgebauten Dateien nicht wiederholt eingegeben werden. | Zunächst der vorhandene Abfuhrkalender-CSV-Weg; Vorlage auswählen, bestehende Vorschau verwenden. Abweichende Spalten müssen sichtbar bleiben. |
| **Verständliche Übernahmeanzeige** | Lesbare Zustände wie „hier gespeichert“, „auf dem Telefon übernommen“ oder „wartet auf Verbindung“ ersparen Nachfragen und wiederholtes Auslösen. | Rein lesende Darstellung tatsächlich passender Quittungen. Erreichbarkeit allein darf nicht als erfolgreiche Speicherung erscheinen. Keine neue Bestätigung durch den Nutzer. |
| **Eigene Favoriten für Arbeitsarten** | Wiederkehrende Bezeichnungen wie „Fahrt“, „Beratung“ oder „Support“ lassen sich mit einer Auswahl einsetzen. | Einige persönliche Favoriten neben den vorhandenen Vorgaben und freier Eingabe. |
| **Einmalige geführte Interneteinrichtung** | Der Nutzer muss nicht selbst herausfinden, ob Hin- und Rückweg zwischen Organizer und Notes funktionieren. | Einen gewählten erreichbaren Zugang einmal einrichten, beide Richtungen automatisch prüfen und verständlich anzeigen, worauf gewartet wird. Keine zusätzliche Bestätigung normaler Änderungen. Ein neuer Vermittlungsdienst wäre ein eigener größerer Entwurf. |

Für Menschen mit wenig Technikkenntnis würde ich zuerst die verständliche Übernahmeanzeige und eine geführte Interneteinrichtung ansehen. Die sichtbare Funktionensuche hilft bei selten verwendeten Funktionen. Die Druckauswahl ist ein besonders kleiner, klar abgegrenzter Komfortgewinn. Diese Reihenfolge ist eine Empfehlung, keine bereits beschlossene Umsetzung.

## Quellen und Abgrenzung

- [Suche und benannte Filter: tatsächliche bestehende UI, Nutzen und Grenzen](desktop/optional-ux-proposals.json).
- [Druckauswahl und Arbeitsarten: bestehende Notes-Oberflächen](media/optional-ux-proposals.json).
- [Übernahmeanzeige und CSV-Vorlagen: bestehende Quellen mit konkreten Codeankern](providers/optional-ux-proposals.json).
- [Internet-/Notes-Einrichtung: vorhandene Wege, Eingaben und Grenzen](internet-notes/README.md).

Vorhandene Geräte-/Syncanzeigen, der vorhandene Kalenderimport und die bestehende Forderung nach einfacher Zeitzonenbedienung in #258 werden nicht nochmals als neue Funktion angeboten. Bei der Übernahmeanzeige muss vor einer Umsetzung je Datenbereich geklärt sein, welche dauerhafte Gegenstellenquittung tatsächlich verfügbar ist; die Idee behauptet noch keine überall fertige technische Quittungskette.
