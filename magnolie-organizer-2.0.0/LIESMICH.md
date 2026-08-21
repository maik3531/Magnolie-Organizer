# Magnolie Organizer – Quellpaket

Die Linux-Ausgabe des persönlichen Magnolie Organizers im Stil eines
ledergebundenen Papier-Organizers (Python 3, GTK 3, WebKit2GTK). Eine native
Windows-Ausgabe und Magnolie Notes für Android gehören ebenfalls zur
Magnolie-Produktfamilie.

WebKit2GTK bleibt unter Linux die primäre und fest paketierte Anzeige. Kann nur
dessen GI-Modul nicht geladen werden, nutzt eine normale Systeminstallation
ersatzweise ein installiertes Chromium oder Google Chrome; GTK 3 bleibt dabei
erforderlich. Das AppImage verwendet ausschließlich sein gebündeltes WebKit und
greift nie auf einen Browser des Wirts zurück.

## Tastatur und Hilfsrahmen

Die kalender- und listenübergreifende Option **Barrierefreiheit: Hilfsrahmen**
steht bewusst unter **Einstellungen > Allgemein**. Sie zeichnet das gerade mit
der Tastatur erreichte Bedienelement mit einem durchgezogenen Rahmen. Der
Hilfsrahmen ist voreingestellt deaktiviert, damit die Papierdarstellung unverändert
bleibt. Mit `Strg+Alt+H` lässt er sich im geöffneten Organizer jederzeit ein-
oder ausschalten; die Wahl wird dauerhaft gespeichert. Der einmalige
Ersteinrichtungsdialog zum Handbuch weist ebenfalls fett auf dieses Kürzel hin.
Am Termin-Notizfeld liegt der Rahmen innerhalb der rollbaren Schreibfläche,
damit er an keiner Kante abgeschnitten wird.

Die vollständige Maussperre des Hintergrunds bei geöffneten Dialogen benötigt
WebKitGTK 2.38 oder neuer. Auf älteren unterstützten Ausgaben begrenzt die
eingebaute Fokusfalle weiterhin Tastaturfokus und Escape-Behandlung auf den
obersten Dialog, während der Hintergrund auf Mausklicks reagieren kann.

Unter **Einstellungen > Allgemein > Registerkarten** lassen sich Aufgaben,
Adressen, Notizen, Jahrestage, Planer und Gesundheit unabhängig voneinander
ausblenden. Zugehörige Einstellungs- und Exportoptionen verschwinden ebenfalls;
die gespeicherten Inhalte bleiben erhalten. Der Kalender ist immer verfügbar.
Mit weniger Registern werden die Zungen höher, bei höchstens drei sichtbaren
Bereichen läuft die Beschriftung von oben nach unten. Ist nur der Kalender
sichtbar, benötigt und zeigt er keine Registerzunge.

## Handbuchdownload

Ist `magnolie-handbuch` installiert, bietet der einmalige Hinweis weiterhin das
direkte Öffnen an. Fehlt es, ruft der Organizer beim ersten Aufschlagen das
Aktualisierungsmanifest unabhängig von der täglichen Updateoption ab und bietet
das dort angegebene Handbuchpaket zum Download an. Der optionale Abschnitt hat
folgende Form:

    <manual>
      <version>1.9.10</version>
      <deb>https://…/magnolie-handbuch_1.9.10_all.deb</deb>
      <sha256>64 hexadezimale Zeichen</sha256>
    </manual>

Die Laufzeit akzeptiert nur HTTPS-Pakete aus derselben festgelegten
GitLab-Ablage, einen zur Version passenden Dateinamen und eine vollständige
SHA-256-Prüfsumme. Ein fehlender oder ungültiger Abschnitt erzeugt kein
Downloadangebot und verbraucht den einmaligen Hinweis nicht.

Organizer-Aktualisierungen enthalten zusätzlich das passende AppImage:

    <appimage>
      <architecture>x86_64</architecture>
      <url>https://…/Magnolie-Organizer-2.0.0-x86_64.AppImage</url>
      <sha256>64 hexadezimale Zeichen</sha256>
    </appimage>

Eine Debian-Installation erhält ausschließlich das Debian-Paket. Erkennt die
Laufzeit die AppImage-Umgebung, verwendet sie ausschließlich URL und Prüfsumme
aus diesem AppImage-Abschnitt; ein fehlender Abschnitt führt nicht zu einem
falschen Debian-Angebot.

