# Import und Export: Abdeckung, Befunde und Grenzen

Dieser Bericht ergänzt die vollständige Issue-Sichtung um die ausdrückliche Anforderung, Datentypen, Wiederholungen, Geburtstage, Farben und alle übergebenen Felder zuverlässig zu bewahren. Alle hier erzeugten Daten sind synthetisch. Ein bestandener gezielter Test ist keine Garantie für jede beliebige Fremddatei oder jedes private Originalbuch.

## Geprüfte Datenwege

| Bereich | Tatsächliche Prüfung | Aussage und Grenze |
| --- | --- | --- |
| Lotus-/CSV-Kontakte und Aufgaben | Vorhandene gemeinsame CSV-Vektoren in beiden Desktop-Codecs; mehrere Adressen, HOME-/WORK-Zuordnungen, Kontakte und Aufgaben | #566 bestätigt und eng korrigiert. Der private Originalbericht bleibt separat offen. |
| ICS-Termine, Aufgaben und Jahrestage | Tatsächliche Python-/C#-Parser und Exporter; eindeutige Typmarker, einfache und komplexe Serien, Ausnahmen, RDATE und Farben | Typzuordnung anhand vorhandener Bedeutung; keine bloße Gleichsetzung „jährlich“ mit Geburtstag. Bestätigte Nachträge #844 und #845 sind gesondert belegt. |
| VCF und Kontaktfelder | Vorhandene Import-/Exportverträge, Personen-/Rollenfelder, Typ-/Kategorie-Trennung, wiederholte VCF-Zyklen | Bewahrt die getesteten Felder und ihre Bedeutung; kein behaupteter Allformatbeweis für unbekannte Erweiterungen. |
| Unicode und Kodierung | CSV-/Native-Import-Regressionen sowie C#-UTF-16-Prüfgruppe | Eingaben und tatsächliche Codecs getestet; keine bloße Zeichenkettenprüfung eines nachgebauten Parsers. |
| Thunderbird, KDE, LDIF, Claws und Lotus | Bestehende reale Format-/Export-Codecs und Schematests; KDE-Vorschau über die echten UI-Quellen | Die UI-Prüfung kontrolliert Vorschau, Bindung an Quelle/Peer, Speichern und Fehlerfälle. Native Verbindungen werden im Host simuliert. |
| OR6 | Tatsächliche Native-/Extension-Fixtures sowie vorhandene Regional- und Quelltextfälle | Bereits bekannte Bedeutung wird bewahrt. Unbekannte private OR6-Semantik wird nicht als korrekt interpretiert behauptet. |
| Vollständiges `.magnolie`-Archiv | Python- und C#-Gesamtarchivgruppen | Archiv-/Wiederherstellungspfade im Host geprüft, keine reale Geräte- oder Dateidialogabnahme. |
| Notizanhänge | Echte JavaScript-Import-/Speicher-/Wiederöffnenpfade für beide Desktopoberflächen, unabhängig als PNG/PDF lesbare Testdateien | Dateiinhalte und Dublettenverhalten geprüft. Native Speicherbestätigung im UI-Host wird simuliert. |
| Provider und Serienidentität | 7 JVM-Codec-/Migrationsfälle; je 29 Fälle mit projizierten macOS-/Tablet-Oberflächen; tatsächlicher Python-Sidecarfall | Sonderbelege auf dem ursprünglichen Prüfstand. Keine native Apple-/Android-Kalenderfreigabe. Quellenstände stehen in den jeweiligen Manifesten. |

Die vorhandene direkte Python-Dateivertragsprüfung umfasst **26 Prüfungen**. Die zusätzlichen bestehenden Python-Semantiksuiten bestanden zunächst mit **203 Fällen** und nach der ersten upstream Farbübernahme mit **220 Fällen**; die CSV-/Wiederherstellungsprüfung bestand mit **155 Fällen**. Der #844-Nachtrag wurde außerdem mit **47 fokussierten Pythonprüfungen**, **15 bestehenden Geburtstagsfällen**, **24 neuen DOM-Modellfällen** und **48 tatsächlichen Codec-/Speicherketten** geprüft. Die abschließende Integration erweitert die bestehenden Semantikläufe um die konkreten #844-/#845-Regressionen; genaue Quellen, tatsächliche Fallzahlen und Logs stehen in [final-integration-summary.json](final-integration-summary.json). Diese teils überlappenden Zahlen werden nicht mit Prüfanweisungen innerhalb einzelner C#-Gruppen oder UI-Programme zu einer scheinbar einheitlichen Gesamtfallzahl addiert.

