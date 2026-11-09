# Lokale Medienvorschau (Refs #429)

Automatische Thumbnails sind optional und zunächst ausgeschaltet. Die Auswahl
gilt für die geöffnete lokale Oberfläche, nicht als synchronisierte Einstellung
oder Medienberechtigung. Auch ohne Thumbnails lässt sich eine einzelne Datei
gezielt als größere Vorschau öffnen. Reine Textnotizen erhalten keine Thumbnails.

Die Vorschau liest den tatsächlich vorhandenen Wiederherstellungsbestand. Sie
stellt nicht wieder her, löscht nichts, erstellt keine Archiv-/Temporärkopie,
startet keine Telefonverbindung und erteilt keine Galerie-/Übertragungsrechte.
Auswahl, gespeicherter Bestand und aktuelle lokale Berechtigung werden vor und
nach dem Lesen/Dekodieren geprüft. Unbekannter, beschädigter, ersetzter oder zu
großer Inhalt bleibt unverändert ohne Vorschau erhalten.

- **Linux:** undurchsichtige Bereich-/Vorgang-/Versionsauswahl; gehaltene native
  Dateiidentität und vollständige Prüfsumme, gemeinsame Aufbewahrungsaktivität.
  PNG/JPEG; Video-Standbild optional über vorhandenes lokales ffmpeg/prlimit,
  ohne Netzwerk/Playlist oder Vorschau-Datei. Maximal 192 beziehungsweise 1024
  Pixel Seitenlänge, begrenzte Rasterantwort. Der Videodekoder ist separat mit
  echten Videobytes geprüft, nicht als vollständiger signierter Video-Papierkorbweg.
- **Notes:** vorhandene authentifizierte verschlüsselte Archivchunks, gleicher
  nativer lokaler Worker wie Wiederherstellung, aktuelles gespeichertes entsperrtes
  Buch. Höchstens 16 MiB temporäre entschlüsselte Eingabebytes, danach überschrieben;
  PNG/JPEG/WebP mit begrenzter Dekodiergröße. Android ab API 27 verwendet für Videos
  eine lokale speicherbasierte Datenquelle und skalierten Frameabruf. Echte native
  PNG-Archivvorschau und Compose-Auswahl/Bestätigung sind geprüft; echte Android-
  Videoausgabe und die physische Handyoberfläche sind noch nicht abgenommen.
- **Windows:** exakte geschützte Papierkorb-/Saved-/END-Zuordnung, ursprünglicher
  nativer Elternordner und gehaltene Dateiidentität/Prüfsumme; gleicher lokaler
  Worker-Ausschluss wie Wiederherstellung/Löschung. Höchstens 16 MiB Eingabe mit
  anschließendem Überschreiben, PNG/JPEG über den nativen Plattformdekoder;
  Dimensionen werden vor dem Dekodieren begrenzt. Video ist hier noch nicht
  unterstützt. Tatsächlicher nativer Papierkorb-Lesepfad und der tatsächlich
  gebaute Produktdekoder sind unter Windows separat geprüft. Die Browseroberfläche
  prüft korrelierte Rasterantworten, bietet weiterhin die vorhandenen nativen
  Wiederherstellungs-/Löschaktionen und entfernt private Bildquellen beim Schließen.

Diese Quellstandsprüfungen sind keine Paket-/Installationsabnahme, keine Freigabe
der gemeinsamen Medienbetriebsbereitschaft und kein Abschluss der noch offenen
Galerie-, Synchronisations- oder Aufbewahrungsarbeiten.