## ODS-Kontakttabelle

Der ODS-Export legt Hauptanschrift, Festnetz, Mobilnummer und E-Mail-Adressen in
eigenen Spalten ab. In diesen Spalten stehen nur die Werte, nicht noch einmal
Bezeichnungen wie „E-Mail“ oder „Mobil“. Straße/Hausnummer und PLZ/Ort bleiben
getrennt. Weitere Anschriften und Rufnummern stehen mehrzeilig in eigenen
Zusatzspalten; dort bleiben freie oder zur Unterscheidung nötige Bezeichnungen
erhalten.

## Aufbau

    bin/         Startprogramm (Python: Fenster, Datenablage, ICS/vCard/
                 Lotus-CSV-Parser, Abgleich mit dem Evolution-Data-Server)
    web/         Oberfläche (index.html, stil.css, anwendung.js)
    symbole/     Programmsymbol als SVG und in vier PNG-Größen
    werkzeuge/   Erzeuger des Erinnerungsklangs sowie Release-/AppImage-Bau
    pruefungen/  Selbsttests (siehe unten)
    debian/      Paketbeschreibung für den Bau des .deb

## Paket bauen

    sudo apt install build-essential debhelper gettext nodejs node-jsdom
    dpkg-buildpackage -us -uc -b

Das fertige Paket liegt danach eine Ebene höher und wird installiert mit:

    sudo apt install ../magnolie-organizer_2.0.0_all.deb

Normale Eigenbauten enthalten kein Contributor-Branding. Offizielle Binärbauten
können über `MAGNOLIE_CONTRIBUTOR_HASH` eine 64-stellige SHA-256-Hexfolge
erhalten. Nur dann wird eine `build-config.json` in DEB, RPM oder AppImage
erzeugt. Die Konfiguration und der Klartextschlüssel gelangen nicht in Debian-
Quellpaket, Source0 oder SRPM.

### Fedora-RPM und SRPM

Auf Fedora erzeugt das Bauwerkzeug ein normalisiertes
`magnolie-organizer-2.0.0.tar.xz` mit dem gleichnamigen obersten Verzeichnis
und baut daraus RPM und SRPM. Bereits vorhandene Debian-Bauverzeichnisse,
generierte Kataloge und die generierte WAV-Datei gelangen nicht in Source0:

    sudo dnf install rpm-build rpmdevtools gettext python3-devel \
        python3-cryptography python3-zeroconf desktop-file-utils appstream
    werkzeuge/rpm_bauen.sh

Die Ergebnisse liegen unter `bau/rpm/RPMS/noarch/` und `bau/rpm/SRPMS/`. Ein
bereits erzeugtes Source0 lässt sich auch unmittelbar mit dem Spec bauen:

    rpmbuild -ba --define "_topdir $PWD/bau/rpm" \
        bau/rpm/SPECS/magnolie-organizer.spec

Ein sauberer Fedora-Chroot-Bau des SRPM und die anschließende Prüfung erfolgen
beispielsweise mit (die Fedora-Version bei Bedarf anpassen):

    sudo dnf install mock rpmlint
    sudo usermod -a -G mock "$USER"
    mock -r fedora-42-x86_64 --rebuild \
        bau/rpm/SRPMS/magnolie-organizer-2.0.0-1.fc42.src.rpm
    rpmlint rpm/magnolie-organizer.spec \
        bau/rpm/SRPMS/magnolie-organizer-2.0.0-1.fc42.src.rpm \
        bau/rpm/RPMS/noarch/magnolie-organizer-2.0.0-1.fc42.noarch.rpm

Das lokale RPM kann mit DNF installiert und wieder entfernt werden, ohne dass
die Paket-Scriptlets Firewallregeln öffnen oder Benutzerdaten verändern:

    sudo dnf install bau/rpm/RPMS/noarch/magnolie-organizer-2.0.0-1.fc42.noarch.rpm
    sudo dnf remove magnolie-organizer

Die mitgelieferte firewalld-Servicebeschreibung ist nur eine Vorlage. Falls
Magnolienbaum Verbindungen von anderen Rechnern annehmen soll, muss sie bewusst
vom Administrator aktiviert werden; die Paketinstallation tut dies nicht.
Bei eingeschaltetem Magnolienbaum registriert der Organizer zusätzlich ein
authentifiziertes Bluetooth-Classic-/RFCOMM-Profil bei BlueZ. Das ist optional,
benötigt keine Firewallregel und bleibt ohne BlueZ oder Bluetooth-Adapter still
aus, während WLAN unverändert weiterläuft.