## Typen und Wiederholungen

Die gezielten Kalendervektoren enthalten folgende Abgrenzungen:

- Ein explizit gekennzeichneter Geburtstag bleibt im Bereich `jahrestage` mit `typ=birthday`.
- Ein Geburtstag ohne bekanntes Jahr mit `--02-29` bleibt ein solcher Geburtstag.
- Ein gewöhnlicher Termin mit jährlicher Wiederholung bleibt im Bereich `termine` mit jährlicher Wiederholung.
- Die geprüften Lotus-Jahrestagshinweise ohne eindeutige Geburtstagsbedeutung machen einen normalen Termin nicht automatisch zum Geburtstag. Das vorhandene einmalige beziehungsweise jährliche Verhalten bleibt erhalten.
- Wöchentliche Serien mit ausgeschlossenen Terminen sowie ausdrückliche zusätzliche Wiederholungstermine behalten ihre Serieninformationen. Komplexe Rohdaten werden nicht durch eine einfachere, aber falsche Annahme ersetzt.
- Unbekannte Eigenschaften innerhalb einer Kalenderkomponente werden, soweit vom bestehenden Roundtrip-Modell getragen, als solche erhalten. Eine Eigenschaft auf Kalenderebene darf nicht in einen Termin verschoben werden und dort eine andere Bedeutung bekommen.

Die Vektoren stehen in [calendar-vectors.json](import-export/calendar-vectors.json). Die Vorherproben verwenden die tatsächlichen Produktcodecs unter [import-export/before](import-export/before).

## Bestätigter CSV-Verlust: #566

Der CSV-Import behandelte zusätzliche Kontaktfelder und Adressrollen unvollständig: Windows übernahm unter anderem nur die erste Adresse beziehungsweise verlor HOME-/WORK-Zuordnungen; Linux konnte HOME-Felder falsch beziehungsweise gemischt zuordnen. Der vorbereitete Patch erhält die vorhandenen Felder in beiden Implementierungen.

Der Nachweis basiert auf acht Kontaktvektoren, vierzehn Aufgabenzeilen und drei VCF-Zyklen sowie den bestehenden Wiederherstellungs-/Save-Verträgen. Der konkrete Fix gehört zu #566; eine vollständige native Abnahme des historischen privaten Datensatzes wird nicht daraus abgeleitet.

## Vollständige Kontaktübernahme: #823 bereits in main

Der während dieser Sichtung vorbereitete Teil zur vollständigen Übernahme von `kontaktpersonen` wurde zwischenzeitlich mit `50b1512234a765635f82af4537f277594fbf9878` nach `main` übernommen. Die beiden Produktänderungen stimmen mit dem geprüften Vorschlag überein; ergänzte Rollen wurden upstream weiter getestet. Der Patch wird deshalb nicht nochmals in die empfohlene Serie aufgenommen.

## Kalenderfarben: #844

Die zusätzliche Probe bestätigte eine tatsächliche Lücke: gültige Standardfarben wie `COLOR:turquoise` in VEVENT und `COLOR:RED` in VTODO blieben zwar zum Teil im ursprünglichen Kalendertext erhalten, wurden aber nicht in die sichtbare Akzentfarbe umgesetzt. `COLOR` beziehungsweise `X-APPLE-CALENDAR-COLOR` auf VCALENDAR-Ebene konnten vollständig verloren gehen.

Die erste Korrektur wurde während der Prüfung mit `8c99834367cc59c7bf936dd630e86a3194304f96` upstream übernommen. Sie ist bereits Teil der finalen Patchbasis. Der eigene Nachtrag behandelt vier unabhängig bestätigte Reste:

