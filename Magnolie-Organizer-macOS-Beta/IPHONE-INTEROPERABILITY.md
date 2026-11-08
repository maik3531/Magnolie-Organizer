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

Dieser Ansatz verlangt die Geräte-/App-Freigabe des jeweiligen Endnutzers,
keinen Apple-Kontozugriff durch Magnolie oder den Projektinhaber.

## Durch Apple-Dokumentation bestätigte Exportmöglichkeiten

Nach erneuter Bereitstellung der Cloud waren die offiziellen Anleitungen am
2026-11-08 erreichbar. Die versionsgebundenen Seiten wurden getrennt gelesen:

- [iPhone mit iOS 26: Notizen exportieren oder drucken](https://support.apple.com/guide/iphone/iphdf551cfa2/26/ios/26)
  beschreibt PDF- und Markdown-Export mit anschließender Auswahl des Speicher-
  oder Sendeziels. Eine neue Magnolie-iOS-App ist dafür nicht erforderlich.
- [iPhone mit iOS 18](https://support.apple.com/guide/iphone/iphdf551cfa2/18.0/ios/18.0)
  beschreibt den PDF-Export über Teilen/Markieren und Speichern. Markdown wird
  in dieser versionsgebundenen Anleitung nicht angeboten.
- [Apple Notes auf dem Mac](https://support.apple.com/guide/notes/import-export-and-print-notes-not201900c07/mac)
  beschreibt ebenfalls PDF-/Markdown-Export. Das ist eine zusätzliche Option
  für Nutzer mit Mac, keine Voraussetzung für den iPhone-Dateiweg.

Eine konkrete Begrenzung nennen beide geprüften iPhone-Anleitungen: Wird eine
ganze Notiz als PDF exportiert, enthält sie von einem eingebetteten mehrseitigen
PDF oder Scan nur dessen erste Seite. Deshalb die vollständigen Originalanhänge
zusätzlich als eigene Dateien sichern und übertragen; der spätere Import kann
bereits beim Apple-Export weggelassene Seiten nicht wiederherstellen.

Markdown ist zunächst ein Textweg. Magnolies ausgewählter Mac-Dateiimport
übernimmt Markdown als editierbaren Literaltext mit entsprechendem Hinweis;
referenzierte Bilder oder editierbare Apple-Zeichenstriche werden dadurch nicht
automatisch übernommen. Zeichnungen/Bilder und Original-PDFs separat übertragen.
Die Anleitung belegt die angebotenen Apple-Funktionen, keinen bereits bestandenen
Gerätetest und keine unveränderte Menüfolge auf allen älteren iOS-Versionen.

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
