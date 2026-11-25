# iPhone-Anbindung: vorhandene Apps und Übertragungswege

Auftragsumfang präzisiert am 2026-11-10, Arbeit zu #121: Nutzbare
iPhone-Anbindungen über vorhandene Apps, insbesondere KDE Connect, bleiben
Teil des Auftrags. Eine eigene Notes-App für das iPhone wird nicht umgesetzt.
Die folgenden Hinweise zum Export von Apple-Notizen beschreiben optionale
Dateiwege über vorhandene Apps.

Technischer Quellenstand: 2026-11-08; KDE-iOS-HEAD am 2026-11-10 erneut auf
denselben unten genannten Commit geprüft. Untersuchung öffentlicher Quellen;
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

## Weitere vorhandene iPhone-Fähigkeiten prüfen

Der geprüfte Quellbaum enthält außerdem Plugins für RemoteInput, RunCommand,
Battery, Ping, FindMyPhone und Presenter. Für den Organizer sind die jeweilige
Senderichtung, ausgehandelten Fähigkeiten und verfügbaren Desktop-Adapter
zu prüfen. Das Vorhandensein eines Plugins ist keine bestandene Magnolie-
Integration. Neben der Dateiübertragung bleiben solche nutzbaren Verbindungen
im Prüfumfang; ein pauschaler Ausschluss der iPhone-Anbindung gilt nicht.

## Mac-Empfänger und Alternative für ältere Macs

