# Aktueller Arbeitsstand

`main` ist die Standardquelle. Dieser Eintrag trennt den verifizierten
Quellstand von der installierten Produktversion. Die nachfolgenden
Integrationsstände sind noch nicht Teil von `main`. Ihre Git-Zweige beim
Wechsel des Werkzeugs im autorisierten privaten Projekt-Git prüfen
(in der bestehenden Arbeitskopie: Remote `work-private`; in einer neuen
Arbeitskopie den vorhandenen autorisierten Remote einrichten). Ein
Arbeitsverzeichnis eines Assistenten ist keine Wiederherstellungsquelle.

Vor Änderungen `git status` lesen und fremde Änderungen im bestehenden
Arbeitsbaum stehen lassen. Die Zweige lassen sich nach
`git fetch work-private` mit
`git log -1 work-private/work/330-linux-settings` (entsprechend für Notes
oder Windows) prüfen. Erst den Pin vergleichen, dann bei Bedarf einen
eigenen Git-Arbeitsbaum auf dieser Revision anlegen.

| Aufgabe | Integrationszweig | Quellstand |
| --- | --- | --- |
| [#330](https://github.com/maik3531/Magnolie-Organizer/issues/330), Linux | `work/330-linux-settings` | `c418ddfaf5c9de1e422b03fdecb8bb9f92e72747` |
| #330, Linux – manuelle Bild-Gesamtsammlung | `work/330-linux-manual-images` | `6fcaa6cd1d058f29d6b89e5efb940b509f639a5e` |
| #330, Android Notes | `work/330-notes-settings` | `3fb976ecd45fbb6c4ad7a6f059990aa1eaa40d9e` |
| #330, Windows (nur Quelle) | `work/330-windows-media` | `7c83bdee58f2d56235032735b02952a2fc162caf` |
| [#245](https://github.com/maik3531/Magnolie-Organizer/issues/245), Linux – Spiegelung | `work/245-logind-owner` | `e1810778903a4fe534120742b93703684c1e86e6` |
| #245, Linux – privates Testpaket auf installierter Basis | `work/245-user-deb` | `47c84874c069c4700a42d79bc38795005e14320d` |
| #245/#763, Notes – Quellprüfung bestanden | `work/245-notes-user-draft` | `5993dbb3d289f20e2852a21cd20d28053a6ba72c` |

**Geprüft:** Linux-Oberfläche und beide Seiten des Einstellungsabgleichs in
Quell-/Loopback-Tests. Der Abgleich startet keinen Medienvorgang. Linux
gleicht gespeicherte WLAN-Einstellungen auch dann wieder ab, wenn der
Dateivorgang aufgrund eines fehlenden Zielordners oder einer nicht
unterstützten Richtung sicher gesperrt bleibt. Windows: String-/UI- und
portable Prüfungen sowie Windows-Zielkompilierung, kein nativer Medienlauf.

Die kombinierte Wiederholungsprobe ist auf den verlinkten Linux-/Notes-Pins
bestanden: Nach erneutem Verbinden blieb die Übereinkunft auf demselben
verschlüsselten Testkanal trotz unveränderter höherer Fähigkeitsrevision und
verspäteter älterer Meldung auf beiden Seiten erhalten. Kein Dateivorgang.
Das ist kein installierter WLAN- oder Gerätenachweis.

Die manuelle Bild-Gesamtsammlung kann auf dem separaten Linux-Zweig starten,
wenn das lokale Senderecht, eine ausdrücklich gewählte Bildquelle und der
kompatible, empfangsbereite Gegenpart vorliegen. Der Organizer lässt den
Start sichtbar, aber deaktiviert, solange die Voraussetzungen fehlen.
Eine passive Statusabfrage startet nichts. Oberfläche und drei
verschlüsselte Quelltests bestanden:
Abschluss mit zwei Originalen und Archiv, echter Widerruf, sowie sicheres
Anhalten vor dem Versand einer geänderten zugeordneten Handydatei. Der
Rückweg für „Nur Handybestand“ ist dadurch nicht freigegeben.

**Vorrangig [#763](https://github.com/maik3531/Magnolie-Organizer/issues/763):**
Eine zuvor aktive Telefonverbindung muss nach einem Notes-Update ohne Öffnen
der App oder manuelles Umschalten wiederkommen. AUS muss AUS bleiben. Der
Notes-Fix ist als Quellstand `fcfe26935e931df60945bb708a44223ec07f7856`
in `main` enthalten. Die drei gezielten Tests bestanden auf der Standardbasis
und separat auf `work/763-notes-integration`
(`381d2a5724c54e79bd4d8925fa4ae3bbf4d75626`). Die isolierte
Upgrade-Prüfung für AN und AUS ist vorbereitet: Sie kontrolliert den Dienst
und die authentifizierte WLAN-Verbindung noch vor dem Öffnen von Notes.
Die Messlogik ist mit zwölf Einzeltests geprüft; der alte Kandidat wird vor
dem Start abgelehnt. Der passende quellgebundene Nachfolger und der
installierte Nachweis stehen noch aus.

**Danach #330:** den sicheren Rückweg für bereits zugeordnete Handydateien
getrennt nachweisen. Den allgemeinen Neuimport dafür nicht verwenden; die
ursprüngliche Galerie-ID muss erhalten bleiben. Dafür ist auf
`work/330-notes-original-hold-draft` (`86315e3b870f9779a89122a69c59f0f99fb0ac3e`)
eine **noch ungeprüfte** Sperre gegen versehentlichen Neuimport und gegen
eine Auswahl zwischen widersprüchlichen Galerie-Zuordnungen vorbereitet.
Der Entwurf kann bei neu bestätigten Originalen das Android-Volume geschützt
speichern und das wiedergefundene Original lesend gegen Revision und
Dateihash prüfen. Alte Einträge ohne Volume werden nicht umgedeutet.
Ein sicherer Rückweg mit Schutz vor gleichzeitigen Änderungen ist damit
noch nicht nachgewiesen. Native Windows- und
Geräteabnahme stehen ebenfalls aus. Kein weiteres Benutzer-Testpaket; die installierte Ausgabe
nicht aus ihrer Versionsnummer ableiten. [Webcam #503](https://github.com/maik3531/Magnolie-Organizer/issues/503),
[Spiegelung #245](https://github.com/maik3531/Magnolie-Organizer/issues/245)
und [Erweiterung #727](https://github.com/maik3531/Magnolie-Organizer/issues/727)
bleiben getrennte Abnahmen.

Bei #245 darf ein neuer Sitzungsdienst die frühere Sperrfreigabe nicht
übernehmen. 38 isolierte Tests prüfen u. a. den D-Bus-Namenswechsel,
die Entfernung der gebundenen Sitzung und den Ausschluss nichtgrafischer,
entfernter oder nicht eindeutig bekannter Sitzungen. Im KDE-/Wayland-Gast
ordnete logind weder der PID des tatsächlich installierten Organizers
noch dem Prozess an der von GTK verwendeten Wayland-Verbindung eine
Sitzung zu. Das rechtfertigt keine Startfreigabe; der native
Spiegelungslauf bleibt offen.
Der Organizer unterscheidet in der
geprüften Oberfläche eine nicht bestätigte oder gesperrte Desktopsitzung
vom fehlenden WLAN-Gegenpart. Der Start bleibt in diesem Fall gesperrt.
Der Hinweis ist in allen 19 Linux-Sprachkatalogen geprüft.
Ein zusätzlicher isolierter Test mit echtem GTK-Viewer, lokalem
Hintergrunddienst und verschlüsseltem Testgegenpart bestätigt: Ein
simuliertes logind-Sperrsignal stoppt die Ansicht auch ohne weitere
Bilder, lässt die Datenverbindung auslaufen und erhält den Telefon-Steuerkanal.
Das Sperrsignal zwischen Vorbereitung und Sendefreigabe verhindert außerdem
die Freigabe auf demselben Kanal.
Für einen späteren privat installierten Nutzertest ist ein kleiner,
isoliert geprüfter Diagnoseumfang vorbereitet. Die Paketfreigabe und
die native Geräteabnahme stehen noch aus.
Die getrennte Integration für diesen Test basiert direkt auf dem bereits
installierten Linux-Teststand. Browser-Test und 126 isolierte Quelltests
sind bestanden. Binärvergleich und In-place-Startprobe im Debian-Gast
bestätigen die vorhandenen Foto-/Video- und Kamerafunktionen in der
Paketkomposition sowie eine inaktive Spiegelung ohne Gegenstelle. Das ist
kein Beleg für eine Aufnahme oder eine echte Sperre. Das passende
signierte Notes-Paket und der gemeinsame Bildtest stehen noch aus.
Im ersten vollständigen Notes-Lauf bestanden der neue Spiegelungstest
und die drei Update-Regressionsfälle. Ein älterer Job-Test setzte die
aktuell notwendige Einstellung „AN“ in seiner Testumgebung nicht.
Nur diese Testvoraussetzung wurde danach korrigiert. Der vollständige
Folgelauf bestand alle 2.594 Fälle ohne Fehler oder Skips. Der spätere
kanonisch signierte Build bestätigt dieselben 2.594 APK-gebundenen
Testfälle und das bisherige Produktionszertifikat. Im isolierten
Upgrade-Fall AN nahm Notes den Dienst und die authentifizierte
WLAN-Verbindung vor Öffnen der App wieder auf; Paarung und Rechte
blieben erhalten. Der getrennte native AUS-Fall blieb 35 Sekunden
ohne Vordergrunddienst und ohne WLAN-Verbindung, ebenfalls bei
erhaltener Paarung und unveränderten Rechten. Das genaue Paar liegt
für den ausdrücklich gewünschten lokalen Privattest bereit.
Der eigentliche Bild- und Sperrtest durch den Nutzer steht noch aus;
kein Nutzergerät wurde automatisch verändert und kein Testpaket
öffentlich veröffentlicht.
Handy → Organizer benötigt keinen Wayland-Bildschirmmitschnitt auf Linux.
X11 wird dafür nicht pauschal ausgeschlossen; ohne verifizierten
lokalen Sperrzustand gibt es jedoch keinen Start. Die echte Erweiterung
ist eine eigene Funktion und setzt einen nachgewiesenen zusätzlichen
Ausgang voraus.

## Notes #758: genaue JVM-Verbindungsablehnung – 24. November 2026

Der Quellfix [dc1a97e](https://github.com/maik3531/Magnolie-Organizer/commit/dc1a97e51d78afa74de705857fc4c8e20c389b92)
ist in `main` enthalten. `Transport.kt` erkennt im vorhandenen Connect-Schritt
jetzt auch die beiden vollständigen Meldungen `Connection refused (connect failed)`
und `Verbindungsaufbau abgelehnt (connect failed)`. Ein vorhandenes Android-Errno
hat weiterhin Vorrang. Timeout, Reset, Teiltreffer und Fehler nach dem
Verbindungsaufbau ergeben weiterhin keine sichere Nichtannahme.

Geprüft auf der Standardbasis `832519716085cda7fcb720cc5d425999f9bddac6`
mit diesem Fix, Linux und Temurin/OpenJDK 21.0.13.1, unveränderter
Gradle-/SDK-Konfiguration und strikter Abhängigkeitsprüfung. Die Release-Unit-Tests
liefen mit `-PmagnolieFdroid=true`, ohne Produktionssignierung oder Installation.
Die folgende Tabelle dokumentiert den damaligen #758-Lauf. Der anschließende
vollständig grüne Release-Unit-Lauf steht im Abschnitt zu #764.

| Prüfung | Ergebnis |
| --- | --- |
| `Baum1ReceiptTest`, `C.UTF-8` | 12 bestanden, keine Fehler oder Skips |
| `Baum1ReceiptTest`, `de_DE.UTF-8` | 12 bestanden, keine Fehler oder Skips |
| Vollständiges `testReleaseUnitTest` nach Einrichtung des benötigten Test-Elternordners | 2.497 Tests: 2.485 bestanden, 6 fehlgeschlagen, 6 übersprungen; Gate nicht bestanden |
| Gezielter Host-Nachlauf mit vollständigen Voraussetzungen | 16 bestanden, keine Fehler oder Skips |

Der echte Loopback-Ablehnungs-/Wiederholungsfall besteht in beiden Locales und
im Vollgate: Die Sendung bleibt mit unverändertem verschlüsseltem Umschlag
erhalten und wird nach Erreichbarkeit erfolgreich zugestellt. Die ergänzten
Tests prüfen außerdem Android-Errno-Konflikte und mehrdeutige Meldungen.

Die fünf fehlgeschlagenen `PairedPublishedReadbackTest`-Fälle des Vollgates
konnten ihren Python-Testhost wegen fehlendem `pytest` nicht starten. Die sechs
übersprungenen Desktop-Screen-Interop-Fälle benötigen ihr ausdrückliches
Host-Test-Opt-in. Der getrennte Nachlauf mit `pytest` 8.3.5,
`MAGNOLIE_PYTHON`, `MAGNOLIE_DESKTOP_SCREEN_INTEROP=1` und den vorhandenen
synthetischen Linux-Gegenstellen bestand alle fünf Readback-Fälle sowie
`DesktopScreenDraftInteropTest` und alle zehn `DesktopScreenViewerTest`-Fälle.
Der No-Skip-Guard blieb unverändert. Diese Nachläufe sind eigene Prüfnachweise.

**Folgebefund: [#764](https://github.com/maik3531/Magnolie-Organizer/issues/764).**
`KontaktUiUndRessourcenTest` verlangte noch den mit #755 entfernten zusätzlichen
5-mm-Abstand. Diese unbegründete Testannahme ist mit dem unten dokumentierten
Arbeitsschritt beseitigt. Die Oberfläche wurde für #758 nicht geändert.

Die Nachweise gelten für die Standardquelle. Die oben benannte private
Notes-Integration zu #330 war hier nicht verfügbar und ist damit nicht
mitgeprüft. Native Android-/Geräte- und Paketabnahmen bleiben separat offen.

## Notes #764: unbegründete Abstandsforderung entfernt – 24. November 2026

**Die 5 mm waren keine Vorgabe des Nutzers.** Er hat diese fälschlich übernommene
Annahme ausdrücklich widerrufen. Der Quellfix
[3ac8f0a](https://github.com/maik3531/Magnolie-Organizer/commit/3ac8f0a360f6c2b79fad81d369d2d97b48ce4b3d)
entfernt deshalb ausschließlich die entsprechende Assertion aus
`KontaktUiUndRessourcenTest`. Die funktionalen Prüfungen für getrennte,
anfangs geschlossene Bereiche bleiben erhalten; eine neue numerische
Abstandsvorgabe wird nicht eingeführt. Der Produktcode bleibt der mit #755
korrigierte Stand mit normalem Schaltflächenabstand.

| Prüfung auf dem korrigierten Quellstand | Ergebnis |
| --- | --- |
| `KontaktUiUndRessourcenTest` | 4 bestanden, keine Fehler oder Skips |
| Vollständiges bestehendes `testReleaseUnitTest` | **2.497 bestanden, 0 Fehler, 0 Skips; BUILD SUCCESSFUL** |

Der vollständige Lauf enthält auch alle zwölf Wiederholungs-/Quittungstests aus
#758, alle fünf `PairedPublishedReadbackTest`-Fälle sowie die elf
Desktop-Screen-Interop-/Viewer-Fälle. Verwendet wurden die zuvor belegten
Host-Testvoraussetzungen mit `pytest` 8.3.5 und
`MAGNOLIE_DESKTOP_SCREEN_INTEROP=1`. Testfilter, Buildkonfiguration und
No-Skip-Guard sind unverändert. #764 ist damit als Testkorrektur abgeschlossen;
die oben genannten privaten Integrations- und nativen Paketabnahmen bleiben
getrennte Aufgaben.

## Presseschau #765: Veröffentlichungsabgleich – 24. November 2026

Die Presseschau und `docs/PRESSE.md` führen jetzt zusätzlich den direkt
bestätigten LicitPro-Verzeichniseintrag zu Magnolie Notes. Damit sind 17
Verzeichnis- und Listenfundstellen erfasst. Die dort genannten Prüfzeitpunkte
werden nicht als Erstveröffentlichung ausgegeben; die dokumentationsbasierte
Beschreibung zählt nicht als unabhängiger Praxistest. Der Abgleich ergab keinen
zusätzlichen Originalartikel bei den geprüften Einreichungsempfängern.

OpenAPK konnte erneut direkt gelesen werden. Die aktuellen Abrufgrenzen von
FindOpenSources, LibHunt und SilentStars sind getrennt von früheren Belegen
vermerkt. Die LinuxParty-Zusage bleibt für den 27. November angekündigt;
eine veröffentlichte Artikeladresse ist am 24. November nicht bestätigt.

Geprüft auf der Standardbasis `92677041f7cb6678c0318f6acd2ec4c457992d7b`
mit diesen Inhaltsänderungen: 20 Rechtsübersetzungen und 64 statische Ausgaben
konsistent, 562 Sprachrouting-Prüfungen bestanden, Website-Build mit 62
HTML-Seiten und Prüfung der lokalen Links erfolgreich. Es wurden ausschließlich
Website-Inhalte und diese Arbeitsstandsnotiz geändert. Die Veröffentlichung
erfolgt über den bestehenden GitHub-Pages-Ablauf aus `main`.

Nächster inhaltlicher Schritt: Bei belegter Artikeladresse den angekündigten
Beitrag anhand der Originalseite neu einordnen. Einreichungsliste und private
Recherchebelege bleiben außerhalb des öffentlichen Repositorys.

## Presseschau #768: Preisbestätigung und Abendprüfung – 24. November 2026

FindOpenSources zeigt die korrigierte Preiskennzeichnung „Free“ in allen sechs
angebotenen Sprachfassungen. Die englische Preis-FAQ ist ebenfalls angepasst;
die deutschen und niederländischen FAQ enthalten noch den alten Preistext.
Die Abgrenzung zwischen Organizer und Android Notes sowie die genauere
Lizenzangabe bleiben in #595 offen. Der direkte öffentliche Abruf war am Abend
wieder möglich; die frühere Abrufgrenze ist damit im aktuellen Eintrag ersetzt.

Unstock ist nun durch direkt gelesene Vergleichsseiten und das App-Profil
belegt. Diese Ansichten zählen gemeinsam als eine Fundstelle. Die Übersicht
nennt jetzt wie Rubrik und Markdown-Liste 17 Verzeichnis- und Listenfundstellen.
Der erneute Abgleich aller 308 Einreichungsdatensätze und ergänzender öffentlicher
Suchtreffer ergab keine zusätzliche bestätigte Veröffentlichung gegenüber dem
Vormittag. Nicht indexierte Inhalte bleiben unbestätigt; bei zwei Empfängern
lieferte nur eines der beiden Suchsysteme eine auswertbare Antwort. Für die
LinuxParty-Ankündigung vom 27. November ist weiterhin keine Artikeladresse
bestätigt; auch der aktuelle öffentliche Feed enthält keinen Magnolie-Beitrag.

Geprüft auf Standardbasis `aacbf6ee2020fb4157165d8636a515136bd1d497` mit diesen
Inhaltsänderungen: 20 Rechtsübersetzungen und 64 statische Ausgaben konsistent,
562 Sprachrouting-Prüfungen bestanden, Website-Build mit 62 HTML-Seiten und
Prüfung der lokalen Links erfolgreich; `git diff --check` ohne Befund. Die
Inhaltsänderung wird über den bestehenden GitHub-Pages-Ablauf veröffentlicht.

Nächster inhaltlicher Schritt: Belegte neue Artikeladressen ergänzen und die
noch offenen FindOpenSources-Metadaten bei einer späteren Rückmeldung prüfen.
Es wurden keine erneuten Einreichungen oder Nachrichten versendet.

## Presseschau #780: Kampagnenrückmeldungen und Quellenprüfung – 26. November 2026

Die Presseschau und `docs/PRESSE.md` berücksichtigen die neu übermittelte
Freischaltungsbestätigung von PostLaunchKit. Sie bezieht sich auf den bereits
erfassten Eintrag; Übermittlungsdatum, Prüfdatum des Portals und unbekanntes
Erstveröffentlichungsdatum bleiben getrennt. UpdateStar ist jetzt durch das
direkt gelesene öffentliche Profil belegt. Bei LiteFile bestätigen Produktseite
und Katalogübersicht dieselbe Fundstelle; die Beschreibung unterscheidet den
Windows-Organizer von der separaten Android-App.

Die heutigen Originalabrufe von AIDIR3, Freeware-base, Windows 10 Download,
ZIRULAB und OpenAPK sind datiert. FindOpenSources zeigt weiterhin sechs
„Free“-Kennzeichnungen; die deutschen und niederländischen Preis-FAQ sowie
Produktabgrenzung und Lizenzpräzisierung bleiben offen. LibHunt ist beim
Direktabruf weiterhin gesperrt, SilentStars liefert 404. Die LinuxParty-Startseite
und der aktuelle Atom-Feed enthalten am 26. November noch keinen Magnolie-Beitrag;
die Zusage für den 27. November bleibt eine Ankündigung.

Der Abgleich der 319 erfassten Einreichungsvorgänge aus dem aktuellen
Kampagnenstand mit zwei Suchsystemen und zusätzlichen öffentlichen Fundstellen
ergab gegenüber dem 24. November abends keine neue bestätigte Veröffentlichung.
Die 17 Verzeichnis- und Listenfundstellen sowie die übrigen Rubrikenzahlen
bleiben unverändert. Fehlende Suchtreffer belegen kein Nichterscheinen;
unbestätigte Alias- oder Spiegeladressen werden nicht zusätzlich gezählt.

Geprüft auf Standardbasis `00776ce70e155c7a607ed55a4502d6fcee5a860c` mit diesen
Inhaltsänderungen: 20 Rechtsübersetzungen und 64 statische Ausgaben konsistent,
562 Sprachrouting-Prüfungen bestanden, Website-Build mit 62 HTML-Seiten und
Prüfung der lokalen Links erfolgreich; `git diff --check` ohne Befund. Die
Veröffentlichung erfolgt über den bestehenden GitHub-Pages-Ablauf aus `main`.

Nächster inhaltlicher Schritt: Eine belegte Artikeladresse zur angekündigten
Veröffentlichung prüfen und danach neu einordnen. Die privaten Kampagnenbelege
bleiben außerhalb des Repositorys. Es wurden keine Nachrichten oder neuen
Einreichungen versendet; #595 bleibt für ausstehende Portalangaben offen.
