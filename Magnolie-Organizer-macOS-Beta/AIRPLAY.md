# iPhone-Bildschirm in Magnolie – Quellintegration zu #721

Stand: 25. November 2026. **Implementierter Quellpatch, noch kein nativ
freigegebenes Mac-/iPhone-Paket.** Der Benutzerauftrag ist ein integrierter
Empfänger ohne separat zu installierendes UxPlay oder andere Hilfsprogramme.

## Bedienung im dafür gebauten Magnolie-Paket

Im Magnolie-Anwendungsmenü öffnet **iPhone-Bildschirm anzeigen…** die eigenen
Empfangssteuerungen. Das Öffnen startet keinen Netzwerkdienst. **Empfang starten**
startet den eingebauten Empfänger; das iPhone verwendet im gleichen Netzwerk
**Kontrollzentrum → Bildschirmsynchronisierung → Magnolie [Mac-Name]**. Eine
angeforderte PIN erscheint in Magnolie und wird am iPhone eingegeben. Bild und
Ton gibt der mitgelieferte Renderer aus; das Bild besitzt ein eigenes Fenster.
**Empfang beenden** oder das Schließen des Magnolie-Empfangsfensters beendet die
Sitzung. Das Schließen nur des Rendererfensters ersetzt diesen Stop nicht.

Die PIN-Kopplung bleibt im privaten Magnolie-Profil erhalten. PINs und Rohlogs
werden nicht in Diagnosedateien geschrieben. Nach Abmeldung/Benutzerwechsel,
Ruhezustand, Bildschirmsperre und beim Beenden von Magnolie wird der Empfang
gestoppt. Er startet anschließend nur durch erneutes bewusstes Einschalten.
Die reale Zustellung dieser macOS-Ereignisse ist Teil der offenen nativen Abnahme.

Ein Entwicklungsbau ohne eingebettete Komponente zeigt eine entsprechende
Meldung. Die App sucht nicht in Homebrew-/Systempfaden nach fremden Programmen
und lädt bei der Benutzung nichts nach.

## Aufbau

| Bestandteil | Aufgabe |
| --- | --- |
| `Sources/MacBeta/AirPlayHost.swift` | Native Oberfläche, bewusster Start, eigener Kindprozess, PIN-Anzeige, Sperr-/App-Lebenszyklus |
| `Sources/BetaCore/AirPlaySession.swift` | Zustände, Sitzungstoken, Startzeitlimit, spätes Ereignis/Prozessende, Fehler und PIN-Lebensdauer |
| `Sources/BetaCore/AirPlayProtocol.swift` | Streng begrenzter JSONL-Decoder für ausschließlich lokale Empfängerereignisse |
| `Sources/BetaCore/AirPlayBundle.swift` | Versionierter Bundlevertrag, ausschließlich interne Programmpfade/Plugins und private Kopplungsdateien |
| `Receiver/` | Enthaltener UxPlay-Quellstand, lokale Änderungen, CMake-Ziel, eigener IPC-/Registrierungscode, Lizenzen und Provenienz |
| `tools/airplay_bundle.py` | Bau aus ausdrücklich vorbereitetem SDK, geschlossene Bibliothekskette, Relocation und Signierung im App-Bundle |

UxPlay ist auf **v1.73.7**, Commit
`df67c212a433cf6dda3676dd40c097900d24e645`, gebunden. Die originalen und lokalen
Dateihashes stehen in `Receiver/UPSTREAM.json`; der lokale Delta-Patch und
Lizenzhinweise liegen daneben. Der Empfänger wird aus diesen Quellen als
`magnolie-airplay-receiver` gebaut. Er ist ein interner Magnolie-Prozess, weil
UxPlay/GStreamer einen eigenen Prozesszustand und den macOS-Hauptthread für die
Ausgabe benötigen. Für den Anwender gehört er vollständig zur Magnolie-App.
Die Bibliotheksquellen werden dadurch nicht zu eigener proprietärer Software;
ihre Lizenz- und Quellenhinweise bleiben erhalten.

Der IPC-Kanal enthält ausschließlich `ready`, `pin`, `video`, `audio`,
`disconnected` und feste `error`-Kennungen. Rohes UxPlay-stdout/stderr wird nicht
ausgewertet und nicht in die Oberfläche übernommen. `ready` folgt auf die
geprüfte Initialisierung des Netzwerkempfängers und der Dienstregistrierung.
`video`/`audio` belegen den Empfang von Paketen, **nicht** erfolgreich gerenderte
Frames, hörbaren Ton oder eine gemessene Bildrate. Bei Änderungen aktiver
Medienspuren wird der Status zurückgesetzt und aus den verbleibenden Spuren
neu aufgebaut.

