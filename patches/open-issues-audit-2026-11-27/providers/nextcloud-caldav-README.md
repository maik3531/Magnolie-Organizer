# Nextcloud, CalDAV und CardDAV: aktueller Prüfstand

Ursprünglicher Auditstand: `1f1f3225ab50fe38902bc8e790454fd944f8b693`; abschließender begrenzter Upstream-Abgleich: `7a490dd87e94eec08d7f09cb95a04b34bf4621c2`, 27. November 2026.

**Aktualisierung:** Die BDAY-Grundklassifikation wurde unabhängig in `7a490dd8` übernommen. Der frühere Alternativpatch `8d7263fd` ist historisch und darf nicht erneut angewendet werden. Maßgeblich sind der [Upstream-Abgleich](nextcloud-caldav-evidence/issue-845/upstream-adoption.json) und die [aktuelle Folgelieferung](nextcloud-caldav-evidence/issue-845/upstream-remainder/README.md). Drei konkrete Reste wurden bestätigt: Linux-DAV lässt einen korrekt erkannten Geburtstag aus; eine Typ-/Jahresänderung am unveränderten 29. Februar verliert die besondere Monatsende-Regel; ein tatsächlich exportierter normaler C#-Geburtstag kann trotz später ergänzter separater Serienausnahme als ausnahmsloser Jahrestag eingeordnet werden.

Die geprüften Folgecommits `559c5c1f` und `573905f5` behandeln diese drei Reste. Auf dem ersten Folgecommit bestanden 25 Pythonfälle sowie die C#-Geburtstags- und DAV-Gruppe jeweils 1/1. Der zweite Commit ergänzt genau den normalen C#-Import→Export→Serienausnahme-Fall: identische neue Regression vorher rot und danach grün, normale Kontrolle ohne Ausnahme weiterhin grün. Die folgenden ursprünglichen Testzahlen bleiben an ihren ausdrücklich genannten Stand gebunden.

**Linux und Windows besitzen wesentliche DAV-Funktionen. Eine Zusage, dass alle Nextcloud-Flüsse reibungslos funktionieren, wäre trotzdem nicht gedeckt.** Discovery, ausgewählte Quellen, VEVENT/VTODO, CardDAV, bedingte ETag-Schreib-/Löschoperationen und Konflikt-/Baseline-Schutz sind vorhanden. Die tatsächlichen Grenzen stehen in `nextcloud-caldav-audit.json`; Befehle, Eingangsdateihashes und vollständige Logs liegen unter `nextcloud-caldav-evidence/`.

## Was tatsächlich fehlt

- **#845 – Grundkorrektur übernommen, geprüfte Nachträge für drei Reste:** Auf der ursprünglichen Basis behandelten beide Codecs ein ausdrücklich mit `X-NEXTCLOUD-BC-FIELD-TYPE:BDAY` gekennzeichnetes Birthday-VEVENT als jährlichen Termin. Die Rohmarker blieben erhalten; fehlerhaft waren Typzuordnung und Auswertung des fehlenden Geburtsjahrs. Diese Grundkorrektur ist seit `7a490dd8` übernommen. Der frühere Vorschlag `8d7263fd` auf `a6462407` und seine 44 Pythonfälle sind ausschließlich historische Nachweise, kein aktueller Anwendungspatch. Aktuell vorgesehen sind nur die Folgecommits `559c5c1f` und `573905f5` mit den oben beschriebenen drei Restfällen; [Patchreihenfolge und genaue Prüfstände](nextcloud-caldav-evidence/issue-845/upstream-remainder/delivery.json) sind separat gebunden. Die primär belegte Nextcloud-Serie für den 29. Februar ist `FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=-1`, also auch der 28. Februar in Nichtschaltjahren. Eine bloße jährliche Februar-29-Serie darf nicht still entsprechend umgedeutet werden.
- **#441 – Linux-Jahrestagssynchronisierung:** Vollständiger typisierter CalDAV-Abgleich mit Quellen/UID/ETag, Baselines, gemischten Ressourcen, Konflikten und Löschungen fehlt weiterhin. Der vorhandene Schutz stoppt vor unvollständigen Kalenderwrites. Der Codecpatch darf diesen Schutz weder entfernen noch Daten still aus dem Sync fallen lassen.
- **#683 – reale Server- und Portabnahme:** Farben setzen/ändern/leeren, If-Match/412, gleichzeitige Änderungen, ältere Baselines, fremde Parameter, Export/Reimport/weiterer Sync und Neustart mit dauerhaftem Buch-/Journalabschluss bleiben als konkrete Matrix offen. Mac besitzt DAV-Kontoeinrichtung und Bausteine; Android-Systemproviderkopien ersetzen keinen vollständigen direkten DAV-Sync.

