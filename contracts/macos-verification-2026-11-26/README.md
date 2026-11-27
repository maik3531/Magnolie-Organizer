# Tatsächliche Hostprüfungen — 26. November 2026

Dieser Nachweis gehört zu #121/#783/#785/#786. `manifest.json` ordnet jeden
unverändert übernommenen Log seinen tatsächlich geprüften Quellstand und
Befehl zu. SHA-256 und Bytelänge binden die Dateien; die Zeitangaben im
Unittest-Ausdruck sind die tatsächlich gemeldeten Laufzeiten.

Der erste Gesamtaufruf hatte zwei Fehler: Der Linux-Negativtest erreichte wegen
des neu erforderlichen Runtimearguments nur argparse; der dateibasierte
historische Adapterloader konnte den neuen Projektorimport nicht auflösen.
8d4004a9 und 7c9cf203 beheben diese Ursachen. Kein historisches Orakel und keine
Erwartung wurde abgeschwächt. Der vollständige Wiederholungslauf am Quellstand
7c9cf20394aef73d261a77f746ebca7340826d30 bestand **35/35 Gruppen**.

Die OR6-Probe führt Originalbytes durch den tatsächlichen Parser und die
wirkliche projizierte Organizer-UI bis zur synthetischen Save-ACK-Kette.
Der neue Sync-Runner steht im Hostlog mit 107 Prüfungen in EN/DE; Provider und
Diskantworten sind synthetisch. Die `SWIFT_TEST_TIMEOUT_TECHNICAL`-Zeilen stammen
von ausdrücklich simulierten Child-Prozess-Grenztests, nicht von einem hier
ausgeführten Swift-Compiler. Es gibt hier keinen neuen nativen Mac-Test.

`runtime-configure.json` belegt die unabhängige Configure-/makesetup-Prüfung
an der echten gepinnten CPython-Quelle. Die angegebenen Arbeitsverzeichnisse
sind temporäre Reviewpfade. Der geprüfte ursprüngliche Builder konnte optionale
zstd-Module trotz deaktiviertem pkg-config erkennen. 13692287 übernimmt die
isoliert nachgewiesene Moduldeaktivierung; `runtime.log` prüft den korrigierten
Builder. Das ist kein angeblich fehlgeschlagener oder bestandener Mac-Bau.

Node 24.22.3, JSDOM 26.1.0, GNU gettext 0.21 und CPython 3.12.14 wurden im
Linux-Quellhost verwendet. Der geplante private Mac-Interpreter ist CPython
3.15.2. Die vorbereiteten nativen Gates und Gegenstellenprüfungen stehen in
[Cloud-Mac-Prüfplan](../../Magnolie-Organizer-macOS-Beta/CLOUD-MAC-TESTING.md).

Nach dem genannten Codecommit ergänzt die Übergabe ausschließlich Dokumente,
Inventar und diese Belege. Der endgültige Source-Proof und die reproduzierbare
Projektion werden vor dem Push erneut am vollständigen Dokumentationscommit
geprüft. Die Tests werden nicht zu einer Summe nativer Assertions addiert.
