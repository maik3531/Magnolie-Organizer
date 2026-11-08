# iPhone-Notizen und Zeichnungen: untersuchte Übertragungswege

Stand: 2026-11-08, Arbeit zu #121. Untersuchung öffentlicher Quellen;
noch kein bestandener iPhone–Organizer-Gerätetest und keine vollständige
Apple-Notizen-Synchronisation.

## Vorhandene KDE-Connect-App

KDE Connect bietet bereits eine [iOS-App im App Store](https://apps.apple.com/app/kde-connect/id1580245991).
Eine eigene Magnolie-iOS-App und eine eigene App-Store-Veröffentlichung sind
für die Übertragung exportierter Dateien damit nicht grundsätzlich erforderlich.
Der Projektinhaber muss dafür kein Apple-Entwicklerkonto anlegen.

Geprüft wurde das [offizielle KDE-Repository, Commit
64d8121e717269efe678d8f047dc918ace2e12c8](https://github.com/KDE/kdeconnect-ios/tree/64d8121e717269efe678d8f047dc918ace2e12c8):

- Die README nennt iOS ab 14, macOS ab 13 und die Verbindung über das lokale Netzwerk.
- `DevicesDetailView.swift` bietet **Send Files** sowie **Send Photos and Videos**
  mit tatsächlicher Datei-/Medienauswahl.
- `Share.swift` implementiert Dateipayloads; exportierte Bilder, Zeichnungen und
  PDFs können somit als Dateien transportiert werden.
- Das geprüfte Xcode-Projekt enthält keine gebaute Share Extension. Eine direkte
  Apple-Notizen→KDE-Connect-Aktion im iOS-Teilen-Menü ist dadurch nicht belegt.
- Die README und der App-Lebenszyklus beschreiben eingeschränkten Hintergrundbetrieb.
  Ein ständig erreichbarer Hintergrundabgleich wird nicht zugesichert.

Diese Quellprüfung bestätigt keine bestimmte installierte Store-Binärversion.

## Konkreter Ansatz ohne neue iOS-App

1. Der Endnutzer exportiert ausgewählte Notizen bzw. Zeichnungen in ein von seiner
   Apple-Version angebotenes Dateiformat und stellt diese in **Dateien** bereit.
2. Er wählt in KDE Connect das gekoppelte Ziel und **Send Files**.
3. Am Ziel wird die vollständig empfangene Datei bewusst in Magnolie ausgewählt.
   Bild/PDF bleiben Originalanhänge; Text benötigt einen additiven Notizenimport.

Die genaue Apple-Exportfunktion je Betriebssystemversion ist noch zu prüfen.
Die aktuelle Apple-Dokumentation war beim Abruf in der Cloud durch die
Netzwerkfreigabe blockiert; deshalb enthält dieses Dokument keine zugesicherte
Apple-Menüfolge. Dieser Ansatz verlangt die Geräte-/App-Freigabe des jeweiligen
Endnutzers, keinen Apple-Kontozugriff durch Magnolie oder den Projektinhaber.

## Was getrennt geprüft werden muss

Die Bytes einer exportierten Zeichnung können als Bild/PDF erhalten bleiben.
Das beweist keine editierbaren Apple-Zeichenstriche, Ebenen, gesperrten Notizen,
Notizbuchstruktur, Versionshistorie oder bidirektionalen Notizenabgleich.
Dateitransport und Formatübernahme sind unterschiedliche Prüfungen.

Die Mac-/Tablet-Betas besitzen bislang keinen eigenen KDE-Connect-Transport.
Ein externer Client und anschließende Dateiauswahl sind mögliche Bausteine;
der gesamte Weg ist noch nativ zu prüfen. Insbesondere deckt die genannte
macOS-13-Voraussetzung des externen KDE-Clients nicht automatisch unser
angestrebtes Monterey-12.7-Ziel ab. Eine Web-App würde ebenfalls keinen
allgemeinen Zugriff auf den Apple-Notizen-Bestand erhalten.

Vor einer Produktzusage: echte Dateiübertragung mit Hashvergleich, mehrere
Dateien, Zeichnung/Bild/PDF, Unicode-Dateiname, Abbruch/Übergröße sowie Speichern
und Neuöffnen in Magnolie testen. iPhone→Linux, Windows, Mac und Tablet sind
jeweils eigene Prüfstrecken.