## Ausgeführte Prüfungen

| Prüfung auf 1f | Ergebnis | Aussagegrenze |
|---|---|---|
| Vorhandene Python-DAV-/Farb-/Cleanup-/Kontaktfactory-Fälle | 194 bestanden, 4 fehlgeschlagen | Drei Fälle benötigen fehlendes gi/GLib. Ein tatsächlicher gettext-Fehler im ungültigen ICS-Pfad wurde von #844 in `a6462407` gezielt behoben und geprüft. |
| C# Nextcloud/CalDAV/CardDAV/Discovery/ETag/Sicherheit | 1/1 Gruppe bestanden | Kontrollierter Transport und synthetische Ressourcen; kein realer Nextcloud-Server. |
| C# Wildcard-ETag-/Versionsbindung | 1/1 Gruppe bestanden | Gezielte Versionsschutzprüfung. |
| C# Geburtstag-Dublettenbereinigung | Gesamtgruppe im Host blockiert | Named-Pipe-Socket mit Permission denied; kein Erfolg für die gesamte Gruppe behauptet. |
| Markerdiagnose in beiden Originalcodecs | Zwei falsche Typklassifikationen je Codec bestätigt | Beobachtungsrunner, nicht als grüne Regression zu zählen. |

Die ursprüngliche Diagnose-Fixture für einen jahrlosen 29. Februar enthielt nur `FREQ=YEARLY`. Sie belegt die fehlende Markerbehandlung, ist aber keine genaue Nachbildung des Nextcloud-Generators. Die #845-Regressionsfälle verwenden die tatsächlich erzeugte Monatsende-Regel. Bekannte Jahre vor 1970 und widersprüchliche Marker sind gesondert zu behandeln: `UNKNOWN-YEAR:1` darf nicht blind jede vorhandene echte Jahresangabe löschen.

## Volumen, Rechte und Offlinebetrieb

Beide Desktopwege lesen derzeit vollständige DAV-REPORTs. Linux fragt zwar `sync-token` in Discovery ab, führt damit aber keine inkrementelle `sync-collection`-Kette. Windows verwendet ebenfalls den Vollreport. Linux begrenzt Discovery auf 2 MiB und Report/Objekt auf 42 MiB; Windows XML/Report auf 16 MiB und einzelne Objekte auf 4 MiB. Daraus folgt keine bestandene 50.000-Objekte-Serverabnahme. Grenzen wurden nicht erhöht.

Bekannte schreibgeschützte Quellen werden geschützt. Die Kalender-Discovery ermittelt jedoch nicht dieselbe vollständige Privilegienlage wie der CardDAV-Kontaktweg. Geteilte/schreibgeschützte Nextcloud-Kalender, Kontorechtewechsel, App-Passwortwiderruf und echte Offlineänderungen mit späterem Konfliktabschluss benötigen gezielte Serverabnahme. Ein vorhandener HTTP-/Codec- oder gespeicherter Lokalerfolg ist nicht automatisch ein bestätigter Serverabschluss.

## Welche Formate sind prioritär?

Nextcloud benötigt hier kein zusätzliches proprietäres Dateiformat: ICS und vCard sind vorhanden. Auch CSV, LDIF, Claws und Lotus-OR6 besitzen bestehende Importwege. Der belegte dringende Rest betrifft korrekte Semantik und vollständige Abläufe in diesen Formaten. Weitere Formate wie PST lassen sich nur anhand eines zusätzlich gewünschten Quellprogramms als Bedarf begründen.

## Primärquelle und Grenzen

Maßgeblich für die Geburtstagssemantik ist die [Nextcloud-BirthdayService-Quelle](https://github.com/nextcloud/server/blob/1ab09ec753f106661beadee1794b390ebec455dd/apps/dav/lib/CalDAV/BirthdayService.php). Sie setzt bei unbekanntem Jahr den technischen Anker 1970 oder 1972; ein bekanntes ursprüngliches Jahr steht in `X-NEXTCLOUD-BC-YEAR`. Der Quellenhash steht im JSON. Die vollständigen fremden PHP-Dateien im Analysecache sind **nicht zur Weitergabe** vorgesehen.

Kein realer Server, kein persönliches Buch, keine native GUI-/Geräte-/Paketabnahme wurde in diesem Zusatzlauf verwendet oder freigegeben. Historische Nachweise und die aktuellen Hostläufe bleiben getrennt.