Der Helfer beobachtet seine stdin-Verbindung zur App. EOF beendet ausschließlich
ihn selbst, mit begrenzter Nachfrist auch bei blockiertem GStreamer. Die App
benutzt keine globalen Prozessnamen oder `killall`. Sitzungstoken verhindern,
dass verspätete Ereignisse/Timer einen neu gestarteten Empfänger verändern.

Kopplungsdateien sind benutzereigen und privat; Links und mehrfach verknüpfte
Dateien werden abgelehnt. Der ersetzte Upstream-Registrierungsleser begrenzt
Größe, Zeilen und Schlüssel, verweigert abgebrochene Einträge und speichert nur
öffentliche Kopplungsschlüssel. Die Prozessumgebung übernimmt keine fremden
UxPlay-/GStreamer-/Loader-Konfigurationen.

## Bau und Quellen

Der vollständige Entwicklerweg und das Eingabe-SDK stehen in
[AIRPLAY-BUILD.md](AIRPLAY-BUILD.md). GStreamer, OpenSSL 3 und libplist werden im
Bundle mitgeliefert; Bonjour ist der macOS-Systemdienst. Mindestziel bleibt
macOS 12.7 für Intel beziehungsweise Apple Silicon. Der Bau lehnt Bibliotheken
mit unpassender Architektur, höherem Mindest-macOS oder offenen externen
Abhängigkeiten ab. Das ist keine Monterey-Gerätefreigabe.

Primärquellen:

- [UxPlay 1.73.7](https://github.com/FDH2/UxPlay/releases/tag/v1.73.7)
- [Versionsgebundene UxPlay-Dokumentation](https://github.com/FDH2/UxPlay/blob/v1.73.7/README.md)
- [GStreamer: private Bereitstellung und Relocation am Mac](https://gstreamer.freedesktop.org/documentation/deploying/mac-osx.html)
- [Apple: Bildschirm und Ton mit AirPlay übertragen](https://support.apple.com/guide/iphone/stream-video-and-audio-from-your-iphone-iphd668e80e6/ios)

## Prüfung und offene Abnahme

Die folgenden gezielten Prüfungen gehören zum Patch:

```sh
python3 Receiver/tests/test_receiver.py
python3 tests/test_airplay_bundle.py
python3 tools/check_airplay.py
```

Die ersten beiden Strecken prüfen echten C++-Steuercode und synthetische
Paket-/Abhängigkeitsfälle auf dem Entwicklungshost. Der Swift-Launcher prüft
die tatsächlichen Foundation-/POSIX-Quellen in einem isolierten Swift-Paket,
benötigt eine vorhandene Swift-Toolchain und meldet deren Fehlen ausdrücklich
als Fehler. In der Arbeitsumgebung vom 25. November war kein Swift vorhanden;
die Swift-Fälle und die AppKit-Anbindung sind dort **nicht ausgeführt** worden.

Vor der Übernahme als nutzbares AirPlay-Paket am Mac stehen aus:

1. Native Kompilierung einschließlich der neuen Swift-Tests, Bundlebau aus
   passendem SDK und Signaturprüfung auf `arm64` und `x86_64`.
2. Start des verschobenen App-Bundles auf einem Mac ohne extern installiertes
   UxPlay/GStreamer/Homebrew; Bonjour und lokale Netzwerkfreigabe prüfen.
3. Echtes iPhone: erste PIN, Wiederverbindung mit erhaltener Kopplung,
   abgebrochene PIN-Eingabe, Bild/Ton, Hoch-/Querformat, Audio ohne Video.
4. Fenster-/App-Stop, Sperre, Benutzerwechsel, Ruhezustand, App-Absturz,
   Verbindungsabbruch und erneuter Start; keine verwaisten Empfänger.
5. Längere Sitzung, CPU-/Speicherverbrauch, Bildrate und Latenz messen.
   `-vsync no` und ein bestimmter Videosink werden ohne diese Messung nicht
   pauschal als bessere Einstellung erzwungen.

## Notizen, Termine und weitere iPhone-Funktionen

AirPlay transportiert Bild/Ton und ersetzt keinen Datensatzabgleich. Der
zusätzliche Nutzerauftrag wurde gegen Apples Schnittstellen und den aktuellen
Magnolie-Quellbestand geprüft. Die konkrete Matrix, mögliche Wege ohne eigene
iPhone-App und die vorhandenen Lücken stehen in
[IPHONE-INTEROPERABILITY.md](IPHONE-INTEROPERABILITY.md#datenfunktionen-ohne-eigene-iphone-app--prüfung-vom-25-november-2026).
