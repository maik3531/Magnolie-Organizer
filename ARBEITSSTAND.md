# Aktueller Arbeitsstand

Die geprüften Einzelissues sind abgeschlossen; die weiterhin benötigten
Paket- und Geräteprüfungen sind in [#113](https://github.com/maik3531/Magnolie-Organizer/issues/113#issuecomment-7215114176)
und [#121](https://github.com/maik3531/Magnolie-Organizer/issues/121#issuecomment-7215113730)
aufgeführt.

## Weitere Abnahme für den Gesamtrelease

- [#809](https://github.com/maik3531/Magnolie-Organizer/issues/809):
  Beide ISO-Abbilder sind anhand offizieller Signaturen geprüft.
  Auf Mint 27 Cinnamon Beta wurden die 2.0.30-Baseline-DEBs
  installiert und verifiziert. Organizer-Einrichtung und Handbuch
  öffneten und schlossen regulär unter X11. Der Bedienvergleich
  mit Mint 22.3 und die Abnahme der finalen Paketbytes stehen aus.
- [#815](https://github.com/maik3531/Magnolie-Organizer/issues/815):
  Der Linux-Hintergrunddienst verdeckt bei einem fehlgeschlagenen
  Telefon-Stopp keine unerwartete Ausnahme mehr. Vier gezielte
  Dienstfälle, ein echter GLib-Lebenszyklustest und die strikte
  Kompilierung mit Python 3.14 sind bestanden.
- [#747](https://github.com/maik3531/Magnolie-Organizer/issues/747):
  Die Bereitschaftsabfrage des Linux-Hintergrunddiensts liest
  den IPC-Status, ohne mit dem Dienst um dessen Start-Sperre zu
  konkurrieren. Das Rennen wurde vor dem Fix reproduziert;
  danach bestanden vier Prüfungen einschließlich beider
  GLib-Neustartvarianten und des Weckerdienstfalls.
- [#748](https://github.com/maik3531/Magnolie-Organizer/issues/748):
  Der Windows-Webcam-Test bereitet beide Test-Gegenstellen vor
  dem Medienstart vor. Der betroffene Fall und insgesamt
  19 gezielte Testgruppen bestanden nativ unter Windows.
- [#831](https://github.com/maik3531/Magnolie-Organizer/issues/831):
  Die Windows-Web-Brücke lässt die vorhandenen Webcam-Befehle und
  Medienfelder bis zu ihren nativen Prüfungen durch. Alle 56 erfassten
  Web-Nachrichten bestanden den Vertragsvergleich, zuvor 38. Acht
  gezielte Gruppen bestanden nativ unter Windows. Die Aufnahme mit
  echter Kamera und Mikrofon bleibt Teil der Geräteabnahme.
- [#830](https://github.com/maik3531/Magnolie-Organizer/issues/830):
  Der Downloadgenerator erhält benachbarte URL-Konstanten und damit
  den F-Droid-QR-Eintrag im Linux-Erstassistenten. Neun Prüfungen und
  das Generator-Gate bestanden mit unveränderten Downloadzielen.
- [#829](https://github.com/maik3531/Magnolie-Organizer/issues/829):
  Der Linux-/Windows-Quellvergleich prüft 153 Befehle, 97 Rückrufe
  und sieben unterschiedlich benannte Medienwege. Der Linux-Sender
  erzeugt dieselben Foto-/Video-Freigabefelder; sieben Vergleichsfälle
  und die reproduzierbare Erzeugung des Vertrags bestanden.
  [#833](https://github.com/maik3531/Magnolie-Organizer/issues/833):
  Die Linux-Quellordnerprüfung meldet für ihre Testgegenstelle den
  erforderlichen WLAN-Status. Zehn Quellordner- und 20 benachbarte
  Medien-Wiederherstellungsprüfungen bestanden.
- [#832](https://github.com/maik3531/Magnolie-Organizer/issues/832):
  Eine veraltete Handbuchkopie wird nach vollständigem Bytevergleich
  mit Dateiname und kurzer Fehlermeldung abgelehnt. Drei Prüffälle sowie
  der Test der kanonischen Quelle über 170 Seiten bestanden.
- [#824](https://github.com/maik3531/Magnolie-Organizer/issues/824):
  „Alles“ zeigt und bestätigt beim Wiederherstellen das vollständige
  Ersetzen. Nach dem Abwählen gilt wieder das zuvor gewählte Verfahren
  für Teilbereiche. Zwölf Dialogprüfungen auf Linux-/Windows-Quellen
  sowie der Handbuchhinweis in 20 Sprachen und auf beiden Plattformen
  bestanden. Der native Wiederherstellungsablauf bleibt unverändert.
- [#821](https://github.com/maik3531/Magnolie-Organizer/issues/821):
  Notes begrenzt den gesamten Ordnerimport und speichert erst nach
  vollständig erfolgreicher Vorbereitung. 28 JVM-Prüfungen und die
  Handbuchprüfung in 20 Sprachen auf beiden Plattformen bestanden.
  Die Prüfung echter Android-Dokumentanbieter bleibt offen.
- [#810](https://github.com/maik3531/Magnolie-Organizer/issues/810):
  Mac und Android-Tablet sind als Quellen übernommen. Die
  Entwicklungsbundles und Debug-APKs sind noch keine normal
  signierten Releaseartefakte. Der lokal nachgeholte Tablet-Bau
  `c9745c9e` bindet beide Debug-APKs an den exakten Quellstand;
  303 Unit- und 194 Webtests sind bestanden. Auf API 34 waren
  Start, Editor, verschlüsselte Ablage, Wiederöffnen und
  Layout erfolgreich. Die vollständige native Abnahme ist offen.
- [#811](https://github.com/maik3531/Magnolie-Organizer/issues/811):
  `c363dc01` aktualisiert den Prüfer für die Zeitzonenidentität
  der Serien-Worker-Jobs. Im quellgebundenen API-34-Lauf wurden
  17/17 fertige echte Worker-Jobs und 17 eindeutige datierte
  Vorkommen bestätigt. Zwei echte Registerwechsel bestanden.
  Die dritte Zielvorbereitung erreichte ihr Zeitlimit;
  der weitere Touch-Nachweis steht in
  [#816](https://github.com/maik3531/Magnolie-Organizer/issues/816).
- [#330](https://github.com/maik3531/Magnolie-Organizer/issues/330):
  Die Linux-Korrekturen des Einstellungsabgleichs fehlten in dem
  privaten DEB. Auf `work/330-linux-settings-on-user-deb`
  (`f1ad42a6138671a4c2a5cda70c09eac3d562a34a`) sind 30 verschlüsselte
  Linux-Prüffälle bestanden. Der anschließende Quelltest mit dem
  vorgesehenen Notes-Stand bestätigte Wiederverbindung und
  verspätete Duplikate beider Leser ohne Transfer.
  Das [Upgrade des privaten Linux-Pakets](https://github.com/maik3531/Magnolie-Organizer/issues/330#issuecomment-7216108304)
  auf Debian 13 bestand mit 15 bestätigten installierten Prüfsummen
  und regulärem Fensterschluss. Zwei [isolierte Android-Updateproben](https://github.com/maik3531/Magnolie-Organizer/issues/330#issuecomment-7216893207)
  mit exakt dieser Linux-Paketkomposition bestätigen erhaltene Kopplung
  und Rechte, erneut vereinbarte Medienwahl AUS nach dem Wiederverbinden
  und keinen Transfer. Der echte Originaltransfer bleibt offen.
  Fünf Notes-Tests für den getrennten lesenden Galerieentwurf
  bestanden. Alte Telefonreferenzen bleiben vom Neuimport getrennt.
  Rückschreiben in dieselbe Galeriezeile ist weiterhin offen.
- [#753](https://github.com/maik3531/Magnolie-Organizer/issues/753):
  Die optionale Messung ist ausschließlich im Test aktiv. Elf
  Recorderprüfungen und die automatische Bildprobe bestanden.
  Die Bildprobe benötigte 11,862 Sekunden Ereigniswartezeit bei
  unverändertem 12-Sekunden-Limit. Das ist keine Beschleunigung
  und kein Nachweis am installierten Paket.
  Die Testfixture konkurriert jetzt nicht mehr mit dem Worker um
  dessen Einstellungszugriff. Nach dieser Korrektur bestanden
  30 private Medienfälle sowie zwölf Standardprüfungen; die
  Standard-Bildprobe schloss nach 11,661 Sekunden ab.
- [#812](https://github.com/maik3531/Magnolie-Organizer/issues/812):
  Der Regelkalender-Test findet seine Vektoren und die Python-Referenz
  auch im eigenständigen Windows-Quellarchiv. Die Prüfung der 1.434
  Archiveinträge und je 9.260 Assertions aus dem Checkout und dem
  entpackten Archiv bestanden. [#813](https://github.com/maik3531/Magnolie-Organizer/issues/813)
  ist ebenfalls geprüft: Alle 19 Windows-Sprachkataloge bestehen
  im Checkout und nach Regeneration aus dem entpackten Archiv.
  Der Medien-Wiederherstellungstest [#814](https://github.com/maik3531/Magnolie-Organizer/issues/814)
  prüft den direkt sichtbaren Offline-Bereich ohne aktive Notes-Verbindung.
  Je 20 UI-Fälle und 19 Kataloge bestehen im Checkout und im Quellarchiv.
  Die vollständige Windows-Abnahme steht in #113.

## Linux-Telefonstatus und lokale Buchspeicherung – 27. November 2026

Die geprüften Issue-Patches #760 und #761 sind übernommen. Bei einem
fehlgeschlagenen Hintergrunddienst-Lesezugriff zeigt der Organizer
eine nicht verfügbare Telefonverbindung und aktualisiert sich wieder
nach erfolgreicher Antwort. Der lokale Buchcodec bildet den Nachweis
für die Medien-Aufbewahrung auch bei gültigen Dezimalzahlen.
39 fokussierte Tests und vier zusätzliche Zielordner-IPC-Fälle
bestanden. Der Auslöser des früher gemeldeten GUI-Abbruchs ließ sich
nicht bestimmen. Die installierte Speicher- und Wiederöffnungsprobe
für die Medienaufbewahrung steht in #113.

[#762](https://github.com/maik3531/Magnolie-Organizer/issues/762):
Notes berücksichtigt nach authentifizierter WLAN-Rückkehr verspätete
Inhaltsfreigaben, bevor es den einmaligen automatischen Abgleich auslöst.
Alle 135 gezielten Notes-Tests bestanden, einschließlich der Fälle für
gültige Alt-Läufe, Widerruf und ersetzte Verbindungen. Die Heimkehrprobe
mit der persönlichen Organizer-Gegenstelle wurde nicht ausgeführt.

## Windows-Testbereinigung – 27. November 2026

[#794](https://github.com/maik3531/Magnolie-Organizer/issues/794):
Auf echtem Windows war `phone.db` nach dem WLAN-Medientest noch
geöffnet. Die Fixture gibt jetzt ihre beiden eigenen SQLite-Pools
frei. Der zuvor rote Einzeltest, elf Webcam-Nachbargruppen und der
Isolationstest für unabhängige Pools bestehen nativ. Die Telefon-
und Medienlogik im Produkt bleibt unverändert.

## Mac-Integration – 27. November 2026

Der Mac-Quellstand aus `work/macos-issue-fixes-20261126` ist mit der
bereits integrierten Tablet-Serie zusammengeführt. Der native
[Mac-Lauf auf ARM64 und Intel](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45827353062)
belegt den Entwicklungsbau und App-Lebenszyklus auf macOS 15.
In der kombinierten Quellfassung bestanden die Windows-Archivprüfung
mit 1.427 Dateien, 321 Geburtstagstests, 72 Herkunftschecks für
Erinnerungskopien und 88 Setup-Feiertagsfälle. Die neue gemeinsame
Tablet-Projektion bestand 194 Web- und 46 Import-/Anhangsprüfungen
im Host-Test.
Produktionssignatur, Notarisierung und die offenen Systemanbieter- und
iPhone-Prüfungen brauchen eigene Nachweise.

## Tablet-Integration – 27. November 2026

Die Quellserie aus [PR #795](https://github.com/maik3531/Magnolie-Organizer/pull/795)
ist mit dem aktuellen Standardstand zusammengeführt. Gegenüber dem
[API-34-Lauf mit 303 Unit-Tests und Providerprüfung](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45822320243)
blieben die Tablet-Laufzeitquellen und ihre gemeinsamen Eingaben unverändert.
Die 24 Provenienztests und die Windows-Archivprüfung mit 1.406 Dateien
bestanden bei der Übernahme. Der historische Tablet-Audit bleibt im
Repository und gehört nicht in das eigenständige Windows-Quellarchiv.

Offen bleiben die in #795 aufgeführten Android-Laufzeitprüfungen und das
signierte Tablet-Release. Der geprüfte Debug-Bau ist kein Release-Paket.

## Nachprüfung und spätere stabile Übernahme – 26. November 2026

**Aktueller Quellkandidat:** `3f3ec069895dec254c53660d14e6851cb23077cd`,
Tree `176fa7f362227c92ec4d7c4bf08d09b855951ae7`, gesichert auf
`work/macos-issue-fixes-20261126`. Der erweiterte native
[Lauf #104](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45827353062)
ist auf **ARM64 und Intel vollständig erfolgreich abgeschlossen**. Er lief am
26. November von **14:15:18 bis 14:49:42 Uhr Europe/Berlin**. Spätere reine
Berichtscommits sind nicht mit diesem tatsächlich geprüften Quellcommit
gleichzusetzen.

Beide Architekturen bestehen je **26 Runtime-, 27 AirPlay- und 17 Helperfälle**,
die Host-Suite mit **34 bestandenen Fällen und einem Linux-only Skip**, vier
Debug-Swift-Kontexte sowie den zusätzlichen optimierten Release-Testkontext.
Die fünf Kontexte enthalten dieselben **501 Testnamen**; keine Fehler, je nach
Kontext 4/5/5/6/6 dokumentierte Skips. Die neue echte Swift→gebündelte
Python-Prozessprobe bestätigt **9/9 Kriterien**, der App-Lebenszyklus **7/7**.
Die unabhängige Prüfung beider tatsächlichen Pakete besteht je **65/65 Checks**.
Der [dauerhafte #104-Gesamtbeleg](Magnolie-Organizer-macOS-Beta/verification/native-run-104.json)
sichert die zugehörigen Quell-, Log-, Paket- und Prüfsummenbindungen.

Der getrennte Windows-Lauf **#552** auf `8c860a14` ist dagegen mit **551 von
552 bestandenen Core-Testgruppen** fehlgeschlagen. Die weiterhin geöffnete
`phone.db` beim Fixture-Cleanup reproduziert #794; dafür wurde hier kein
Windows-Produktfix vorgenommen. Die Mac-Ergebnisse ersetzen diese offene
Windows-Abnahme nicht.

Die zusätzlichen gemeinsamen Hostregressionen und die vollständige
Wiederherstellung aller 24 Originalpatches sind abgeschlossen. Der
[Stabilitätsbericht](Magnolie-Organizer-macOS-Beta/STABILITY-VERIFICATION-2026-11-26.md)
sichert Ergebnisse, Quellenhashes, Fehlversuche und Prüfgrenzen. Der
[Übernahmeplan](contracts/macos-stable-integration-2026-11-26.md)
ordnet Folgecommits, spätere gemeinsame Änderungen und stabile Freigabegates.
Die gezielte Remote-Nachprüfung um **14:16:51–14:16:58 Uhr Europe/Berlin**
bestätigt `main` auf `d4da48a5`, 0/23 Commits und einen konfliktfreien
Merge-Tree exakt gleich dem Kandidaten. Der abschließende API-Read um
**14:52:15 Uhr Europe/Berlin** bestätigt dieselbe Main-Referenz. Es wurde kein
Merge ausgeführt.

### Erhaltener Verlauf der erweiterten Nachprüfung

Die Nachprüfung hat den engen Bauprüferrest #806 bestätigt und als eigenen
Quellcommit `6599dcb2a7d337f4b248b8b172e5e18c537a2dfa` gesichert: eindeutige
macOS-Plattform-/Mindestversionsangabe für Runtime, App und optionales AirPlay.
Lokal bestehen 23 Runtimefälle mit einem zusätzlichen Darwin-only Skip und
26 AirPlayfälle. Der folgende native Lauf ergänzt genau diesen Darwin-Fall,
den tatsächlichen Swift→ImportHelper-Prozessweg und optimierte Swift-Tests.
Bis zur echten Ausführung bleiben diese neuen nativen Gates offen.

Der tatsächliche [Lauf #100](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45821167801)
auf `8c860a14f7e10904c1b3a159ae84619c2c24ba82` hat auf beiden Architekturen
einen direkten Nachbesserungsrest in #806 aufgedeckt: Der positive native
Mach-O-Test verwertete neben `minos` auch die im selben `LC_BUILD_VERSION`-
Block ausgegebene Linker-`version` als Deploymentwert. Je 24 Runtimefälle
endeten deshalb mit genau einem Fehler; der eigentliche Runtimebau und die
nachfolgenden Gates wurden nicht ausgeführt. Die Korrektur liest beim modernen
Command ausschließlich `minos`, beim ausdrücklich erlaubten Legacy-Command
ausschließlich dessen `version`. Plattform-, Mehrdeutigkeits- und
Mindestversionsgrenzen bleiben bestehen; zwei neue Regressionen bilden die
echte Apple-Ausgabestruktur ab. Lokal bestehen danach 24 Runtimefälle mit
einem zusätzlichen Darwin-only Skip und 27 AirPlayfälle. Ein neuer nativer Lauf ist für diesen
Nachbesserungsstand erforderlich. Der fehlgeschlagene #100-Beleg bleibt erhalten.

[Lauf #102](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45823313660)
prüft `625233067cd49e204786deb5706e6bc08ef85c4e`. Beide abgeschlossenen
Mac-Jobs bestätigen je **25 Runtimefälle ohne Skip**, einschließlich der
echten Mach-O-Positiv-/Fremdplattformprobe. Die erstmals nativ mitlaufende
AirPlay-Suite zeigt danach zwei Testwurzelvergleiche mit `/var` statt
`/private/var`. Dieser Callerrest gehört zu #793: Ein echter temporärer
Linux-Elternalias reproduziert beide Fehler. Nur die unmittelbar selbst erzeugte
Wurzel in `BundleCase.setUp` wird nun kanonisiert; Produktcode und SDK-/Linkgrenzen
bleiben unverändert. Danach bestehen lokal 27/27 AirPlayfälle und gezielt beide
zuvor gescheiterten Fälle unter dem echten Elternalias. Der eigentliche
Runtimebau und die weiteren nativen Gates benötigen einen neuen Folgelauf.
#102 endete auf beiden Architekturen mit genau diesem Testwurzelbefund.

[Lauf #103](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45824626525)
auf `f7957801ba99c0e65e7eaeb70f69824efcd55fd0` bestätigt auf ARM64 und Intel
je **25 Runtime- und 27 AirPlayfälle ohne Fehler oder Skip**. Der danach
gestartete tatsächliche XZ-Bau scheitert jedoch nach erfolgreichem `configure`:
Der sichere Quellenextraktor verwirft Archivzeitstempel, sodass später
entpackte, tatsächlich ältere Eingaben unnötig `am--refresh` und das fehlende
`aclocal-1.18` auslösen. Der ursprüngliche Abbruch bleibt als eigener Beleg
erhalten; CPython, Host-, Importprozess-, weitere Swift-, App- und Paketgates
wurden in #103 nicht erreicht.

Der vor Änderung angelegte neue Befund
[#808](https://github.com/maik3531/Magnolie-Organizer/issues/808) ist mit dem
echten hashgeprüften Archiv auch auf Linux reproduziert. Der enge Fix erhält
beim bisherigen exklusiven Kopieren regulärer Quelldateien deren Archiv-mtime;
Pins, Pfad-/Link-/Größengrenzen und Baubefehle bleiben unverändert. Eine echte
Make-Regression scheitert vor dem Fix und besteht danach: ältere, später im
Archiv stehende Eingaben lösen keinen Neubau aus, eine tatsächliche spätere
Änderung löst ihn weiterhin aus. Die Runtime-Suite führt lokal **26 Fälle**
aus: **25 bestanden, ein Darwin-only Skip**. Der tatsächliche produktive
XZ-Bauhelfer besteht anschließend `configure`, statischen lib-only-Bau und
private Installation; alle **655 Quelldateien** behalten Archivbytes und
Zeitstempel. Ein neuer vollständiger nativer Folgelauf ist erforderlich.

## Fortsetzung: native Mac-Läufe und konkrete Folgefixes – 26. November 2026

**Nativer Abschluss auf ARM64 und Intel:** [#97 / 45807249788](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45807249788)
ist auf genau `215d89029df02df2dce78f35412785ec9f9b36d8` erfolgreich.
Beide Architekturen bestanden Runtimebau, 21 Runtimebuildertests,
17 ImportHelper-/Pfadtests, 35 Hosttests ohne Fehler mit einem Skip und
vier Swift-Kontexte mit jeweils 501 Fällen ohne Fehler (4/5/5/6 Skips).
Auch äußere App-Signatur, tatsächlicher Start, Speichern, normales Beenden,
Wiederöffnen und Entwicklungspaketierung sind bestanden. Der vorherige
Signaturrest #802 ist damit nativ bestätigt behoben. Vollständige produktive
UI-, Monterey-, TCC-, Konto- und Geräteabnahme bleiben gesonderte offene Teile.

Die Übergabe aus dem unterbrochenen Chat wurde auf dem unveränderten Remote-Head
`97baf780fa3474eba54d03e41d0258c97ae8b1ca` wieder aufgenommen. Alle 24 Patches,
29 SHA256SUMS-Einträge, 30 publizierten Manifestdateien und 31 vollständigen
Issue-Kommentartexte wurden erneut auf Identität geprüft; keine Abweichung und
keine doppelte Veröffentlichung. Die entfernte Main-Basis ist weiterhin
`d4da48a5eadd0bda22422b924bef4ee3b4324040`.

Über die bereits angemeldete GitHub-Weboberfläche wurde der vorhandene Workflow
gezielt mit `target=macos` auf dem Arbeitszweig gestartet:
[Lauf 45786948279](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45786948279).
Dies ist ein tatsächlicher neuer nativer Lauf, kein historischer CI-Beleg.
Beide Architekturen bestätigten dieselben zwei Swift-Kompilierfehler; [#788](https://github.com/maik3531/Magnolie-Organizer/issues/788)
behebt die verdeckte `text`-Instanzmethode und die throwing Kurzschlussauswertung
mit unveränderter Import-/Konfliktsemantik. Der tatsächliche
[Folgelauf #92 / 45788423617](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45788423617)
auf `689266570cda17f463132a182c02d78ea732dfbd` hat die BetaCore-Kompilierung
und beide Zeitzonenreferenzphasen auf **ARM64 und Intel** bestanden. Vorhandene
native XCTest-Fälle bleiben erhalten; ihre spätere Ausführung wurde noch nicht
erreicht.

Beide Architekturen scheiterten anschließend im privaten Runtimebuilder an
den regulären CPython-Buildlinks; beide Logs bestätigen außerdem fehlendes
`_lzma`. [#789](https://github.com/maik3531/Magnolie-Organizer/issues/789) begrenzt
die Korrektur auf streng validierte gleichnamige Quellziele und privat statisch
gebautes liblzma aus verifiziertem XZ 5.8.4. Der ausgelieferte Runtimebaum bleibt
symlinkfrei; Modulmenge, Architektur-/Mindestversions-/Systemlink-, Signatur-
und Relokationsgates bleiben erhalten. Die XZ-Quelle und ihre begrenzte
statische Linux-Baufolge wurden tatsächlich geprüft; dies ersetzt keinen
nativen Mac-Runtime-Erfolg. Die erweiterte Runtimebuilder-Suite besteht lokal
mit **13/13 Tests**. [Mac-Lauf #93 / 45791918626](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45791918626)
hat auf genau dem veröffentlichten Fixcommit
`cc9dc29a606658b7937eb7261409564c96f93775` den Runtimebau auf **ARM64 und Intel
bestanden**: isolierter Modulabschluss einschließlich LZMA, je 704
inventarisierte Dateien und 52 Mach-O-Dateien, deklariertes Deploymentziel 12.7, nur
Systembibliotheksabhängigkeiten sowie beide originalen XZ-Lizenztexte.

Beide Jobs zeigten danach denselben nächsten Prüftreiberrest
[#793](https://github.com/maik3531/Magnolie-Organizer/issues/793): selbst erzeugte
temporäre Wurzeln laufen über den macOS-Systemalias `/var`, den die strikte
Projektion zurückweist. Die ImportHelper-Suite kam deshalb auf 0 ausgeführte
Tests; XCTest und Bundle-/App-Abnahme wurden noch nicht erreicht. Der
Callerfix kanonisiert nur unmittelbar selbst angelegte Tempwurzeln; die
allgemeine Quell-/Projektionspfadprüfung bleibt unverändert. Ein echter
Linux-Elternsymlink hat den ursprünglichen Fehler reproduziert. Danach
bestanden alle drei gezielten Dateisystemregressionen, auch mit einem
Elternalias im Tempstamm. Die vollständig betroffenen Check-/Testaufrufer
verwenden denselben engen Korrekturpfad; `safe_path` bleibt textgleich.
Der vollständige aktuelle Host-/Apple-Erfolg ist noch nativ zu prüfen.

[Mac-Lauf #94 / 45794303684](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45794303684)
hat auf `8c01f75b2ae6a9e753b9c23b0e3c65a7d7826c66` den Pfadfix auf ARM64
und Intel bestätigt: je **17 ImportHelper-/Pfadtests**, frische UI-Projektion
und **90 OR6→UI-Prüfungen** bestanden. Die folgende Hostsuite endete je mit
35 Tests, vier Fehlerergebnissen und einem Skip. Die vollständige Swift-Suite
kompilierte und führte je Lauf 498 Tests aus; wiederholt erscheinen dieselben
fünf Assertions in drei Fällen. Ein separater Kommunikations-Harnessfehler
komplettiert den Befund; noch kein App-Bundle-/Smoke-Erfolg.

[#796](https://github.com/maik3531/Magnolie-Organizer/issues/796) korrigiert die
fehlende echte Zeitzonen-Bootstrap-Ladung des Kommunikationsprüfers aus dem
Rohcheckout. Danach stimmen lokal alle 15 Payloads mit der bytegleichen
historischen Fixture überein; ausdrücklich gelieferte Projektionen müssen
ihre eigene Datei besitzen. [#797](https://github.com/maik3531/Magnolie-Organizer/issues/797)
korrigiert zwei unzutreffende Swift-Testprüfungen (Notes-Reason vs. Bodyfeld,
Character- vs. Byteentfaltung) und ersetzt den verlustbehafteten JSON-Reparse
vor der Reminder-Editorprüfung durch eine begrenzte native Wertkopie.
Originaltext, mutable-input-Isolation, Budgets und Revisionbindung bleiben
Gegenstand der gezielten nativen Regressionen. Die lokale Umgebung hat kein
Swift; der nachfolgende echte Mac-Lauf bestätigt die Änderungen.

[Mac-Lauf #95 / 45799895334](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45799895334)
prüfte exakt `3c0b4bb410a5ab514e3deae7fb665a692eb436c2`. Auf ARM64 und
Intel bestehen nun beide gesamten Hostläufe: **35 Tests, 0 Fehler, 1 Skip**
(594,947 beziehungsweise 800,281 Sekunden). Alle vier Swift-Gesamtläufe
führen je **501 Tests ohne Fehler** aus; die Kontexte haben je **4/5/5/6
Skips**. Die Wiederholungen werden nicht addiert. #796/#797 sind damit auf
beiden Architekturen nativ bestätigt, einschließlich der neuen FEFF-,
Revision-, Textkopier- und Faltungsregressionen.

Der App-Code kompiliert. Erst die äußere Appsignatur scheitert auf beiden
Rechnern am gemischten Python-Verzeichnis unter `Contents/Helpers`: ARM64
meldet `runtime.json`, Intel `LICENSE-XZ-Utils.txt` als unsignierten Code.
Der neue Folgeauftrag [#802](https://github.com/maik3531/Magnolie-Organizer/issues/802)
trennt deshalb Programm, native Plug-ins und Ressourcen in einem echten
internen Helper-Bundle. Ein begrenzter isolierter PyConfig-Launcher erhält
den statischen Python-Kern und feste interne Suchpfade. Das SDK-Inventar
entsteht außerhalb des Helpers nach dessen Signatur; die äußere App wird
zuletzt signiert. Die erweiterte Runtime-Hostsuite besteht mit 21/21 Tests;
lokale C/API-Proben und unabhängiger Quellreview sind abgeschlossen.
App-Smoke und Entwicklungspaketierung sind in #95 noch nicht erreicht.
Der tatsächliche Folgelauf #97 bestätigt den veröffentlichten Layoutfix auf
beiden Architekturen einschließlich der äußeren Appsignatur und aller sieben
App-Smoke-Kriterien. Zwei Entwicklungskandidaten mit Quellen-, Runtime-,
Build-, Signatur- und Lebenszyklusbelegen wurden erzeugt und heruntergeladen.
Die Aufbewahrung der CI-Artefakte beträgt 14 Tage; es ist keine Releasefreigabe.

Der zusätzliche Desktop-Archivblocker
[#787](https://github.com/maik3531/Magnolie-Organizer/issues/787) ist im Quellstand
eng korrigiert: Windows und die gemeinsame Linux-Quellauswahl schließen nur die
zwei konkreten publizierten Mac-Belegverzeichnisse aus. Neue reguläre Verträge,
Pflichtdateien und die Inhalts-/Pfadprüfung bleiben erhalten. Die Regression
reproduzierte vor dem Fix beide Python-Varianten; danach bestanden 7/7 Tests
und die byte-/modusgleiche Projektion aller 138 ausgewählten echten Verträge.
Der native [Windows-Folgelauf 45788221321](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45788221321)
auf dem Archivfix hat die erweiterten nativen Archivregressionen mit explizitem
Erfolgsmarker bestanden. Die folgenden CoreTests endeten mit **551/552**:
Ein separater `phone.db`-Cleanupfehler des Medienprüffalls ist im Folgeauftrag
[#794](https://github.com/maik3531/Magnolie-Organizer/issues/794) dokumentiert.
Dadurch scheiterte der Gesamtworkflow; ZIP-/Installerbau und Artefaktupload
wurden übersprungen. Der erfolgreiche Archivnachweis wird davon getrennt
ausgewiesen. Der Stand und die
Grenzen der nativen Fortsetzung stehen in
[NATIVE-VERIFICATION-2026-11-26.md](Magnolie-Organizer-macOS-Beta/NATIVE-VERIFICATION-2026-11-26.md).

Der Nutzerauftrag bleibt die reviewbare Patch-/Issue-Übergabe für Codex.
Kein Merge nach `main`, keine Issue-Schließung und keine Releaseveröffentlichung.

## Veröffentlicht: 31 Mac-Issue-Übergaben – 26. November 2026

Der Arbeitszweig `work/macos-issue-fixes-20261126` ist auf GitHub verfügbar.
**Alle 31 zugeordneten Issue-Kommentare sind veröffentlicht und einzeln mit
identischem vollständigem Text zurückgelesen.** Die festen Beleglinks zeigen
auf den Dokumentations-/Artefaktstand `cf7b3f2bf4e8afee662a4926f32fc989d7ff7df8`.
[Alle Kommentar-URLs und Publikationsbelege](contracts/macos-issue-publication-receipts-2026-11-26.md)
sowie [Zusammenfassung und Fortsetzungs-Prompt](contracts/macos-next-chat-prompt-2026-11-26.md)
sichern die Übergabe unabhängig vom bisherigen Chat.

API-Quellcommit `8efc6834abd16f18300f3d59a1897c81758b0c34` enthält exakt den
Originaltree von `0dfeb1b30a208480eb6901e3d3148a5efeaae5ff`; die ursprünglichen
Einzelcommits sind im geprüften Git-Bundle erhalten. Die
[Wiederherstellungsanleitung](contracts/macos-issue-publication-2026-11-26/CODEX-RESTORE.md)
ordnet die unterschiedlichen Commitmetadaten und die 24 Patchdateien zu.
Nachfolgende Publikationsbelege ändern keine Produktquellen.

Die zusätzlichen [Dell-/NFC-Befunde](contracts/windows-dell-nfc-research-2026-11-26.md)
und [sechs Windows-Featurevorschläge](contracts/windows-feature-opportunities-2026-11-26.md)
sind recherchierte Entwicklungsaufträge, keine implementierte neue Authentisierung.
Die vollständige native UI-, Monterey-, TCC-, Konto- und Geräteabnahme sowie
die nachstehenden technischen Restpunkte bleiben offen; der definierte
CI-Umfang von #97 ist inzwischen bestanden. Die ursprüngliche Übergabe
änderte weder `main` noch Issue-Zustände oder veröffentlichte Pakete.

## Mac-Issue-Audit, aktuelle Importe und Apple-Abgleich – 26. November 2026

**Vollständiger Prüfzweig: `work/macos-issue-fixes-20261126`.** Der abschließend
geprüfte Codecommit ist `7c9cf20394aef73d261a77f746ebca7340826d30`; die
nachfolgenden Übergabedateien dokumentieren genau diesen Implementierungsstand.
Die Main-Basis `d4da48a5eadd0bda22422b924bef4ee3b4324040` ist enthalten und
wurde vor Auslieferung erneut unverändert bestätigt. Die bisherige komplette
Mac-Folge bis `616069f1` bleibt erhalten. Nutzerauftrag: reviewbare Patches und
Belege in den jeweiligen Issues für die spätere Codex-Prüfung und Übernahme.

Alle 128 aktuell offenen Issues wurden abschließend abgeglichen: 31 gehören
zur Mac-Übergabe (26 ursprüngliche plus #781/#783/#784/#785/#786), 97 haben einen
individuell dokumentierten Ausschlussgrund. #9/#455/#460 sind zusätzlich als
bereits geschlossene historische Fälle nachverfolgt. Maßgeblich sind:

- [Gesamtbericht mit Einzelbefunden und Patchreihenfolge](contracts/macos-issue-handoff-2026-11-26.md).
- [Maschinenlesbares vollständiges Inventar](contracts/macos-issue-inventory-2026-11-26.json).
- [Tatsächliche Prüflogs und Quellbindungen](contracts/macos-verification-2026-11-26/README.md).
- [Recherchierter Cloud-/macOS-VM-Prüfplan](Magnolie-Organizer-macOS-Beta/CLOUD-MAC-TESTING.md).

### Inhalt der neuen Folge

#783 entfernt die Rücksetzung aktueller gemeinsamer Mac-Bauquellen auf die
veröffentlichte Desktopbasis v2.0.30. Source-Proof, Freeze und reproduzierbare
Projektion binden die konkreten Bytes. #784 korrigiert die Geräteseite auf
vorhandene Mac-Einstiege. Es wird **keine eigene Magnolie-Notes-Begleitapp**
vorausgesetzt; bestehendes KDE Connect und Apple-Programme bleiben im Umfang.

#785 stellt aktuelle ICS/VCS/LCS-, OR6/CSV-, vCard/CSV-, Claws/LDIF-, klassische
ZIP- und Müllvorschauparser bereit. Das originale `magnolie_or6.py` bleibt
bytegleich. Ein gebündelter privater CPython-Interpreter, konkreter Regional-
und Zeitzonenkontext, Byte-/Manifestbindung, native Auswahl sowie gemeinsame
Vorschau und Save-ACK bilden die neue Route. Gesamtarchiv und lokale
Programmerkennung sind präzise dokumentierte Folgearbeiten. Der unabhängig
belegte optionale zstd-Konfigurationspfad ist explizit deaktiviert.

#786 verbindet einen bewusst gebundenen manuellen Kalender-/Kontakt-/
Erinnerungs-Feldabgleich mit echten Provideradaptern, Dreiwegevergleich,
Readback, verschlüsseltem Journal und unabhängig gelesenem lokalen
Speicherabschluss. Bestehende Kopien erteilen keine Quellberechtigung.
Neuanlagenexport, Löschungen, Serien/weitere Felder, Automatik, geführte
Ungewissheits-Recovery und vollständiger Apple-Notes-Rückabgleich bleiben offen.
Die öffentlichen Apple-APIs bieten keinen von uns nachgewiesenen atomaren
Vergleich-und-Schreibabschluss gegenüber gleichzeitig ändernden Apps.

Weitere gezielte Korrekturen betreffen #771 (Zeitfenster), #778/#781
(Importfehler und Speicherbestätigung), #776 (gemeinsame Kontaktgeburtstage)
sowie Teilfixe #465/#511. #779 erhielt einen echten Regressionstest, weil der
zunächst vermutete Metadatenverlust nicht auftrat. Die Einzelbelege benennen
die jeweilige Reichweite; die verbleibenden Teile werden nicht geschlossen.

### Tatsächlich geprüft und weiter ausstehend

Der integrierte Schlusslauf bestand **35/35 Hostgruppen in 118,272 Sekunden**.
Dazu gehören die 107 neuen Sync-UI-Prüfungen in EN/DE. Separat bestanden
14 Parsergruppen mit allen 27 originalen OR6-Fixtures, 90 echte OR6→Helper→UI-
Prüfungen, sieben Runtimebuildertests und die Quellselektionssuite. Die aktuelle
UI-Abgrenzung bestand 27 Assertions, 30 originale Notizsuchfälle und 181
nicht angebundene Desktopbefehle. Die Umfänge überlappen und werden nicht addiert.
Zwei Testtreiberfehler im ersten Gesamtversuch sind mit ihrer Korrektur und dem
vollständigen erfolgreichen Wiederholungslauf im Rohprotokoll erhalten.

Diese Umgebung „Magnolie-Organizer einrichten“ ist tatsächlich Linux x86_64;
Swift/Apple-SDK, Modulrechte und `/dev/kvm` fehlen. Hier wurden kein neuer
nativer Mac-Bau und kein Apple-/KDE-Konten-/Gerätelauf ausgeführt. Die neuen
Swift-Tests, CPython-Apple-Bau-/Signatur-/Relokationsgates und echten Bundle-
Prüfungen sind vorbereitet. Geeignete echte macOS-VMs sind der vorgesehene
Prüfweg; eigener physischer Macbesitz ist nicht nötig. iCloud benötigt beim
untersuchten Apple-Silicon-Weg einen geeigneten Host und frisch erzeugten Gast
ab macOS 15. Mindestversionsabnahme 12.7, Intel und ARM bleiben getrennte Ziele.
Der recherchierte xnulinux-Weg scheitert hier bereits an Architektur und
Modulrechten. Der Workflow-Start ist konkret dokumentiert; die lokale GitHub-
CLI hatte keine Anmeldung, daher wird kein Dispatch behauptet.

Der Vorschlag ist nicht nach `main` übernommen; kein neues Paket, keine
Issue-Schließung und keine Veröffentlichung. Codex soll den vollständigen
Prüfzweig samt Abhängigkeiten lesen, die ausgewiesenen nativen Gates ausführen
und erst danach die passenden Quellpatches übernehmen.


## Mac #777: Apple-Erinnerungen als eigenständige lokale Aufgaben – 25. November 2026

**Aktueller vollständiger Arbeitszweig: `work/777-macos-reminder-copy`, Basis
`a706c57132d3646139464d7d432abe3f860514d6` aus #775.** Der Zweig enthält weiter
AirPlay #721, Kalender #770, Apple-Notes-Textkopien #772, die Einstellungs-
Korrekturen #773/#774 und Kontakte #775. Die entfernte Standardbasis wurde als
`00776ce70e155c7a607ed55a4502d6fcee5a860c` bestätigt. Gemäß Nutzerauftrag
werden überprüfbare Quellpatches im Issue und auf dem Arbeitszweig für die
spätere Codex-Übernahme bereitgestellt; kein Merge nach `main`, kein Paket
und keine Veröffentlichung.

Der parameterlose Befehl `macos_erinnerungen_importieren` ist im nativen Menü
und unter den System-Internetkonten angebunden. Der neue direkte
EventKit-Reader nutzt die bestehende serielle Store-Queue und ausdrückliche
Systemfreigabe. Auswahl von Liste/Konto und offenen oder erledigten Einträgen,
vollständige Vorschau, erneuter ausgewählter Quellenabruf und dauerhafte
Speicherquittung sind verbunden. Die älteren allgemeinen Reader/Snapshots
behalten ihre getrennten Verträge und Einschränkungen.

Bis zu 100 Einträge und 16 MiB werden als eigenständige lokale Aufgaben
vorbereitet. Titel, Klartextnotiz, Erledigtstatus, unterstützte Daten und eine
sichtbar erklärte Gruppierung in drei Prioritäten werden übernommen.
Originalwerte und tatsächlich gelesene öffentliche Felder bleiben passiver
Quellenbeleg. Unteraufgabenbeziehungen, Tags, Markierungen, Anhänge,
Zuweisungen, Rich Text und Provider-Sonderfelder werden als nicht verfügbar
gekennzeichnet; ihre Abwesenheit wird nicht erfunden. Serien und Alarme
werden sichtbar ausgeschlossen. Es gibt keine Quelländerung, keinen
Rückabgleich, keine neue Benachrichtigung und keine zusätzliche iPhone-App.

DATE und floating werden direkt als unveränderte Gregorianische
Kalenderwerte abgebildet. Eine fehlende eigene DateComponents-Zeitzone wird
weder durch Kalender-, Objekt- noch Systemzeitzone ersetzt. Die Prüfung
deckte eine zusätzliche Verankerung durch den bisherigen Kalenderdecoder
auf; der neue Civil-Pfad erhält auch floating Uhrzeiten in Sommerzeitlücken
und -überlappungen. Nur ausdrücklich gebundene Zeiten verwenden die
gepinnten Zeitzonendaten; mehrdeutige Zeiten, Subminuten und nicht
bearbeitbare Kombinationen werden sichtbar ausgeschlossen.

Quellidentitäten werden bytegenau verglichen, alle neun Listen-/Kontofelder
und ausgewählten Rohdatensätze einschließlich Ausschlüssen neu geprüft.
Das ist eine Revision gelesener Felder, kein atomarer Serverstand. EventKit
liefert für die Eintragsauswahl bereits vollständige EKReminder-Objekte;
die Metadatengrenze von 10.000 greift nach dem Callback und ist keine
Zusicherung über dessen interne Allokation. Abbruch/20-Sekunden-Frist
beenden die eigene Fortsetzung genau einmal; verspätete Ergebnisse werden
verworfen, ohne sofortigen Abbruch synchroner Systemzugriffe zu behaupten.

Die tatsächliche kanonische UI erzeugt neue lokale IDs und Zeitstempel.
Sie prüft den gesamten Aufgabenbaum auf Klonen und hängt neue Wurzelaufgaben
erst nach bestätigtem Erhalt aller Bestandsaufgaben an. Lokale Änderungen,
bekannte Kopien und Papierkorbeinträge bleiben erhalten. Vorschautoken,
fünfminütige Frist, konkretes Buch samt vollständigem Inhalt, Zeitzone,
Entwürfe, Wiederherstellungspunkt und Save-ACK sind gebunden.

Die unabhängige Prüfung reproduzierte einen Folgefehler nach dem Anhängen:
Eine Ausnahme im öffentlichen Renderer-Hook ließ die neue Kopie im Buch und
einen Speichertimer aktiv, meldete aber nur den Darstellungsfehler. Der
neue Anschluss unterscheidet jetzt bestätigtes Save-NACK von noch nicht
bestätigter Speicherung. Eine echte UI-Regression prüft Erhalt, Save-Retry
und Wiedererkennung ohne Duplikat. Der gleiche Quellpfad älterer
Kalender-/Notes-/Kontaktkopien wird getrennt in **#778** geprüft.

Der von Root ausgeführte gemeinsame Lauf bestand **7/7 Testgruppen** in
29,029 Sekunden, Node 24.22.3 / CI-JSDOM 26.1.0:

| Prüfung | Tatsächlich bestanden |
| --- | --- |
| Erinnerungskopien mit vollständigem gemeinsamem Core-Fixture und echter projizierter UI | 369 Prüfungen |
| Kontaktkopien einschließlich Geburtstag/Editor und 14 Anker-Driftprüfungen | 230 Prüfungen |
| Apple-Notes-Textkopien einschließlich Kontoentwürfen | 179 Prüfungen |
| Systemkalenderkopien einschließlich Settings-Einstieg | 307 Prüfungen |
| Allgemeiner tatsächlicher UI-Host-Vertrag | 109 Assertions |
| Bridgeinventar | Bestanden |
| Freeze-/Manipulationserkennung | Bestanden |

Danach wurde ausschließlich der deutsche native Berechtigungsfehlertext
ergänzt. Der abschließende getrennte Erinnerungs-Runner bestand auf diesen
finalen Eingaben erneut **369 Prüfungen mit unveränderter Eingabeinventur**.
Vier deutsche UI-/Vorschauprüfungen sind enthalten. Native Nutzlasten und
Transportantworten sind synthetisch. 31 neue Swift-Core-/Bridge-Testmethoden
sind vorbereitet, **hier weder kompiliert noch ausgeführt**. Tatsächlich
geprüft sind außerdem JSON-/Plist-Format, Übereinstimmung der 20 Rohfelder,
unabhängiger Identitätshash, vollständige ergänzte deutsche Meldungen und
sauberes Diff-Whitespace. Die finale Produktinventur enthält **432 Dateien**,
SHA-256 der sortierten Inventur
`39622893d7205e8485d8f47cdea8ebdefe378cb566c75a223a071a8ed2a75754`.
Kein SourceFreeze und kein dauerhaft erzeugter Bundle-Stand.

Native Swift-/EventKit-/AppKit-/TCC-/Konten- und Geräteabnahme bleibt gemäß
[SYSTEM-REMINDER-IMPORT.md](Magnolie-Organizer-macOS-Beta/SYSTEM-REMINDER-IMPORT.md)
offen. Der gemeinsame Aufgaben-Normalizer anderer Editionen übernimmt die
neuen Herkunftsfelder nicht wie der Mac-Erhaltungsvertrag. Diese konkrete
Quellenabweichung und die gesonderte Linux-/Windows-JSON-Austauschprüfung
stehen in **#779**; kein dortiger nativer Datenverlust wird behauptet.
**#776** bleibt der separate Kontaktgeburtstagsfall. Nächster Schritt ist
die Codex-Übernahme und native Abnahme des gesicherten Gesamtzweigs sowie
die getrennte Bearbeitung der benannten Folgeprüfungen.

## Mac #775: ausgewählte Systemkontakte als lokale Kopien – 25. November 2026

**Aktueller vollständiger Arbeitszweig: `work/775-macos-contact-copy`, Basis
`f32f4daa71acea7f76fb9f58ff0f8d4794f728ab` aus #774.** Er enthält weiterhin
AirPlay #721, Kalender #770, direkte Apple-Notes-Textkopien #772 und die
Einstellungs-Guards #773/#774. Die entfernte Standardbasis wurde als
`00776ce70e155c7a607ed55a4502d6fcee5a860c` bestätigt. Gemäß Nutzerauftrag wird
der prüfbare Quellpatch im Issue und auf dem Arbeitszweig für die spätere
Codex-Übernahme bereitgestellt; kein Merge nach `main` und kein Paket/Release.

Der neue parameterlose Befehl `macos_kontakte_importieren` öffnet die native
Adressbuch-/Kontaktauswahl. Der direkte Contacts-Reader nutzt die vorhandene
serielle Store-Queue und ausdrückliche Systemfreigabe. Zunächst liest er
Kennungen/Namen, danach nur die ausgewählten nicht vereinheitlichten Kontakte.
Containerzugehörigkeit, Quellmetadaten und Berechtigung werden vor/nach dem
Detailabruf und nach der Vorschau erneut geprüft. Kein Note-Key, kein breiter
vCard-Descriptor, keine private Datenbank und keine Quellschreiboperation.

Bis zu 100 Kontakte und 16 MiB werden als bewusste lokale Kopien vorbereitet.
Standardfelder, Mehrfachwerte, Labels, Originalfotos und unterstützte Geburtstage
laufen durch die tatsächliche kanonische Normalisierung. Nur ausdrücklich
angezeigte E-Mail-Kleinschreibung ist zugelassen; andere verlustbehaftete Fälle
werden sichtbar ausgeschlossen. Zusätzliche gelesene öffentliche Felder bleiben
als gekennzeichnete Ursprungsdaten erhalten, ohne vollständige Provider-Sicherung
zu behaupten. Das entitlementgeschützte Kontakt-Notizfeld wird nicht angefordert.

Native Herkunft und unabhängige lokale IDs bleiben getrennt. Gleiche Namen,
E-Mail-Adressen oder Telefonnummern führen zu keiner Zusammenführung. Bekannte,
veränderte und im Papierkorb liegende Kopien werden nicht überschrieben oder
neu angelegt. Der Vorschlag bindet das tatsächliche Buch und dessen Inhalt,
läuft nach fünf Minuten ab, prüft Entwürfe/Restore erneut und verwendet
Wiederherstellungspunkt plus dauerhafte Speicherquittung. Fehler nach dem
Anhängen lassen die Kopien ausdrücklich ungespeichert sichtbar.

Für `birthdayPolicy: "contact-only"` bleibt das Datum direkt am Kontakt; 14 enge
Mac-Projektionsanker verhindern automatische Jahrestage/namensgleiche Zuordnung
und bewahren die Semantik im Editor, beim Laden, im Druck-/ODS-Fallback und bei
MCP-`birth_date`. Jahrfreier 29.02. und ein ausdrücklich vorhandenes Jahr 1604
bleiben erhalten. Die unabhängige Durchsicht fand eine Lücke bei ungültigen
Texteingaben im neuen Geburtstagsfeld; sie wurde innerhalb dieses neuen
Anschlusses korrigiert. `31.02.2000` und `12.` behalten nun den gesamten Kontakt,
die Eingabe und den Editorfokus; bewusstes Leeren bleibt möglich. Gewöhnliche
Kontakte und ausdrücklich angeforderte Jahrestagsmutationen bleiben unverändert.

Der abschließende von Root ausgeführte gemeinsame Lauf bestand **6/6
Testgruppen** in 20,627 Sekunden, Node 24.22.3 / CI-JSDOM 26.1.0:

| Prüfung | Tatsächlich bestanden |
| --- | --- |
| Kontaktkopien mit gemeinsamem vollständigem Core-Fixture, echtem Editor, Settings, MCP und ODS | 230 Prüfungen sowie Driftprüfung der 14 Geburtstagsanker |
| Apple-Notes-Textkopien einschließlich Kontoentwürfen | 179 Prüfungen |
| Systemkalenderkopien einschließlich Settings-Einstieg | 307 Prüfungen |
| Allgemeiner tatsächlicher UI-Host-Vertrag | 109 Assertions |
| Bridgeinventar mit neuer expliziter Fähigkeit | Bestanden |
| Freeze-/Manipulationserkennung | Bestanden |

Native Nutzlasten und Transportantworten sind synthetisch. Der getrennte
Kontakt-Runner bestand ebenfalls 230 Prüfungen mit unveränderter
Eingabeinventur. 25 neue Swift-Core-/Bridge-Testmethoden sind vorbereitet,
**hier weder kompiliert noch ausgeführt**. Zusätzlich tatsächlich geprüft:
JSON-/Plist-Format, Fixture-Identität, PNG-Struktur/CRC/Scanlines und sauberes
Diff-Whitespace. Finale Produktinventur: **428 Eingangsdateien**, SHA-256 der
sortierten Inventur `791b8f37633ef06cb44171bc6c42f758777f36e4a0c10eb4c0b73c652bb33968`;
kein SourceFreeze und kein dauerhaft erzeugter Bundle-Stand.

Native Swift-/Contacts-/ImageIO-/AppKit-/Konten- und Geräteabnahme bleibt gemäß
[SYSTEM-CONTACT-IMPORT.md](Magnolie-Organizer-macOS-Beta/SYSTEM-CONTACT-IMPORT.md)
offen. Vollständige Sprachkatalog-/Paketprüfung wird nicht aus den ergänzten
und tatsächlich geprüften deutschen Mac-UI-Texten abgeleitet. Der gemeinsame
Normalizer anderer Editionen kennt die neue Geburtstagsregel noch nicht;
die konkrete Quellenabweichung und gesonderte Linux-/Windows-Austauschprüfung
stehen in **#776**. Kein dortiger nativer Datenverlust oder Alarm behauptet.
Nächster Schritt ist die Codex-Übernahme und native Abnahme des gesicherten
Gesamtzweigs; Erinnerungen behalten ihren getrennten offenen Abbildungsumfang.

## Mac #774: Kontoentwürfe beim Notes-Import erhalten – 25. November 2026

**Aktueller vollständiger Arbeitszweig: `work/774-notes-account-draft`, Basis
`fbb50c2c9146091a778fdb45608b315a67d64899` aus #773.** Dieser Zweig enthält
die direkte Apple-Notes-Textkopie #772 sowie die getrennten Korrekturen #773 und
#774, aufbauend auf Kalender #770 und AirPlay #721. Die Patches bleiben für die
spätere Codex-Übernahme bereitgestellt; `main` und Pakete sind unverändert.

Die mit erfundenen Testdaten tatsächlich reproduzierte Lücke im neuen Notes-
Start ist geschlossen: Separate Server-/Benutzerentwürfe und eine alleinige
Kennworteingabe in sichtbaren Einstellungen blockieren den Import vor der
Navigation und erneut nach dem Save-ACK. Dialog, Werte und Buchdaten bleiben
erhalten; weder native Notes-Auswahl noch DAV-Speicherung werden gestartet.
Verborgene alte Felder nach bewusstem Schließen blockieren spätere Menüstarts
nicht. Die vorherige Reproduktion betraf nur ungespeicherte Formulareingaben,
keine bereits gespeicherten Zugangsdaten oder tatsächlichen Nutzerkonten.

Der gezielte Notes-Runner bestand mit **179 Prüfungen** und stabiler
Eingangsdatei-Inventur. Der anschließend von Root gemeinsam ausgeführte Lauf
gegen den vollständigen aktuellen Stand bestand **3/3 Testgruppen**:

| Abschließende Prüfung | Ergebnis |
| --- | --- |
| Apple-Notes-Textkopien, tatsächlicher Settings-Knopf und Kontoentwürfe | 179 Prüfungen bestanden |
| Systemkalenderkopien einschließlich Settings-Einstieg und Kontoentwürfen | 307 Prüfungen bestanden |
| Allgemeiner tatsächlicher UI-Host-Vertrag | 109 Assertions bestanden |

Node 24.22.3 / CI-JSDOM 26.1.0; native Quellnutzlasten und Transportantworten sind
synthetisch. Der zuvor abgeschlossene #772-Lauf bestand zusätzlich die
Notizdateiübernahme (23 Prüfungen), das Bridgeinventar und die Freeze-/
Manipulationserkennung. Die neue Korrektur verändert nur den Notes-Startpfad,
seine Regressionstests und Dokumentation. Finales Quellaudit: 424 Eingangsdateien,
kein Freeze oder dauerhaft erzeugter Bundle-Stand; Diff-Whitespace sauber.

18 neue Swift-Core-/Bridge-Tests aus #772 bleiben mangels Swift/Mac unkompiliert
und unausgeführt. Native Notes-Dictionary, Automation-Berechtigung, stabile
Objektreferenzen und die echten Mac-/iPhone-Daten müssen nach
`APPLE-NOTES-IMPORT.md` geprüft werden. Vollständige Sprachkatalog-/Native-Bau-
und Geräteabnahme werden durch diese Projektionsprüfungen nicht behauptet.
Nächster Schritt ist die native Übernahme-/Abnahme dieses gesamten Zweigs;
Kontakte und Erinnerungen behalten ihre getrennten offenen Abbildungsaufgaben.

## Mac #773: Kalenderimport aus den Einstellungen – 25. November 2026

**Quellpatch auf `work/773-calendar-settings-entry`, Basis
`6ffe768f382fbbca3e8f531c93f9ee197eba59a7` aus #772.** Der reproduzierte Fehler
im bestehenden Kalender-Startpfad #770 ist korrigiert: Nach Navigations-Guard
und dauerhafter Speicherquittung schließt ausschließlich der eigene
Einstellungsdialog über dessen kanonischen Pfad. Zusätzliche Modale, abgebrochene
Editorentwürfe und fehlgeschlagene Speicherung verhindern weiterhin den Start.
Der native Befehl bleibt parameterlos; die Vorschaugrenzen bleiben unverändert.

Separate DAV-/Nextcloud-Entwürfe liegen nicht im gewöhnlichen Buch-Save oder im
aktiven Organizer-Editor. Deshalb prüft der Start sichtbare Einstellungen vor
Navigation/Speicherung und erneut nach dem Save-ACK auf geänderte Kontofelder
oder eine nichtleere Kennworteingabe. Die Felder bleiben erhalten; es gibt weder
automatisches Speichern noch Verwerfen. Versteckte alte Kennwortfelder nach
einem bewussten Schließen blockieren spätere Menüstarts nicht.

Der vorhandene gezielte Kalenderprüfer bestand mit **307 Assertions**, Node
24.22.3 / CI-JSDOM 26.1.0 und stabiler Eingangsdatei-Inventur. Er führt den echten
Settings-Knopf mit korrelierter Quellenantwort und vollständigem synthetischem
Kalender-DTO bis zur Vorschau, zum Recovery-Checkpoint und zur dauerhaften
Speicherquittung aus. Zusätzliche Modale, tatsächliche Editorentwürfe,
Speicherfehler sowie URL- und alleinige Kennworteingaben vor/während des
Start-Speicherns sind geprüft. Diff-Whitespace sauber.

Keine Swift-/EventKit-/native Mac-Prüfung aus diesem JS-Nachweis abgeleitet;
keine gemeinsame Linux-/Windows-Quelldatei geändert. Kein Merge oder Paket.
Bei derselben Prüfung ist die gesonderte Kontoentwurfslücke im neuen
Notes-Start #772 konkret reproduziert worden; sie wird anschließend als
eigenständiger Patch zu #774 behoben. Die Reproduktion verwendet ausschließlich
erfundene Werte und zeigt Verlust ungespeicherter Eingaben, keine Veränderung
gespeicherter Zugangsdaten.

## Mac #772: direkte Apple-Notizen als lokale Textkopien – 25. November 2026

**Quellpatch auf `work/772-apple-notes-copy`, Basis Kalenderpatch
`2b3a7cea5093b80de1dd14bdf5afaf84231d66ad` aus #770.** Die abgerufene
Standardbasis ist `00776ce70e155c7a607ed55a4502d6fcee5a860c`. Weiterhin gilt der
Nutzerauftrag, konkrete Patches im Issue zur späteren Codex-Prüfung und Übernahme
bereitzustellen. Kein Merge nach `main`, kein installierbares Paket und kein Release.

Der neue parameterlose Befehl `macos_apple_notizen_importieren` startet die
ausdrückliche Konto-/Ordner-/Notizauswahl. Der eingebaute Reader verwendet feste
NSAppleScript-Handler, typisierte Apple-Event-Argumente und Antworten sowie eine
prozessweit serielle Hintergrundqueue. Die reguläre Automation-Zweckbeschreibung
ist ergänzt. Keine zusätzliche Anwendung, kein `osascript`, keine private
Notes-Datenbank und keine Apple-Notes-Schreib- oder Löschbefehle. Notizen vom
iPhone müssen im gewählten vorhandenen Mac-Notizkonto verfügbar sein.

Bis zu 32 ausgewählte Notizen werden als bewusste Textkopien vorbereitet;
Schutzstatus, Anhänge, Titel, Plaintext, HTML-Repräsentation, Änderungsinformation
und tatsächliche Konto-/Ordner-/Notizkennungen werden geprüft. Geschützte und
anhangshaltige Notizen liefern keine Bodies und erscheinen als Ausschlüsse.
Je Text-/HTML-Feld gelten 1 MiB; Nachweis und finale Nutzlast sind unabhängig auf
8 MiB begrenzt. Dies sind Antwort-/Verarbeitungsgrenzen, keine zugesicherte
Vorab-Allokationsgrenze innerhalb der Apple-App.

Die Vorschau zeigt die vollständigen Texte und das tatsächliche Zielnotizbuch.
Die Kopieridentität bindet bytegenau Konto und Notiz, der Ordner gehört zur
Revision. Wiederimport, geänderte Quelle und Ordnerwechsel überschreiben keine
lokale Bearbeitung; Papierkorbeinträge werden nicht neu angelegt. Nach Freigabe
wird dieselbe Auswahl erneut gelesen. Der private UI-Vorschlag bindet Buch,
Zielnotizbuch, Entwürfe einschließlich ausstehender Notizeditor-Snapshots und eine
begrenzte Gültigkeit. Nur neue kanonische Notizen werden normalisiert. Erfolg
folgt erst nach Recovery-Checkpoint und dauerhafter Speicherquittung.

Quell-HTML bleibt inaktive Herkunft und wird nicht gerendert. Leere Inhalte,
LF, Tabs, Emoji und kombinierende Zeichen bleiben in der geprüften Projektion
erhalten; CR/CRLF und sonst durch den vorhandenen Editor veränderte Texte werden
sichtbar ausgeschlossen. Formatierung, Checklisten, Tabellen, Zeichnungen und
andere Notes-Funktionen werden nicht als entsprechende Funktionen konvertiert.
Die Textkopie ist kein vollständiges Notes-Archiv oder laufender Abgleich.

| Tatsächlich geprüfter Umfang | Ergebnis |
| --- | --- |
| Neue Notes-Übernahme mit tatsächlicher kanonischer UI und synthetischen nativen Daten/Antworten | 155 Prüfungen bestanden; Node 24.22.3, CI-JSDOM 26.1.0 |
| Bestehende Notizdateiübernahme | 23 Prüfungen bestanden |
| Bestehende Kalenderübernahme | 258 Prüfungen bestanden |
| Allgemeiner UI-Host | 109 Assertions bestanden |
| Gemeinsamer abschließender Python-Lauf | 6/6 Tests bestanden, einschließlich Bridgeinventar und Freeze-/Manipulationserkennung |
| Quellaudit, JSON/Plist, Python-Syntax und Diff-Whitespace | 424 Eingangsdateien; neuer Befehl und Automation-Zweckbeschreibung vorhanden; kein Freeze oder dauerhaft erzeugter Bundle-Stand |
| Neue Swift-Kern-/Bridgeverträge | 18 XCTest-Methoden vorbereitet, nicht ausgeführt; `swift`/`swiftc` hier nicht vorhanden |
| Native Swift-/AppKit-/Notes-Dictionary-/Automation-Ausführung und echte Mac-/iPhone-Konten | Nicht durchgeführt |

Native Restmatrix und Quellen: `Magnolie-Organizer-macOS-Beta/APPLE-NOTES-IMPORT.md`.
Die genaue Dictionary und Rückgabetypen, stabile zurückgelieferte Objektreferenzen,
Zugriff/Entzug, gesperrte/komplexe Notizen, Laufzeit und Abbruch sowie dauerhafte
Wiederöffnung müssen auf macOS 12.7 und einem aktuellen unterstützten macOS für
Intel/Apple Silicon geprüft werden. Ein Apple-Event-Timeout oder Task-Abbruch
behauptet keine harte Beendigung der Zielanwendung. Native Ergebnisse nach
Abbruch/Dokumentwechsel werden verworfen; blockierte Aufrufe erzeugen keine Queue
weiterer Importe. Die vollständige Sprachkatalogprüfung bleibt mangels `msgfmt`
offen. JavaScript-Prüfungen sind keine native Freigabe.

Separater bestätigter Befund #773: Der ältere Kalender-Importknopf in den
Einstellungen lässt den Einstellungsmodal offen und blockiert damit die spätere
Vorschau. Reproduziert über den echten projizierten Knopf mit synthetischem
Transport. Der neue Notes-Einstieg schließt ausschließlich diesen eigenen
Einstellungsdialog nach dem bestehenden Speicher-Guard; andere Modale bleiben
geschützt. Die entsprechende Kalenderkorrektur wird getrennt bearbeitet.
Keine gemeinsame Linux-/Windows-Quelldatei geändert oder dortige Behebung behauptet.

## Mac #770: Systemkalender als lokale Termin-Kopien – 25. November 2026

**Quellpatch auf `work/770-macos-calendar-import`, aufbauend auf dem gesicherten
AirPlay-Commit `25c5a849a89d8846b211ff98922a708dcc7e127d` aus #721.** Die erneut
abgerufene Standardbasis bleibt `00776ce70e155c7a607ed55a4502d6fcee5a860c`.
Nutzerauftrag: ohne eigene iPhone-App weiterentwickeln; Patches im Issue zur
späteren Codex-Übernahme bereitstellen. Kein Merge nach `main`, kein Paketbau
oder Release aus diesem Schritt.

Der neue parameterlose Mac-Befehl `macos_kalender_importieren` öffnet einen
nativen EventKit-Kalender-/Datumsdialog. Nach ausdrücklich angeforderter
Systemfreigabe werden höchstens 366 Tage, 10.000 Datensätze und 16 MiB gelesen
und geprüft. Einfache Einzeltermine werden über den bestehenden kanonischen
ICS-Codec vorbereitet. Präzise UTC-Zeiten einschließlich Sekunden und Folds
sowie DATE-/Ganztagsgrenzen bleiben erhalten. Serien, Alarme, Teilnehmer,
Geburtstagsquellen und sonst nicht unverändert abbildbare Termine erscheinen
mit Gründen als Ausschlüsse.

Die Vorschau unterscheidet neue, bereits übernommene, an der Quelle geänderte
und ausgeschlossene Termine. Herkunft bindet tatsächlichen Kalender,
Ereigniskennung und Elternkonto; gleiche Titel sind keine Dublettenidentität.
Vorhandene Kopien und lokale Bearbeitungen werden nicht überschrieben,
Papierkorbeinträge nicht neu angelegt. Nach Bestätigung wird die Quelle erneut
gelesen. Der private UI-Vorschlag prüft Buchinhalt, Generation/Zeitzone,
Sperre/Restore und auch zwischenzeitlich geöffnete Editorentwürfe vor und nach
dem bestehenden Recovery-Checkpoint. Erfolg erst nach dauerhafter Speicherquittung;
gescheiterte Abschlussspeicherung bleibt ausdrücklich ungespeichert sichtbar.

Gezielte Mac-Projektion in Normalisierung, Termin-Editor und Erinnerungsprüfung
verhindert erfundene Standardalarme bei den neuen Kopien. Bewusst im Editor
gesetzte Standardalarme oder einzelne lokale VALARMs bleiben nutzbar. Der
native bestätigte/vorläufige Status folgt dem vorhandenen editierbaren
`vorlaeufig`-Vertrag; sein ursprünglicher EventKit-Wert bleibt in der Herkunft.
Keine widersprüchliche zusätzliche rohe STATUS-Zeile.

| Tatsächlich geprüfter Umfang | Ergebnis |
| --- | --- |
| Neue Übernahme mit echter projizierter UI, vollständigen synthetischen DTOs, echtem Editor/Kalender/Erinnerungsplan und synthetischem nativen Speichertransport | 258 Assertions bestanden; Node 24.22.3, CI-JSDOM 26.1.0 |
| Bestehender allgemeiner UI-Host-Vertrag | 109 Assertions bestanden; gleiche CI-JSDOM-Version |
| Zusammengehöriger abschließender Python-Lauf | 5/5 Tests bestanden: neuer Import, vorhandener UI-Host, Bridgeinventar, Alarmadapter-/Ankerabweichung, Freeze-/Manipulationserkennung |
| Eingangsdateien im gezielten Importprüfer | Unverändert im abschließenden Lauf; zwischenzeitliche Änderungen werden ausdrücklich zurückgewiesen |
| Statisches Quellaudit | 420 Eingangsdateien; neuer Befehl inventarisiert; kein Freeze und kein dauerhaft erzeugter Bundle-Stand |
| Swift-Kern/SDK-Verträge | 16 XCTest-Fälle angelegt; nicht ausgeführt, `swift`/`swiftc` hier nicht vorhanden |
| Python-Syntax, JSON-Ressource und Diff-Whitespace | Geprüft |
| Native AppKit-/EventKit-/WKWebView-Ausführung, echte Mac-/iPhone-Konten und Geräte | Nicht durchgeführt |

Ein erster zusätzlicher allgemeiner UI-Lauf mit JSDOM 31.0.1 vermisste den
Capability-Block. Der unveränderte Test bestand anschließend sowohl gegen den
Vorgängerstand als auch gegen den aktuellen Stand mit 31.0.1 und mit der
CI-Vorgabe 26.1.0. Kein reproduzierter Produktfehler oder belegter genereller
JSDOM-31-Fehler; keine Testbedingung abgeschwächt. Die vollständige frühere
Sprachkatalogprüfung bleibt mangels `msgfmt`/erzeugter Kataloge unbestätigt und
wird nicht aus den gezielten englischen UI-Prüfungen abgeleitet.

Details, Bedienung, Grenzen, wiederholbarer Prüfbefehl und native Restmatrix:
`Magnolie-Organizer-macOS-Beta/SYSTEM-CALENDAR-IMPORT.md`.
`systemAccountSyncImplemented` bleibt false. Keine automatische Aktualisierung,
Rückschreibung oder Löschung in Apple-Konten. JSON-Sicherungen erhalten die
Herkunftserweiterungen; der strenge ICS-Export solcher Kopien bleibt bis zu einer
vollständigen Herkunftsabbildung gesperrt. Erinnerungen, Kontakte und Apple
Notes sind weiterhin eigene offene Anschlussaufgaben ohne neue iPhone-App.

Separater statischer Befund #771: Der ältere allgemeine EventKit-Leseguard
erlaubt 1464 Tage, während Apple Fenster über vier Jahre verkürzt. Die neue
Übernahme bleibt bereits vor dem nativen Read unter dieser Grenze (366 Tage).
Keine native Reproduktion oder Datenverlustbehauptung; kein nachgewiesener
Linux-/Windows-Fehler. Gemeinsame kanonische Produktdateien wurden hier nicht
verändert. Als Nächstes native Kompilierung und tatsächliche Kalender-/Rechte-/
Abbruch-/Speicher-/Wiederöffnungsfälle auf beiden Mac-Architekturen abnehmen;
danach den getrennten Aufgaben-/Kontakt-/Notizenanschluss fortsetzen.

## Mac #721: eingebauter iPhone-AirPlay-Empfänger – 25. November 2026

**Prüfbarer Quellpatch auf `work/721-macos-airplay`, Basis
`00776ce70e155c7a607ed55a4502d6fcee5a860c`; Übernahme und native Abnahme offen.**
Der Nutzer möchte Patches im Issue zur späteren Prüfung/Übernahme mit Codex.
Dieser Anschluss wird deshalb als benannter Arbeitszweig bereitgestellt.

UxPlay 1.73.7 ist mit Versions-/Quellenhashes und erhaltenen Lizenzen direkt
unter `Magnolie-Organizer-macOS-Beta/Receiver` enthalten. Der native Mac-Host
bietet Start/Stop/PIN, verarbeitet ausschließlich feste lokale Statusereignisse
und besitzt seinen eigenen Empfängerprozess. Das iPhone benötigt nur seine
vorhandene Bildschirmsynchronisierung. Der zusätzliche Bundlebau nimmt ein
ausdrücklich vorbereitetes SDK, baut den Helfer und liefert GStreamer/OpenSSL 3/
libplist samt Bibliothekskette, Quellen und Lizenzhinweisen innerhalb der App.
Eine Installation zusätzlicher Empfängerprogramme beim Anwender entfällt in
einem erfolgreich so gebauten Paket. Noch kein solches natives Paket erstellt.

| Prüfung dieses Patches | Ergebnis |
| --- | --- |
| Echter portabler C++-IPC-/Registrierungscode, `-Wall -Wextra -Werror` | 11 Tests bestanden |
| Synthetische Paket-/Bibliotheks-/Relocation-/Quellenfälle | 25 Tests bestanden |
| Versionierter Upstream-Abgleich | 76 vendorte Dateien geprüft; lokaler Delta-Patch gegen sauberen v1.73.7-Stand anwendbar |
| Bestehende Host-Prüfungen für Identität, Freeze-/Manipulationserkennung und Ablehnung falscher Linux-Bauzusage | 3 Tests bestanden |
| Bestehender vollständiger UI-Projektionstest | Fehlgeschlagen an fehlender Bauvoraussetzung: 0 statt 19 erzeugte Sprachkataloge; `msgfmt` in dieser Umgebung nicht vorhanden |
| Neuer portabler Swift-Vertrag, Decoder, Bundlepfade und private Ablage | 27 XCTest-Fälle vorbereitet; nicht ausgeführt, keine vorhandene Swift-Toolchain |
| Native Swift/AppKit-/GStreamer-Kompilierung, Codesign, echter Mac/iPhone-Lauf | Nicht ausgeführt |

Die Katalogvorbereitung bleibt der bestehende `po_zu_js.py`-/`msgfmt`-Weg.
Es wurden weder Tests abgeschwächt noch Ersatzkataloge erzeugt, um die fehlende
Voraussetzung zu verdecken. Die oben genannten gezielten AirPlay-Prüfungen
belegen keinen vollständigen Mac-Build. Der UI-Audit liest die neuen Quellen;
Produkt- und Gerätefreigabe bleiben getrennt.

Der ergänzende Nutzerauftrag zu Notizen, Terminen und weiteren iPhone-Funktionen
ist in `IPHONE-INTEROPERABILITY.md` gegen Apple-Primärquellen und vorhandenen
Magnolie-Code geprüft: Kalender/Erinnerungen über EventKit, Kontakte über
Contacts und gemeinsame Konten, Notizen über bestehenden Dateiimport oder einen
noch zu entwickelnden AppleScript-Connector am Mac. Eine eigene iPhone-App ist
dafür keine Voraussetzung. AirPlay liefert keinen Datensatzabgleich; der
bestehende Status `systemAccountSyncImplemented: false` bleibt zutreffend.

Nächster Schritt: Patch mit Codex übernehmen, die vorhandene Katalogvorbereitung
ausführen und native Swift-/Bundle-/iPhone-Abnahme für Intel und Apple Silicon
nach `AIRPLAY.md` durchführen. Keine Release-Veröffentlichung erfolgt.

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
| #245, Linux – privates Testpaket auf installierter Basis | `work/245-user-deb` | Paketquelle `47c84874c069c4700a42d79bc38795005e14320d`; Diagnose-Folgequelle `e61697c37cc3f16261a31a93a59adf3915667fc0` |
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
dem Start abgelehnt. Das regulär signierte private Paket hat beide
Upgrade-Fälle im isolierten Android-Gast bestanden: AN verbindet
vor dem Öffnen, AUS bleibt aus; Paarung und Rechte sind erhalten.

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

## Eigenständiger Android-Tablet-Organizer – 26. November 2026

Nutzerauftrag: alle Tablet-Issues gegen den tatsächlichen Quell-/Prüfstand
abgleichen, die aktuelle gemeinsame Oberfläche tabletgerecht verwenden und
Kontakte/Kalender direkt über Android anbinden. Magnolie Notes und KDE Connect
sind keine Voraussetzung; lokale Organizer-Notizen bleiben Bestandteil der App.
Die präzisierte Plattformabgrenzung steht auch in `AGENTS.md` und der Tablet-README.

**Einstieg für die spätere Übernahme:**
[Übergabe, Aktualisierung und vollständige Prüfreihenfolge](pruefnachweise/android-tablet-followup-2026-11-26/handover/README.md).
Festgehaltene Dokumentations-/Nachweisbasis ist `8d5dc47fecf77b7ebc2db0e5cbb7cb4754005b29`;
der tatsächlich in CI #101 gebaute und mit Android-Providern geprüfte Head bleibt
`7a7d90b04796cf338b98f0fdbb87e8da1c967043`. Die Übergabe ergänzt diese Basis als
Folgepatch 13. Der [vollständige Patchindex](https://github.com/maik3531/Magnolie-Organizer/issues/121#issuecomment-7188858114)
bindet die ersten fünf Patches, alle Folgepatches und den jeweils aktuellen
Remote-Head. Die Anleitung enthält das Vorgehen bei späteren Änderungen in
`main`, die vorhandenen Workflowtargets und die offenen nativen Freigabepunkte.
Die frische Integritätsprüfung bestätigt die bisherigen 232 Belegdateien,
462 CI-Inputs und 83 bytegleichen Laufzeitoutputs; sie ist kein neuer Funktionstest.

Arbeitsbasis ist `d4da48a5eadd0bda22422b924bef4ee3b4324040`; Änderungen werden im
Prüfzweig `work/android-tablet-20261126` mit vollständigen Issue-Patches zur
späteren Prüfung/Übernahme bereitgestellt. Keine Freigabe eines neuen APK-Pakets
oder Release erfolgt aus diesem Quellnachweis. Der vollständige Audit mit
26 maßgeblichen Issues steht in `contracts/android-tablet-audit-2026-11-26.md`.
Die Fortsetzung baut auf PR-Head `29acde7e3df2b8bcaaab0cc19b3377b8dbf4bd14`
auf und ergänzt denselben Draft-PR #795. Der Folgeaudit in
`contracts/android-tablet-followup-2026-11-26.md` erfasst vier weitere
reproduzierte Fehler (#798–#801). Zwei tatsächliche CI-Prüfcodebefunde
(#804/#805) und der spätere native Serienfixture-Befund #807 ergänzen die
Zuordnung auf 33 Issues. CI #101 belegt inzwischen den vollständigen APK-Gate
und die begrenzte API34-Providerstufe auf dem oben genannten Testhead. Die
vollständige native Bedien-/Geräteabnahme und Produktionsfreigabe bleiben offen.

- #790: Der Tablet-CI-Bau verwendet den aktuellen gemeinsamen Checkout. Das alte
  `v2.0.30` bleibt nur unabhängige Codec-Referenz. Git-/Datei-/Projektions- und
  geprüfte APK-Hashes werden gebunden; JDK21/Gradle9.6/AGP9.5.1 mit integriertem
  Kotlin2.4.21 und compileSdk37.2 sind angeglichen. TargetSDK35 und minSDK26 bleiben.
  Das neue manuelle Workflowziel `tablet-build-only` nutzt denselben vollständigen
  APK-Gate mit allen Ressourcen-/Koordinationsgrenzen. Es überspringt ausschließlich
  Runtimeimage, KVM, Emulator und native Prüfschritte. Job, Artefaktname und
  Metadaten kennzeichnen den reinen Bau; es entsteht keine native Abnahme.
- #791: explizite native Kontakt- und Kalenderkopien mit Quellenwahl,
  Berechtigungsprüfung, Abbruch/Fristen und Session-/Revisionsbindung. Nur neue
  Identitäten ergänzen; vorhandene Datensätze bleiben erhalten. Die gemeinsame
  Normalisierung schützt Kontaktgeburtstage und wiederholtes Öffnen. Termine
  werden für 1–366 Kalendertage als Instanzen übernommen; keine laufende
  Synchronisierung oder Provider-Schreibrechte. Erfolg erst nach Save-ACK.
  #799/#800 ergänzen Schema 2 für Kopierantwort und Herkunft: Kontakte verwenden
  Provider-Source-/Backup-ID beziehungsweise einen gerätegebundenen Raw-ID-Fallback
  mit zusätzlicher Zeilenbindung. Einzelterminidentität hängt nicht von bearbeiteten
  Zeiten ab; Serieninstanzen behalten ihren ursprünglichen Slot einschließlich
  verschobener Ausnahmen. Alte experimentelle Herkunft oder Identitätskonflikte
  werden abgelehnt, nicht geraten oder pauschal bereinigt. Keine allgemeine
  Identitätsgarantie über Provider-Resets und Gerätewechsel hinweg.
- #792: Buchaufteilung nach Fensterbreite, mindestens 48 CSS-Pixel große
  Aktionsziele, kompakte Register und erreichbare, begrenzte Dialoge. Bestehende
  Darstellung sowie Scroll-, RTL- und reduzierte Bewegungsoptionen bleiben.
  #798 erhält den Fokus bei asynchronem Neuaufbau des Quellenbereichs nur, wenn er
  zuvor darin lag. Abbruch, Abschluss und Freigabe besitzen erreichbare Folgeziele;
  andere Controls/Editoren werden nicht zurückfokussiert. Importtexte sind für
  dieselben 20 Sprachkataloge vorhanden; sprachliche Gesamtabnahme nicht behauptet.
- #682: gespeicherte HTTPS-Kalenderanhänge werden nach dem bestehenden
  Speicherschutz direkt an Android übergeben; kein Notes-/KDE-Umweg. Die native
  Richtlinie prüft den tatsächlichen gespeicherten Anhang und dessen Freigabe.
- #463: fehlender/fehlgeschlagener Accessibility-Nachweis wird von positiv
  erkanntem fremdem Paket/Fenster und eigenem nicht bereitem Appzustand getrennt.
  Fokus vorhanden, beide Fensterkennungen `-1` und leeres aktives Paket bedeutet
  jetzt `input-ownership-unverified`. Besitzbedingung, Flags und 420-ms-Geste sind
  unverändert. Keine Ursachenlösung für `-1`, kein Retry/Prewarm und keine
  Zulassung einer unbelegten Geste.

Erste Patchserie, jeweils an ihrem dokumentierten Stand geprüft: 194 bestehende
Tablet-Webchecks; 31 zusätzliche tatsächliche
Frontend-Integrationsfälle mit synthetischer Native-Bridge; 31 JVM-Tests der
Import-/Quellen-/Anhangsrichtlinien; alle 38 Kotlin-Produktdateien gegen echte
Android-37.2-/AndroidX-Abhängigkeiten einschließlich aapt2-Ressourcenübersetzung;
19 Provenienztests plus ein gezielter JAVA_HOME-Weitergabetest; 150/150 echte
Chromium-Layoutchecks in zehn Fenster-/Schrift-/RTL-Fällen. Derselbe Layoutrunner
fand mit dem alten CSS 40 Fehler. Der korrigierte Legacy-CSS-Test prüft die
tatsächlich geltenden vh-/dvh-Fallbacks; Mac-Prüfungen bleiben erhalten.

Gezielte Folgeprüfungen: **22 Provenienz-/Workflowvertragstests** einschließlich
Build-only-Auswahl und unveränderten bisherigen Zielen; **9 JVM-Tests mit 432
Zustandskombinationen** für die unveränderte Besitzentscheidung und neue
Ownership-Diagnose. Der zugehörige Android-Adapter ist gegen echte API 37.2
kompiliert, ohne native Laufzeitprüfung. Zusätzlich sind **46 JVM-Tests** der
Import-/Quellen-/Anhangsregeln und **167 echte Chromium-Prüfungen** des
Importformulars mit synthetischer Native-Bridge, Fokus-/Touchabläufen und
Katalogvollständigkeit belegt. #801 ergänzt die persistente Statusregion im
Dialog; der echte Identitätskonflikt erhält Live-/Speicherbuch und seine Meldung
ist nach Scrollen vollständig sichtbar und per Hitprobe unverdeckt.
**194 Webchecks, 46 Import-/Anhangsintegrationschecks und 150/150 Layoutchecks**
sind auf der gemeinsamen finalen Projektion erneut bestanden:
`7a0c31a550761badd32e07f4bdaee6b016fd158a769a64017c7525332bb70416`.
Rohbelege, Quellhashes und Reproduktion stehen in
`pruefnachweise/android-tablet-followup-2026-11-26/`. Diese Zahlen sind
spezifische Hostnachweise, kein gemeinsamer Androidlauf.

Der echte Actions-Baulauf 45806941029 auf `e7d396e` bestand Vorbereitung,
Readiness, Provenienz und die 194/46 Web-/Importchecks. Er stoppte vor Gradle,
weil der gemeinsame Desktop-Setuptest einen nicht vorhandenen generierten
Zeitzonencache erwartete. Folgepatch 8 zu #790 erzeugt den bestehenden Bootstrap
für diesen Test im Speicher; 88 Cross-Desktop-Fälle in 20 Sprachen sind bestanden.
Veraltete Caches werden nicht gelesen, beschädigte normative Daten bleiben ein
harter Fehler. Neue Projektion:
`3dcf2073c46012e193900fce971a5bab91cefd5194f433bac7169e7f98917907`.
Alle 83 Laufzeitdateien sind exakt identisch zum zuvor geprüften Stand; nur der
gemeinsame Test ist als Projektionsquelle verändert. Dieser gemeinsame
Cross-Desktop-Befund ist zusätzlich in #804 mit engem Quellpatch dokumentiert.

Der folgende echte Actions-Lauf 45809316206 auf `2dd93930` bestätigt den
Setupfix im frischen Checkout: 88/20 Fälle, 194/46 Web-/Importchecks und
22 Provenienztests bestanden. Gradle kompiliert Produkt-Kotlin, Manifest und
Ressourcen; `compileDebugUnitTestKotlin` scheitert anschließend an fünf auf dem
Android-Kompilierpfad fehlenden `JSONObject.similar`-Aufrufen. Der eigene
Test-Kompilierbefund #805 wird mit einem vollständigen strukturellen Vergleich
über öffentliche JSON-APIs korrigiert. Genaue Zahlenwerte, Arrayreihenfolge,
Null-/Fehlfeld- und Typunterschiede bleiben Prüfanforderungen. Die originalen
CI-Fehlerbelege stehen in `pruefnachweise/android-tablet-followup-2026-11-26/ci-run-45809316206/`.
Dieser Lauf erzeugte kein APK und führte keine nativen Schritte aus.
Die enge Korrektur zu #805 kompiliert gegen die echten Android-37.2-APIs;
42/42 gezielte JVM-Tests sind bestanden, darunter alle betroffenen Dokument-/
Kalender-/Vaulttests sowie zwölf neue exakte Vergleichsfälle. Die vorherige
Kompilierstörung und die unveränderten 38 Produktquellen sind hashgebunden belegt.
Kein Produktcode, Manifest, Gradle-Gate oder vorhandener Test wurde dafür entfernt
oder umgangen. Rohbelege unter `pruefnachweise/android-tablet-followup-2026-11-26/issue-805/`.

Für #791 wurde zusätzlich `tablet-system-records` vorbereitet: vollständiger
APK-Bau, anschließend eine eigene API-34-/google_apis-Providerstufe mit elf
Prüfgruppen. Sie verwendet echte Kontakt-/Kalenderprovider, ausschließlich eigene
synthetische Fixtures und die tatsächlichen Produktleser. Schreibrechte gelten
nur bei Fixture-Arbeiten; jeder Produktzugriff prüft zuvor die abgelegte
Shellidentität und fehlende Schreibrechte. Zwei Kalender erlauben einen echten
Auswahlvergleich; Kontakt-Quellenisolierung wird mit der einzigen lokalen
Kontaktquelle ausdrücklich nicht behauptet. 24 Quellen-/Workflowprüfungen,
vier Owner-Verträge und die reale API-Kompilierung sind belegt; die beiden letzten
Scope-Literale wurden gesondert nachkompiliert. Diese Vorbereitungsbelege enthielten
noch keine Emulator-/Provider-Ausführung. Der anschließend tatsächlich ausgeführte
Lauf #99 wird im folgenden Absatz getrennt ausgewertet. Ein UI-/Berechtigungsdialog-,
Save-ACK- oder vollständiger nativer Abnahmenachweis folgt daraus nicht.
Die Rohbelege der Vorbereitung stehen im Unterordner `system-records/`.

Der tatsächliche Actions-Lauf #99 auf Head `92e2c645cf0a8075325874f335087412e7f79c79`
ist getrennt ausgewertet. Versuch 1 scheitert extern an Maven-Central-HTTP429.
Versuch 2 besteht den vollständigen APK-Gate und **303 JUnit-Tests aus 42 XML-Reports,
0 Fehler/Ausfälle/Skips**. Tatsächliche App-/Instrumentierungsbytes,
Kandidatenmanifest und die Projektion innerhalb der APK sind gegen die
Quellbindung geprüft. Die native Providerstufe besteht acht Fachgruppen und
Cleanup, scheitert aber an der erwarteten Zweiermenge nach einer Serienausnahme.
Ihre Ist-Anzahl fehlt im Originalreceipt; kein Duplikat wird daraus abgeleitet.
Alle 16 Produktaufrufe liefen ohne WRITE. Eigene Kontakte/Kalender vollständig
entfernt; Cancellation nach dem Fehler nicht erreicht. Belege: `ci-run-45817099578/`.

Der enge Folgefix #807 ergänzt die bereits synthetische Syncadapter-Fixture um
vollständige Master-/Ausnahmeverknüpfung, direktes Event-Rücklesen und begrenzte
Vorher-/Nachher-Slots. Alle bisherigen Anzahl-/Identitäts-/Zeitprüfungen bleiben
hart; Produktcode und Gates bleiben unverändert. Die unsyncte lokale
Serienausnahme ist ausdrücklich nicht durch diese Fixture abgenommen. Bei
Erstellung von Folgepatch 11 stand dessen native Wiederholung noch aus.

Die anschließende Wiederholung [Actions #101](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45822320243)
auf Head `7a7d90b04796cf338b98f0fdbb87e8da1c967043` / Tree
`06c1a8cf6f115908dc21252682c2a358246f2cb7` besteht den vollständigen APK-Gate
und die echte API34-Providerstufe. 42 Original-JUnit-Reports bestätigen erneut
303 Tests ohne Fehler/Ausfälle/Skips. Alle elf Providergruppen einschließlich
Cleanup bestehen. Die Serien-Fixture liefert vor/nach der Ausnahme genau zwei
Instanzen: 09:00 wird bei gleicher ursprünglicher ID zu 12:00; der Folgetag
bleibt unverändert. Beide vorab abgebrochenen Abfragen wurden erreicht;
19 protokollierte Produkt-/Readbackaufrufe liefen ohne WRITE. Die zwei eigenen
RawContacts und zwei Kalender wurden vollständig entfernt. Originalbelege und
ausgeführter Artefaktprüfer stehen unter `ci-run-45822320243/`.
Der abschließende Nachtrag ändert nur Dokumentation und Nachweise; der tatsächlich
gebaute und nativ geprüfte Head bleibt ausdrücklich der oben genannte.

Offen bleiben unsynchronisierte lokale Serienausnahmen, eine zweite Kontaktquelle,
Android-Berechtigungsdialoge und Live-Widerrufe, UI-/Save-ACK, laufende Query-Cancellation,
TalkBack, IME, Stift, native Pixel-/SAF-/Restore-/Neustartmatrix und tatsächliche
HTTPS-/Clipboard-Bedienung. Historische native
Teilnachweise und heutige Reste werden im Audit getrennt geführt. Für die
unterschiedlichen Befunde in #458, #463 und #471 bleiben die jeweiligen Ursachen-
und Restprüfungen offen. Geschlossene Quell-/Native-Teilfixes werden nicht ohne
neue Regression wieder geöffnet.

## Periodenvorhersage – Integration zu #803, 27. November 2026

[Issue #803](https://github.com/maik3531/Magnolie-Organizer/issues/803)
enthält den geprüften Patch auf Basis von
`d4da48a5eadd0bda22422b924bef4ee3b4324040`. Er ist mit den
zwischenzeitlichen Mac-/Tablet-Änderungen zusammengeführt.
Die dauerhaften Dateien liegen im Artefaktzweig
`work/issue-803-period-forecast-patch` unter `patches/issue-803/`.
Es ist eine Erweiterung der bestehenden Funktion aus #79: optionales
Schätzfenster mit blassen Tropfen, getrennte gestrichelte Hinweissymbole mit
Tooltip, ausdrückliche Bestätigung einzelner tatsächlich beobachteter Tage
und Verfall unbestätigter Vorhersagen ohne erfundene Blutungseinträge.

Bekannte, selbst angegebene Gründe wie Schwangerschaft, Stillzeit,
Medikamente/hormonelle Behandlung und Wechseljahre können die Planung
pausieren. Schwangerschaft schlägt neun anpassbare Kalendermonate vor;
unbefristete Pausen sind ebenfalls möglich. Neu erfasste Blutung beendet
eine Pause erst nach separater Bestätigung als neue Periode. Danach beginnt
die Berechnung mit neuen bestätigten Anfängen. Vertrag und Handbuch erklären
diese Regeln einschließlich der medizinischen Grenzen in allen 20 Sprachen.

Geprüft: 60 unabhängige Datums-/Kontextfälle, 1.000 erzeugte Verläufe je
JavaScript-Frontend, vollständiger JS-/Python-Abgleich, 9.260 JS-Prüfaussagen,
16 Python-Testgruppen, 1.114 portable C#-Prüfaussagen einschließlich
250 erzeugter Verläufe, 60 vollständige Python-/C#-Vergleiche, 113 bestehende
Desktop-Regressionsfälle, MCP-Prüfung beider Oberflächen und zehn reale
Chromium-Szenarien. Dazu kommen die geprüften Sprachkataloge und eine
unabhängige Bedienungsprüfung. Die Prüfprotokolle nennen die genauen Grenzen.
Keine klinische Genauigkeitsprüfung, keine Abnahme installierter Windows-
oder Linux-Pakete und keine native Zustellungsprüfung von Benachrichtigungen.
Auf der zusammengeführten Quelle bestanden beide Oberflächen mit 9.260
Vorhersage-Prüfaussagen, 113 Desktop- und 321 Kontaktgeburtstagsprüfungen.
Dazu kommen 95 Python-Fälle und auf dem vorhandenen Windows-Rechner 1.114
C#-Prüfaussagen. Beide Sprachkataloge enthalten die neuen Texte aus den
beiden Patchserien. Die installierte Benachrichtigungsprüfung bleibt offen.