## AppImage und vollständiger Releasebau

Der AppImage-Bau bündelt Python, PyGObject, GTK/WebKit-Laufzeitbibliotheken,
Typelibs, Übersetzungen und alle Organizer-Ressourcen. Die verwendeten Fassungen
von `linuxdeploy` und `appimagetool` sind mitsamt SHA-256-Prüfsummen im Bauplan
festgeschrieben. Gebaut und gegen den gepackten Programmkern geprüft wird mit:

    werkzeuge/appimage_bauen.sh
    pruefungen/test_appimage.sh ../Magnolie-Organizer-2.0.0-x86_64.AppImage

Für eine Freigabe ist ausschließlich der vollständige Releasebau vorgesehen:

    MAGNOLIE_AUTOPKGTEST_QEMU_IMAGE=/pfad/debian-autopkgtest.qcow2 \
        werkzeuge/release_bauen.sh

Er führt Parser-, DOM- und Import-/Export-Vertragstests, die 30.000er-Lasttests,
den Debian-Quell- und Paketbau, das vollständige `autopkgtest`, den RPM-Bau mit
Fedora-`mock`-Installation sowie AppImage-Bau und AppImage-Prüfung aus. Die
verifizierten Summen stehen danach in `Magnolie-Organizer-PRUEFSUMMEN.sha256`.
Fehlende Systemwerkzeuge brechen die Freigabe ab. Nur für ausdrücklich nicht
veröffentlichbare lokale Bauten dürfen beide Systempaketprüfungen gemeinsam mit
`--skip-system-package-tests` übersprungen werden.

## Prüfungen

Die Parser-, Abgleich- und Oberflächentests laufen ohne grafische Oberfläche
und werden beim Paketbau automatisch ausgeführt:

    TZ=Europe/Berlin python3 pruefungen/test_parser.py
    TZ=Europe/Berlin python3 pruefungen/test_import_export_vertrag.py
    python3 pruefungen/test_paketinhalt.py
    TZ=Europe/Berlin node pruefungen/test.js

Das Debian-Quellpaket enthält zusätzlich `autopkgtest`-Prüfungen gegen die
installierten Dateien. Datei-, DOM- und GTK-/WebKit-Tests laufen ohne Eingriff
in das System. Die echten User-systemd- und UFW-Lebenszyklen sind mit
`isolation-machine` gekennzeichnet und dürfen nur in einem wegwerfbaren
Maschinen-Testbed ausgeführt werden:

    autopkgtest ../magnolie-organizer_2.0.0.dsc -- qemu TESTABBILD

Für den Umstieg von Lotus Organizer gibt es zusätzlich Belastungstests
mit je 30.000 Terminen, Adressen, Aufgaben, Jahrestagen und Notizen:

    python3 pruefungen/erzeuge_lotus.py 30000 /tmp/lotus-gross.csv
    TZ=Europe/Berlin python3 pruefungen/last_test.py /tmp/lotus-gross.csv
    TZ=Europe/Berlin node pruefungen/last_test.js

Unter Debian und Ubuntu stellt `node-jsdom` die Testbibliothek ohne einen
Netzwerkzugriff während des Paketbaus bereit. Ist Node.js lokal nicht
installiert, kann die DOM-Suite auch mit `bun pruefungen/test.js` laufen.

## Aktualisierungen signieren

Die Aktualisierungsprüfung kann Ed25519-signierte Metadaten mit der
SHA-256-Prüfsumme des Debian-Pakets prüfen. Der private Release-Schlüssel bleibt
außerhalb des Quellbaums und muss die Rechte `0600` besitzen:

    python3 werkzeuge/update_signieren.py /sicherer/pfad/release.pem update.xml ../magnolie-organizer_VERSION_all.deb ../Magnolie-Organizer-VERSION-x86_64.AppImage

Das Werkzeug trägt die Prüfsummen von Debian-Paket und AppImage sowie die
gemeinsame `signature` in `update.xml` ein und gibt den
zugehörigen öffentlichen Base64-Schlüssel aus. Dieser wird vor dem ersten
signierten Release als `UPDATE_SIGNATUR_SCHLUESSEL` in
`bin/magnolie-organizer` fest eingebettet. Solange dort kein gültiger Schlüssel
eingetragen ist, wird die Aktualisierungsprüfung ohne Netzabruf abgebrochen und
es werden weder Manifestdaten noch Paketadressen akzeptiert.