- Geburtstage und andere Jahrestage erhalten ebenfalls Komponentenfarbe und Kalender-Vorgabe. Das gilt für die tatsächlichen Codecs, die Normalisierung, den Speicherinhalt, den Export sowie Kalender, Liste, Jahresplaner und Druckmodelle.
- Eine unveränderte `COLOR;X-SOURCE=…`-Zeile mit fremden Parametern bleibt auch dann erhalten, wenn eine eigene wirksame Farbübersteuerung vorliegt. Bewusstes Ändern oder Löschen reaktiviert diese alte Farbe weiterhin nicht.
- Ältere Importdaten ohne das neu eingeführte optionale Kalenderfarbfeld bringen den vorhandenen UID-/Serieninstanzabgleich nicht mehr zum Abbruch. Fehlende Werte und ausdrücklich leere Werte bleiben unterscheidbar.
- Ein durch die erste Farbübernahme eingeführter lokaler Variablenname verdeckte die Übersetzungsfunktion. Ungültige beziehungsweise unvollständige ICS-Dateien erreichen wieder die beabsichtigte Fehlerbehandlung.

Die bestehende Rangfolge ist eigene Magnolie-Farbe vor expliziter Komponentenfarbe vor Kalender-Vorgabe. Typ, Geburtstagssymbol und unbekanntes Geburtsjahr bleiben eigenständig. Es werden weder ein neuer Farbdialog noch zusätzliche Bestätigungen eingeführt. Der Nachtrag wurde an die später ebenfalls übernommene erste #845-Korrektur angepasst und erhält deren Funktion. [Aktueller #844-Nachtrag](import-export/after-7a490dd8-844/README.md), [48 reale Speicherketten am aktuellen integrierten Stand](import-export/final-tail-pipeline/pipeline-manifest.json) und [unabhängige Prüfung der aktuellen Anpassung](import-export/after-7a490dd8-844/independent-review.json).

## Explizite Nextcloud-Geburtstage: #845

Die zusätzliche Nextcloud-Frage führte zu einem zweiten konkreten Importbefund: `X-NEXTCLOUD-BC-FIELD-TYPE:BDAY` wurde in beiden Desktop-Codecs nicht als Geburtstagsbedeutung ausgewertet. Ein ausdrücklich markierter Geburtstag blieb ein gewöhnlicher Termin. Bei unbekanntem Geburtsjahr blieb das technische Ankerjahr sichtbar. Die Rohmarker gingen dabei nicht verloren; fehlerhaft war ihre fachliche Auswertung.

Die Grundkorrektur wurde inzwischen mit `7a490dd87e94eec08d7f09cb95a04b34bf4621c2` upstream übernommen. Sie verwendet eindeutige Marker aus dem tatsächlichen Nextcloud-Generator und bleibt unverändert erhalten. Sie erfindet keine Geburtstage anhand eines Titels, eines Kalendernamens oder einer bloß jährlichen Wiederholung. Bekanntes Jahr und fehlendes Jahr bleiben verschieden; die echten Anker 1970 beziehungsweise 1972 bei unbekanntem Jahr sind kein Geburtsjahr. Die Nextcloud-Regel für den 29. Februar wiederholt am letzten Februartag und muss beim Speichern und Export erhalten bleiben.

Mehrdeutige oder widersprüchliche Typ-/Jahresmarker und nicht als einfacher Jahrestag darstellbare Serien dürfen nicht still vereinfacht werden. Dazu gehören abweichende einzelne Serieninstanzen. Eine bewusste spätere Typänderung darf beim Export keine widersprüchliche alte Geburtstagskennung übrig lassen. Diese Grenzen wurden in der Übernahme geprüft. Der verbleibende enge Nachtrag bewahrt zusätzlich die Bedeutung der Schalttagsregel bei einer solchen Typänderung mit unverändertem Datum und schließt die folgende DAV-Auslassung.

Ein weiterer tatsächlicher C#-Gegenfall wurde über Import → Export → Ergänzung einer getrennten Ausnahme reproduziert: Durch die beim Export ergänzte eigene Geburtstagskennung konnte der Master noch als ausnahmsloser Jahrestag erhalten bleiben. Ein zusätzlicher einzelner Guard bindet auch diesen Pfad an die bereits vorhandene Nextcloud-Serienprüfung. Dieselben tatsächlichen Testdaten schlugen vorher fehl und bestanden danach; ohne Ausnahme bleibt der gewöhnliche Geburtstag erhalten. Die ursprüngliche alternative Gesamtimplementierung ist nur noch Historie. [Aktuelle Nachträge und genaue Belege](providers/nextcloud-caldav-evidence/issue-845/upstream-remainder/README.md).

