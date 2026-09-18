# Verbindlicher Arbeitsablauf

## Eine Produktquelle

Dieses Repository ist die maßgebliche Produktquelle. Änderungen an Organizer,
Notes und Handbuch werden ausschließlich hier vorgenommen. Temporäre Baukopien,
entpackte Pakete und Test-VMs sind keine zusätzlichen Entwicklungsstände.
Ein dort gefundener Fehler wird in der zugehörigen Quelle dieses Repositorys
behoben.

Die dauerhaften Quellordner heißen `magnolie-organizer`,
`magnolie-organizer-windows`, `magnolie-notes` und `magnolie-handbuch`. Sie erhalten bei einem Release
keine neue Versionsnummer im Verzeichnisnamen. Versionsnummern bleiben in den
Programmdaten, Tags und Downloadpaketen.

## Jede Änderung gehört zu einem GitHub-Issue

1. Vor einer Änderung ein vorhandenes Issue zuordnen oder ein neues anlegen.
   Ziel, betroffene Komponenten und überprüfbare Abschlusskriterien festhalten.
2. Eine Aufgabe nach der anderen abschließen. Neue Befunde als eigene Issues
   erfassen; den Umfang der aktiven Aufgabe nicht stillschweigend erweitern.
3. Nur die zugehörige Änderung umsetzen und passend dazu prüfen. Bereits
   bestandene Prüfungen nur bei geänderten Eingaben oder einem konkreten neuen
   Befund wiederholen.
4. Den geprüften Stand mit Issue-Verweis committen und auf GitHub sichern.
   `Refs #N` kennzeichnet Zwischenstände; `Closes #N` nur vollständig erfüllte
   Abschlusskriterien. Keine unfertige Aufgabe als erledigt kennzeichnen.
5. Im Issue knapp festhalten, was umgesetzt wurde, was tatsächlich geprüft wurde
   und was noch fehlt. Eine Quellstandsicherung ist keine Veröffentlichung.

Bestehende Benutzeränderungen erhalten. Nur beabsichtigte Quelldateien aufnehmen;
keine persönlichen Daten, Zugangsdaten, Signierschlüssel, privaten Nachweise oder
erzeugten Pakete committen. Interne Veröffentlichungsunterlagen bleiben privat.

Der zusammengeführte offene Arbeitsstand für 2.0.19 / Notes 1.0.15 wird in
[Issue #4](https://github.com/maik3531/Magnolie-Organizer/issues/4) verfolgt.