## Datenablage

Speicheraufträge laufen seriell in einem Arbeitsfaden, damit Verschlüsselung,
Datei- und Verzeichnis-`fsync` die GTK-Oberfläche nicht anhalten. Jeder Auftrag
trägt eine Vorgangskennung; Schließen, Sicherung und Wiederherstellung warten
auf den zuletzt dauerhaft bestätigten Datenstand.

Bei Kennwortschutz verschlüsselt ein zufälliger 256-Bit-Datenschlüssel die
Hauptdaten. PBKDF2 leitet nur den Schlüssel zum Umhüllen dieses Datenschlüssels
ab. Normales Speichern benötigt daher keine erneute Schlüsselableitung, und ein
Kennwortwechsel ersetzt nur den Umschlag. Bestehende Hüllen der Fassung 1 werden
nach erfolgreicher Authentisierung atomar auf Fassung 2 migriert.

Importdateien sind auf 32 MiB und Sicherungsdateien auf 256 MiB begrenzt.
OpenHolidays-Antworten dürfen einzeln 1 MiB und je Abruf insgesamt 8 MiB
umfassen. Die Leser prüfen reguläre Dateien ohne symbolische Verweise und
brechen auch bei HTTP-Antworten ohne verlässliche Längenangabe begrenzt ab.

Einzeitige wöchentliche, monatliche bis zum 28. und jährliche
ICS-Wiederholungen außer dem 29. Februar werden bei minutengenauen Zeiten und
ausdrücklichem Terminende verlustfrei übernommen. Regeln
mit `EXDATE`, `RDATE`, `RECURRENCE-ID`, mehreren RRULEs, mehrtägigen
Wiederholungen, einer abweichenden Zeitzone oder nicht abbildbaren
RRULE-Teilen werden nicht angenähert:
Ihre Komponenten erscheinen als einzelne Termine, und der Import meldet diese
Produktgrenze ausdrücklich. Abgetrennte Instanzen erhalten dabei eine stabile
eigene Kennung, damit sie nicht als vermeintliches Duplikat verschwinden.
Komplexe Serien werden beim EDS-Abgleich nicht verändert oder zurückgeschrieben.

## Wetter und Datenschutz

Die optionale Wettervorhersage sendet Anfragen an `wttr.in`. Zuerst verwendet
sie den Ort aus der eigenen Anschrift, danach ausschließlich lokal gelesene
LibreOffice-Benutzerdaten. Fehlt dort ebenfalls ein Ort, kann `wttr.in` den Ort
anhand der bei jeder Verbindung sichtbaren öffentlichen IP-Adresse ungefähr
bestimmen. Die Kalenderoption „Wetter ohne Ort nicht abrufen“ beendet diesen
Fall im Backend vor jedem Netzwerkzugriff.

## Direktstart ohne Installation

    MAGNOLIE_ORGANIZER_WEB=$(pwd)/web python3 bin/magnolie-organizer

## Datumsfelder

Datumsangaben lassen sich ohne Unterbrechung als `TTMMJJJJ` tippen. So wird
`11021982` als `11.02.1982` übernommen. Der native Popup-Kalender ist
standardmäßig aus. Er lässt sich unter Allgemein ▸ Barrierefreiheit bei Bedarf
einschalten.

## Tray-Diagnose

Für sporadische Tray-Probleme den Organizer vollständig beenden und anschließend
mit Diagnose starten:

    magnolie-organizer --tray-start --debug

Das private, rotierende Protokoll liegt unter
`~/.local/state/magnolie-organizer/debug.log`. Es enthält technische Start-,
Sitzungs-, Fenster- und Tray-Zustände, aber keine Organizer-Inhalte. Bei einem
nur während der Anmeldung auftretenden Fehler kann im eigenen Autostarteintrag
vorübergehend `--debug` an den `Exec`-Aufruf angehängt werden.
Der optionale Tageszähler wird bei AppIndicator und XApp sichtbar neben dem
Tray-Symbol angezeigt; bei der alten `Gtk.StatusIcon`-Schnittstelle steht er im
Tooltip.
