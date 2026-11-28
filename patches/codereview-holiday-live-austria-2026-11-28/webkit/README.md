# #855/#856 – native WebKit-Prüfung: konkreter Umgebungsblocker

## Ergebnis

**Kein nativer WebKit-Produkttest ausgeführt.** Der vorbereitete lokale
GTK-/WebKitGTK-Lauf kann in dieser Ausführungsumgebung keinen lokalen
IPC-Socket erzeugen. Schon der einzelne Systemaufruf
`socket(AF_UNIX, SOCK_STREAM)` schlägt mit **EPERM / Operation not permitted**
fehl. Es wird dabei weder eine Adresse gebunden noch eine Verbindung
aufgebaut.

Die gleiche minimale Probe schlägt sowohl direkt unter `/usr/bin/python3`
als auch in der vorgesehenen privaten bwrap-Namespace fehl. Somit ist die
Fehlerursache nicht auf die neue Bibliotheksanordnung oder auf den
WebKit-Prozesspfad beschränkt. `dbus-run-session` scheitert folgerichtig vor
dem GTK-/HTML-Start mit:

```text
dbus-daemon: Failed to start message bus: Failed to open socket: Operation not permitted
dbus-run-session: EOF reading address from bus daemon
```

`socket-probe.py` und `socket-probe-results.json` enthalten die unabhängig
nachvollziehbare Minimalprobe. Die gezielten DOM-/Abruf-/Cache-/Speicherprüfungen
wurden deshalb **nicht** in einer echten WebKit-Oberfläche ausgeführt.
Es wird keine native Linux-Paketabnahme oder Windows-WebView2-Abnahme behauptet.

## Vorbereitete Laufzeit

Die bereits bereitgestellten offiziellen Debian-13-Pakete für WebKitGTK
2.54.3 und Xvfb bleiben lokal entpackt. Paketmanifest und Signaturprotokolle
liegen bei. Keine Systeminstallation und keine Änderung am Produktquellcode.

Für den hart einkompilierten WebKit-libexec-Pfad wurde eine private
Mountanordnung vorbereitet: Der Hostbestand unter `/usr/lib` wird in der
Namespace erhalten, die maschinenabhängigen Bibliotheken über einen
schreibgeschützten Alias innerhalb `/usr/lib` erreichbar gemacht und die
lokalen WebKit-Abhängigkeiten ebenfalls dort eingebunden. Dadurch muss der
Hostpfad `/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1` nicht angelegt oder verändert
werden. Der Ablauf ist in `launch-webkit.py` reproduzierbar.

Die Vorbereitung beseitigte die ursprüngliche fehlende libexec-Pfadstruktur
bis zum Start von `dbus-run-session`; sie beweist keinen erfolgreichen Start
der WebKit-Unterprozesse. Der erste Versuch mit einzelnen Mountargumenten
für 3.828 Dateien überschritt bwraps Argumentlimit. Der endgültige Ansatz
verwendet 75 Top-Level-Einträge mit einer lokalen Symlinkanordnung. Ein
zusätzlich erwogener äußerer Netzwerk-Namespace scheiterte ebenfalls an
EPERM; dieser zusätzliche Namespace ist im endgültigen Runner nicht aktiv.

Es wurde **keine WebKit-Sandbox abgeschaltet**, kein privilegierter Lauf
angefordert und kein alternativer Zugang zur Umgehung der Socket-Sperre
verwendet. Nach dem direkten Nachweis der Umgebungsgrenze wurde dieser
Prüfpfad beendet.

## Aussagekraft und nächster Schritt

Die vollständige JSDOM-Sprachmatrix und die separat ausgeführten
Live-Provider-/C#-/Kotlin-/Swift-Prüfungen behalten ihre jeweils dokumentierte
Aussagekraft. Sie werden durch diesen fehlgeschlagenen Startversuch weder
ersetzt noch in native GUI-Abnahmen umbenannt.

Für die noch offene WebKit-Abnahme wird eine reguläre Linux-Sitzung benötigt,
in der lokale IPC-Sockets, X11/Wayland, D-Bus und die unveränderte
WebKit-Prozesssandbox funktionieren. Dort den vorgesehenen begrenzten Ablauf
mit vollständigem Produkt-HTML/JavaScript, den gebundenen Live-Captures und
kontrollierter Hostbrücke prüfen: regionale Aktualisierung, Erhalt fremder
Bestände, Wiederholung ohne Dubletten, Ferien-Opt-out und Speicher-Callback.
Eine solche Quelloberflächenprüfung wäre weiterhin von der Installation und
Abnahme eines ausgelieferten Linux-Pakets zu unterscheiden.