Die [aktuellen offiziellen KDE-Downloads](https://kdeconnect.kde.org/download.html)
bieten zusätzlich zur Swift-App einen Qt-Desktopclient. Im
[stabilen Bestand 26.08.2](https://download.kde.org/stable/release-service/26.08.2/macos/)
ist KDE Connect für ARM64 nachgewiesen. Der
[geprüfte Homebrew-Cask](https://github.com/Homebrew/homebrew-cask/blob/6b5a25d97a1426b8c8326f67f639b4ec9a3b82d3/Casks/k/kde-connect.rb)
verlangt macOS 13 und enthält einen `kdeconnect-cli`. Diese CLI-Zusage gilt
nicht automatisch für die eigenständige Swift-App. Intel-Downloads sind als
ungeprüfte Nightlies belegt, nicht als stabiler Monterey-Empfänger. Keiner dieser
Clients wurde in dieser Untersuchung installiert oder nativ gestartet.

Für ältere Macs gibt es einen weiteren vorhandenen Dateiweg: **AirDrop**.
Die versionsgebundenen Anleitungen für
[macOS Monterey 12](https://support.apple.com/guide/mac-help/send-files-between-devices-with-airdrop-mh35868/12.0/mac/12.0)
und [iOS 15](https://support.apple.com/guide/iphone/use-airdrop-to-send-items-iphcd8b9f0af/15.0/ios/15.0)
beschreiben Übertragen und ausdrückliches Annehmen ausgewählter Inhalte.
Bereits exportierte Bilder/PDFs/Dateien lassen sich am Mac annehmen und danach
bewusst in Magnolie importieren. Ein Apple-Entwicklerkonto des Projektinhabers
oder eine neue iOS-App ist dafür nicht erforderlich. Das ist ein dokumentierter
Ansatz, noch kein bestandener Gerätetest; er belegt keinen bestimmten
Apple-Notizen-Export unter iOS 15.

## Bildschirmspiegelung über AirPlay / UxPlay

Ergänzung vom 2026-11-20, [Issue #721](https://github.com/maik3531/Magnolie-Organizer/issues/721):
Der vom Nutzer genannte [GNU/Linux.ch-Artikel](https://gnulinux.ch/uxplay-iphone-bildschirm-unter-linux-anzeigen)
zeigt einen weiteren vorhandenen iPhone-Weg. UxPlay empfängt Bildschirm und Ton
über AirPlay; das iPhone verwendet dazu seine Bildschirmsynchronisierung im
Kontrollzentrum. Dafür wird keine eigene Notes-App oder andere neue iPhone-App
benötigt. Dieser Weg ist unabhängig von einer Android-Notes-Verbindung.

Geprüft wurden die Quellen der aktuell stabilen
[Version 1.73.7](https://github.com/FDH2/UxPlay/releases/tag/v1.73.7), Commit
`df67c212a433cf6dda3676dd40c097900d24e645`. Die
[Mac-Bauanleitung](https://github.com/FDH2/UxPlay/blob/v1.73.7/README.md#building-uxplay-on-macos-intel-x86_64-and-apple-silicon-m1m2-macs)
beschreibt Intel und Apple Silicon sowie ältere Macs ohne den eingebauten
AirPlay-Empfänger. Der Entwicklungszweig bezeichnet sich bereits als
„1.74 Experimental“; dessen neue Funktionen sind kein stabiler Nachweis.

Für den Mac-Anschluss sind UxPlay, GStreamer, libplist, OpenSSL 3 und Bonjour
zu berücksichtigen. Die Anleitung nennt ausdrücklich Besonderheiten des
GStreamer-Hauptthreads, Videosinks und Fensterschließens auf macOS sowie
Framedrops bei bestimmten Zeitstempel-Einstellungen. Die Paketierung und
Standardoptionen müssen deshalb auf beiden Architekturen tatsächlich geprüft
werden. Geeignete vorhandene Komponenten beim bewussten Start verwenden;
fehlende Komponenten nicht ungefragt nachinstallieren. Bei einer Mitlieferung
soll der Nutzer keine Entwicklungswerkzeuge zum Kompilieren benötigen.

UxPlay steht unter GPLv3. Bei einer Auslieferung gehören die Komponentenlizenzen
und zugehörigen Quellen zum Paketnachweis; insbesondere beschreibt das Projekt
OpenSSL 3 als geeigneten Linkpfad. Eine fertige Magnolie-Paketintegration ist
damit noch nicht geprüft.

**Spiegeln und Steuern sind getrennte Fähigkeiten:** UxPlay liefert Bild und
Ton, aber keine Maus-/Tastatur-Fernbedienung des iPhones. Eine solche Steuerung
darf die Organizer-Oberfläche daraus nicht ableiten. Die geplante Integration
benötigt Start/Stop und einen tatsächlichen Verbindungszustand; die Abnahme
umfasst echte iPhones, Kopplung, Bild/Ton, Drehung, Latenz/Bildrate, längere
Sitzungen, Verbindungsabbruch und erneutes Verbinden. Es gibt hierfür bisher
keinen bestandenen nativen Magnolie-Gerätetest.

### Implementierter Anschluss vom 25. November 2026

Der Quellpatch zu #721 enthält jetzt den Empfänger direkt unter `Receiver/`,
den nativen Magnolie-Host mit Start/Stop/PIN sowie den Bundlebau mit seinen
Bibliotheken. Für diesen Weg installiert der Anwender kein separates UxPlay.
Details und der genaue Prüfstatus stehen in [AIRPLAY.md](AIRPLAY.md) und
[AIRPLAY-BUILD.md](AIRPLAY-BUILD.md). Der Patch ersetzt den bisherigen reinen
Integrationsvorschlag; native Swift-/Mac-/iPhone-Abnahmen bleiben erforderlich.

## Datenfunktionen ohne eigene iPhone-App – Prüfung vom 25. November 2026

Der Nutzer hat zusätzlich die Prüfung von Notizen, Terminen und weiteren
Organizer-Funktionen beauftragt. Die vorhandenen Apple-Apps können dafür als
Gegenstellen dienen. Die AirPlay-Verbindung selbst liefert Medien und keine
Notiz-, Kalender- oder Kontaktdatensätze. Diese Aussage folgt sowohl aus
[Apples AirPlay-Funktionsbeschreibung](https://support.apple.com/guide/iphone/stream-video-and-audio-from-your-iphone-iphd668e80e6/ios)
als auch aus dem tatsächlich eingebundenen UxPlay-Protokoll-/Rendererbestand.

| Funktion | Technisch möglicher Weg ohne eigene iPhone-App | Tatsächlicher Magnolie-Quellstand und offene Arbeit |
| --- | --- | --- |
| Termine | Apple Kalender am iPhone; gemeinsames iCloud-/CalDAV-Konto; EventKit am Mac | `SystemAccounts` besitzt Lesen, quellengebundene Snapshots und revisionsgebundene Änderungen an Titel/Notiz/Ort bestehender nicht wiederkehrender Termine. Vollständiger Organizer-Abgleich, Anlage/Löschung, Konflikte und sichere Serienabbildung bleiben offen. |
| Aufgaben und Erinnerungen | Apple Erinnerungen am iPhone/Mac; EventKit für die freigegebenen Listen; bei iCloud dasselbe aktivierte Konto | Lesen/Snapshots und begrenzte Textänderungen sind vorbereitet. `NativeSystemRecordReader` kennzeichnet die nicht vollständig verfügbare Hierarchie. Keine Zusage für verlustfreie Unteraufgaben, Serien oder vollständigen Rückabgleich. |
| Kontakte und Geburtstage | Apple Kontakte; gemeinsames iCloud-/CardDAV-Konto; Contacts-Framework am Mac | Containergebundene, nicht vereinheitlichte vCard-Snapshots existieren. Status ist ausdrücklich `readOnly: true`; vollständige Feldabbildung und sichere Schreibtransaktionen fehlen. Geburtstage benötigen dieselbe geprüfte Kontaktabbildung. |
| Apple-Notizen als Text/Datei | Apple Notes exportiert Markdown/PDF beziehungsweise Originalanhänge; Übernahme über Dateien/AirDrop oder auf demselben Mac | `NoteFileImportHost` übernimmt TXT/MD als editierbaren Literaltext, PDF/Bilder als Originalanhänge mit Vorschau, Auswahlprüfung und Speichern. Das ist ein bewusster Import, kein laufender Abgleich. |
| Apple-Notizen automatisch am Mac | Gezielte AppleScript-Anbindung an die vorhandene Mac-App ist technisch möglich; für iPhone-Inhalte müssen sie dort über das eingerichtete Notizkonto verfügbar sein | Kein solcher Connector vorhanden. Er benötigt native Automation-Freigabe, feste Konto-/Ordneridentität, Änderungserkennung und Tests für gesperrte Notizen, Anhänge, Formatverlust und Konflikte. Keine allgemeine Apple-Notes-API verfügbar. |
| Fotos, PDF, Zeichnungen, andere Dateien | Vorhandener Apple-Dateiexport/AirDrop, anschließend Magnolies bewusster Import | Eine Bild-/PDF-Datei kann übernommen werden. Editierbare Apple-Zeichenstriche, Apple Pencil-Druckdaten und Live-Digitizerereignisse sind damit nicht belegt. Kein automatischer Galerieabgleich über AirPlay. |
| Bildschirm und Ton | iPhone-Kontrollzentrum, AirPlay und der in Magnolie eingebaute Empfänger | Anschluss in diesem Patch; echte Geräteabnahme offen. Die Bedienung des iPhones bleibt am iPhone. |
| Schichtplan, Mülltermine, Jahrestage und weitere Kalenderinhalte | Soweit sinnvoll über konkret abgebildete Kalenderereignisse/ICS; iPhone zeigt sie in Apple Kalender | Die Semantik muss pro Magnolie-Funktion geprüft werden. Eigene Planungsregeln, Gesundheits-/Messwerttabellen und weitere Magnolie-Daten erhalten durch AirPlay keinen gemeinsamen Datensatzkanal. |

### Belastbare Schnittstellen und ihre Grenzen

Apple dokumentiert mit [EventKit](https://developer.apple.com/documentation/eventkit.md)
Zugriff auf Kalender und Erinnerungen einschließlich Erstellen/Ändern und
Änderungsbenachrichtigungen. Das
[Contacts-Framework](https://developer.apple.com/documentation/contacts/cncontactstore.md)
stellt entsprechende Kontaktzugriffe bereit. Die
[iPhone-Kontoeinrichtung](https://support.apple.com/en-ie/guide/iphone/ipha0d932e96/26/ios/26)
nennt CalDAV und CardDAV ausdrücklich. Das vermeidet eine neue Magnolie-App auf
dem iPhone. Der Transport zwischen den Geräten erfolgt bei diesem Aufbau über
den eingerichteten Kontodienst. Bei iCloud nutzt er iCloud; die lokalen
EventKit-/Contacts-Zugriffe in Magnolie machen diesen Transport nicht zu einem
rein lokalen Direktabgleich.

Die aktuelle Mac-Quelle meldet weiter
`systemAccountSyncImplemented: false`. In `main.swift` sind Quellenauswahl und
Systemfreigabe angebunden. Das Vorhandensein der Methoden in `SystemAccounts`
und `NativeSystemRecordReader` ist kein Beleg, dass bereits alle Organizer-
Datensätze vollständig und automatisch in beide Richtungen abgeglichen werden.

Für Apple Notes hat Apples Developer Technical Support im Januar 2026
[ausdrücklich die fehlende allgemeine Notes-API bestätigt](https://developer.apple.com/forums/thread/813810),
zugleich aber den AppleScript-Zugriff am Mac bestätigt. Ein nativer Mac-
Connector wäre deshalb eine mögliche weitere Entwicklung ohne eigene iPhone-
Notes-App. Das ist eine Architekturfolgerung aus Apples Auskunft, keine bereits
bestandene Magnolie-Integration. iOS-Kurzbefehle erlauben vom Nutzer eingerichtete
Abläufe; sie stellen laut derselben Apple-Auskunft keine allgemeine von fremden
Apps aufrufbare Notes-API bereit.

Der heute vorhandene Dateiweg bleibt konkret nutzbar in einem entsprechend
geprüften Magnolie-Bau. Apple beschreibt
[Notizexport am Mac](https://support.apple.com/guide/notes/import-export-and-print-notes-not201900c07/mac)
und [am iPhone](https://support.apple.com/guide/iphone/iphdf551cfa2/ios).
Markdown ist versionsabhängig; die bestehende Dokumentation unten trennt die
älteren PDF-Wege. Anhänge nicht allein durch den PDF-Gesamtexport einer Notiz
sichern: Apple nennt dort die Beschränkung auf die erste Seite eingebetteter
mehrseitiger PDFs/Scans.

### Konkrete Fortsetzung innerhalb von #121

Die AirPlay-Arbeit darf diese Datenfunktionen nicht als schon implementierten
Zusatz freischalten. Der nächste getrennt abnehmbare Datenanschluss ist die
Vervollständigung der vorhandenen EventKit-/Contacts-Adapter: zunächst geprüfte
Übernahme ausgewählter Quellen, danach nur bestätigte verlustfreie Änderungen
mit Rücklesen, Konfliktbehandlung und Widerruf. Apple-Notizen benötigen einen
eigenen Mac-Connector oder den bestehenden Dateiimport. Eine eigene iPhone-App
ist für diese Wege keine Voraussetzung.

## Dateiübertragung und Livezeichnen unterscheiden

Der geprüfte iOS-Pluginbestand unterstützt Dateien, Fotos/Videos und bewusstes
Senden der Zwischenablage. Magnolies Digitizer-Protokolle für Livezeichnen
sowie SMS-/Telefonie-Plugins sind darin nicht nachgewiesen. Deshalb exportierte
Zeichnungen als Dateien übernehmen; daraus keine Live-Pencil-, Druckdaten-
oder iPhone-SMS-Unterstützung ableiten. CLI-Schalter des Desktopclients allein
beweisen keine entsprechende Fähigkeit des gekoppelten iPhones.

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