**Die Dateiimportkorrektur ist kein vollständiger Linux-CalDAV-Jahrestagsabgleich.** Dieser Rest bleibt in #441. Auf dem tatsächlich übernommenen Stand wurde ein entsprechender BDAY-Datensatz korrekt gelesen, aber vom reinen Linux-Termin-Sync ausgelassen, während der Lauf Erfolg meldete. Der neue enge Schutz weist diesen nicht vollständig unterstützten Jahrestagsbereich vor Schreib- oder Löschaktionen ausdrücklich zurück. Er verhindert eine falsche Erfolgsmeldung und stilles Auslassen; er behauptet keine fertige #441-Integration. [DAV-Bericht](providers/nextcloud-caldav-README.md).

Zusätzlich muss der ursprüngliche Datenweg stimmen: Nextclouds automatisch erzeugter Geburtstagskalender wird aus den Geburtstagsdaten der Kontakte gebildet und lässt sich nicht wie ein gewöhnlicher Kalender direkt bearbeiten. Änderungen an solchen Quelldaten gehören zum Kontakt-/CardDAV-Weg. Ein exportierter Geburtstagseintrag und der zugrunde liegende Kontakt sind daher zwei zusammenhängende, aber verschiedene Ressourcen. [Offizielles Nextcloud-35-Handbuch, Geburtstagskalender](https://docs.nextcloud.com/server/stable/user_manual/en/groupware/calendar.html#birthday-calendar).

## Sind weitere Import-/Exportformate zwingend nötig?

Für die geprüften Nextcloud-Abläufe sind ICS und vCard bereits vorhanden. Auch CSV, LDIF, Claws, Thunderbird und Lotus/OR6 haben konkrete bestehende Wege. Aus dieser Sichtung ergibt sich kein zwingend fehlendes weiteres Dateiformat. Die nachgewiesenen dringenden Lücken betreffen korrekte Bedeutung, vollständige Feldübernahme und Ende-zu-Ende-Verhalten der vorhandenen Formate.

Ein zusätzlicher Import etwa aus einem weiteren proprietären Programm wäre erst mit dessen konkretem Datenformat, einer gewünschten Datenart und einem repräsentativen Beispiel sinnvoll zu priorisieren. Er würde die offenen Typ-, Farb- und CalDAV-Abläufe nicht ersetzen.

## Nachweise und bekannte Prüfhilfengrenzen

- [Ursprüngliche zusätzliche Semantikprüfung](import-export/root/manifest.json) und [korrigierter Thunderbird-Aufruf](import-export/root/thunderbird-runner-followup.json).
- [Archiv- und Anhangsprüfung](import-export/archive-attachments/manifest.json) und [korrigiertes Archiv-Arbeitsverzeichnis](import-export/archive-attachments/archive-runner-followup.json).
- [CSV-/Wiederherstellungsprüfung](validation/after-50b15122/manifest.json).
- [Provider-Sonderprüfungen](special-tests/providers/README.md).

Die zwei korrigierten Aufrufe verwendeten zunächst ein falsches Quellen- beziehungsweise Arbeitsverzeichnis. Der gleiche unveränderte Produktcode bestand nach der reinen Aufrufkorrektur. Die ersten Logs wurden nicht überschrieben und nicht als echte Produktfehler ausgegeben.

## Verbleibende Abnahme

Die Typ-/Farb-/Feldtreue wurde in #113 als verbindliche Abnahmebedingung ergänzt. Reale installierte Anwendungen, Systemkalender, Gerätekombinationen, native Dateidialoge und private Originaldateien benötigen weiterhin ihre dafür vorgesehenen Abnahmen. Vollständige Erhaltung unbekannter Eigenschaften auf VCALENDAR-Ebene erfordert eine dazu passende Datenstruktur; solche Eigenschaften dürfen nicht unbemerkt in den falschen Geltungsbereich umgedeutet werden.
