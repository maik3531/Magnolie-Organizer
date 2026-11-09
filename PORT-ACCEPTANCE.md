# Organizer-Ports: Funktions- und Abnahmeumfang

Arbeitsauftrag und Querverfolgung: [Issue #121](https://github.com/maik3531/Magnolie-Organizer/issues/121).
Referenz ist die veröffentlichte Version `v2.0.30`, Commit
`067c38934b539943d8e1720abafd8a80b401d797`. Die Paketkennung allein bedeutet
keine Funktionsgleichheit. Mac-Testpakete aus
[Run 42547724299](https://github.com/maik3531/Magnolie-Organizer/actions/runs/42547724299)
am Quellstand `798771ed` bestehen die vorhandenen nativen Prüfungen und den
App-Start-/Speicher-/Wiederöffnen-Ablauf auf macOS 15 für Intel und Apple Silicon.
Das ist eine Komponentenabnahme; die unten offenen Funktionen bleiben offen.

## Ziel und verbindliche Nachweise

Beide Anwendungen sollen stabil und flüssig bedienbar sein. Unterstützte
Funktionen müssen tatsächlich arbeiten; fehlende native Anschlüsse dürfen keine
erfundenen Erfolgsantworten, leeren Kontenlisten bei verweigertem Zugriff oder
verlustbehaftete Ersatzdarstellungen liefern.

| Bereich | Erforderlicher Funktionsnachweis | Aktueller Stand / offene Integration |
| --- | --- | --- |
| Termine | Anlegen, ändern, löschen, Papierkorb, Mehrtages- und Ganztagstermine; Datenerhalt nach Prozessneustart | Gemeinsame Oberfläche; Mac-Persistenz nativ bestanden, Tablet-Basics und einzelne Neustartläufe bestanden; vollständige Fallmatrix offen |
| Wiederkehrende Termine | COUNT/UNTIL, Intervalle, Monats-/Wochentagsregeln, RDATE/EXDATE, einzelne geänderte/gelöschte Vorkommen, Sommerzeit und Zeitzonen | Native Mac-Kalendercodecs gegen unabhängige Referenzen auf beiden Architekturen bestanden; Android-Codecs sowie tatsächliche WebView-/Worker-Zeitpfade bestanden. Port-Abnahme und Altbestands-Reparatur #465 (Nachfolge zu #462) sowie vollständige Interaktionsmatrix bleiben offen |
| Aufgaben | Erstellen, Fälligkeit, Unteraufgaben, Erledigen, Wiederholungen und Erinnerungen mit unveränderten Zeit-/Quellenbindungen | Tablet-Grundablauf nativ bestanden; vollständige Wiederholungs-/Erinnerungs- und Providerabnahme offen |
| Jahrestage | Geburtstag/Jahrestag mit und ohne Geburtsjahr, 29. Februar, Anzeige-/Import-/Export-Rundlauf | Gemeinsame Modelle; nativer Kalenderexport wird ergänzt; native Abnahme offen |
| Import/Export | Alle angebotenen Formate einschließlich ICS, VTODO, vCard/CSV und vollständiger Sicherung; Vorschau, Dubletten, Abbruch, Fehler und erneuter Import | Mac-Kalendercodecs und ausgewählte Notizdateien nativ geprüft; Android-SAF-ICS-Import/Export einschließlich Abbruch und atomarer Fehlerablehnung bestanden. Vollständige Format- und Restore-Abnahme offen |
| Nextcloud | CalDAV/CardDAV-Discovery, Auswahl, Lesen/Schreiben, ETags, Konfliktprüfung, Löschungen, Abbruch/Wiederholung und sichere Zugangsdaten | Native Transport-/Protokollmodule werden ergänzt; Konten-UI, sichere Ablage und vollständiger Synchronisierungskoordinator noch offen |
| Systemkonten auf macOS | EventKit-Kalender/Erinnerungen und Contacts-Adressbücher mit vorhandenen macOS-Quellen; erlaubter/verweigerter/widerrufener Zugriff und bestätigtes Schreiben | Native Quellenmodule werden integriert. Keine Übernahme von Linux EDS/Akonadi; keine Extraktion von Internetkonto-Passwörtern |
| Feiertage / Schulferien | Land, Region/alle Regionen, ausgewählte Jahre, Datumsgrenzen, lokaler Cache, Offlineanzeige und Fehler ohne Cacheverlust | Gemeinsame Anzeige/Filter; native HTTPS-Abrufe werden ergänzt |
| Sicherung / Datenerhalt | Erstsave, normaler Abschluss, harter Prozessneustart, Importersetzung, Fehler vor/nach Commit, vorhandene unbekannte Felder | Mac-Lifecycle nativ bestanden; weitergehende Fehler-/Upgrade-/Restore-Abnahme und Tablet-Komplettsuite offen |
| Flüssigkeit | Gemessene Kalt-/Warmstarts, Eingabe- und Ansichtswechselzeiten mit realistischen Daten; keine UI-blockierenden Netzwerk-/Datei-/Kontenabfragen | Native Laufzeiten und Testschritte werden protokolliert. Tablet-Layout-/Touch-Suite derzeit nicht bestanden; lokale JSDOM-Messungen ersetzen keinen Gerätenachweis |

## Abnahmeszenarien

- Exportierte Daten erneut importieren und IDs, Serien/Ausnahmen, Zeiten,
  Aufgabenstatus, Anhänge und unbekannte zulässige Eigenschaften vergleichen.
- Berlin/New York, UTC, Sommerzeitlücke/-überlappung und zukünftige Regeln
  prüfen. Eine Serie darf nicht als endliche Liste von Einzelterminen exportiert
  oder durch pauschale UTC-Umrechnung verfälscht werden.
- Bei Nextcloud veraltete ETags, gleichzeitige Änderungen, entzogenen Zugriff,
  Verbindungsabbruch und bereits gelöschte Ressourcen prüfen. Ein HTTP-Erfolg
  ersetzt keinen lokalen dauerhaften Commit und bestätigten Quellenabgleich.
- Native Konten verwenden die öffentlichen Plattform-APIs und deren
  Berechtigungsdialoge. Nicht konfigurierbare Konten auf einem CI-Runner sind
  ausdrücklich ungetestet; sie zählen nicht als erfolgreiche Synchronisierung.
- Native Tablet-Prüfungen behalten die 17 alten Serien, 40 tatsächlichen
  Touch-Registerwechsel und bestehenden Zeit-/Speichergrenzen. Die Fixture muss
  den Kalenderindex tatsächlich invalidieren. Ein Timeout oder Prozessabbruch
  bleibt ein fehlgeschlagener Lauf.
- Netzwerk, Dateizugriff und native Kontenabfragen laufen außerhalb des
  UI-Threads. Abbruch und späte Ergebnisse dürfen keine inzwischen ersetzten
  Profile, Konten oder Auswahlen verändern.

Die abschließende Veröffentlichung ist vom Nutzer autorisiert. Die noch
ausstehende native Gesamtabnahme und notwendige Installations-/Startprüfungen
blockieren derzeit die Produktionsveröffentlichung. Bis dahin sind Artefakte
nachvollziehbar gebundene Testkandidaten. Einzelne bestandene Komponentenläufe
ersetzen insbesondere nicht die vollständige Tablet-Touchprüfung.
