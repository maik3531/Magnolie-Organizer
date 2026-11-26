# Erneute Stabilitätsprüfung und gesicherte Weiterführung

Stand: **26. November 2026**. Folgeauftrag zu #121/#783 und zum
[Übernahmeplan](../contracts/macos-stable-integration-2026-11-26.md).
Dieser Bericht hält die zusätzliche Prüfung nach dem erfolgreichen nativen
Lauf #97 fest. Historische Laufbelege werden nicht überschrieben.

## Quellstände und aktueller Abschluss

| Teil | Tatsächlich gebundener Stand |
| --- | --- |
| Gemeinsame Hostregression | `c8a7690d5eb4e002ebadb1d0aab03c8780af9e0b`; Produktcode `215d89029df02df2dce78f35412785ec9f9b36d8` |
| Neuer enger Bauprüferfix #806 | `6599dcb2a7d337f4b248b8b172e5e18c537a2dfa` |
| Erweiterung der nativen Prüfungen | `8c860a14f7e10904c1b3a159ae84619c2c24ba82` |
| Korrekte moderne/Legacy-Deploymentfelder #806 | `625233067cd49e204786deb5706e6bc08ef85c4e` |
| AirPlay-Testwurzelfix #793 | `f7957801ba99c0e65e7eaeb70f69824efcd55fd0` |
| Archivzeitstempelfix #808 und aktueller nativer Prüfkandidat | `3f3ec069895dec254c53660d14e6851cb23077cd`, Tree `176fa7f362227c92ec4d7c4bf08d09b855951ae7` |
| Aktueller nativer Lauf | [#104 / 45827353062](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45827353062), Attempt 1; **completed / success**, 26. November, **14:15:18–14:49:42 Uhr Europe/Berlin** (34 Minuten 24 Sekunden) |
| Native Jobs | ARM64 `139934825830`, Intel `139934826621`; Tablet nicht ausgewählt |
| Arbeitszweig | `work/macos-issue-fixes-20261126`; entfernten Head bei Fortsetzung erneut lesen |

**Abschluss:** Die gemeinsamen Hostregressionen, die funktionale
Wiederherstellung und der erweiterte native Mac-Lauf sind abgeschlossen.
**#104 besteht auf ARM64 und Intel einschließlich tatsächlichem Runtimebau,
neuer Swift→Python-Prozessprobe, optimierten Swift-Tests, Signatur-,
App-Lebenszyklus- und Paketgates.** Beide Entwicklungspakete sind zusätzlich
unabhängig gegen ihre tatsächlichen Bytes und Quellen geprüft. Der getrennte
Windows-Lauf #552 reproduziert dagegen den offenen Cleanupbefund #794.
Die weiteren unten benannten stabilen Freigabegates bleiben offen. Spätere
Dokumentationscommits ändern nicht den geprüften Quellanker `3f3ec069`.

## Endgültiger nativer Mac-Lauf #104

Der [vollständige strukturierte Abschlussbeleg](verification/native-run-104.json)
bindet beide tatsächlich abgeschlossenen Jobs, alle Testkontexte und Skips,
die aktuellen Git-Aufrufer sowie die heruntergeladenen Artefakte. Er wahrt den
ursprünglichen eingefrorenen Capture mit SHA256
`1c8839c7fe2056f1a425c16eb6b35c6ed48cf8240dde20b35bd21dae35ef4598`.
ARM64 lief auf **macOS 15.8.2**, Intel auf **macOS 15.7.9**; beide verwendeten
SDK 15.5. Das verifizierte Deploymentziel 12.7 ist kein Lauf auf Monterey.

| Tatsächlich ausgeführte Prüfung | ARM64 | Intel |
| --- | --- | --- |
| Quellenvertrag | 7 bestanden | 7 bestanden |
| Runtimebuilder einschließlich echter Darwin-Mach-O-Probe | 26 bestanden, kein Skip | 26 bestanden, kein Skip |
| AirPlay-Bauprüfer und Ablehnungsgrenzen | 27 bestanden | 27 bestanden |
| ImportHelper / Projektionspfade | 17 bestanden | 17 bestanden |
| Host-Suite | 35 insgesamt: 34 bestanden, 1 Skip | 35 insgesamt: 34 bestanden, 1 Skip |
| Swift Debug: Kalendercodec, UTC | 501 insgesamt: 497 bestanden, 4 Skips | 501 insgesamt: 497 bestanden, 4 Skips |
| Swift Debug: Editor, UTC | 501 insgesamt: 496 bestanden, 5 Skips | 501 insgesamt: 496 bestanden, 5 Skips |
| Swift Debug: Editor, Europe/Berlin | 501 insgesamt: 496 bestanden, 5 Skips | 501 insgesamt: 496 bestanden, 5 Skips |
| Swift Debug: Entwicklungsbau mit Live-Feiertagen | 501 insgesamt: 495 bestanden, 6 Skips | 501 insgesamt: 495 bestanden, 6 Skips |
| Swift Release: optimierte Konfiguration mit Live-Feiertagen | 501 insgesamt: 495 bestanden, 6 Skips | 501 insgesamt: 495 bestanden, 6 Skips |
| Originaler Swift-Prozess → signierte gebündelte Python-Runtime | 9/9 Kriterien | 9/9 Kriterien |
| Tatsächlicher App-Lebenszyklus | 7/7 Merkmale | 7/7 Merkmale |
| Native innere/äußere Signaturprüfung, Appbau und Paketierung | bestanden | bestanden |
| Unabhängiger Paketbyteaudit | 65/65, keine Abweichungen | 65/65, keine Abweichungen |

Alle aufgeführten Suiten enden ohne Fehler. Der Host-Skip ist ausschließlich
`test_no_linux_native_build_claim` mit dem Grund „Negative Linux-only build
gate“. Die Swift-Skips sind im Beleg einzeln benannt: Je nach Kontext fehlen
absichtlich die für Kalender, Editor, Druck oder opaque JSON benötigten
Live-Fixtures; die Live-Feiertagsprüfung ist in den ersten drei Kontexten
nicht eingeschaltet. Der vollständige opaque-JSON-Speicherpfad bleibt #511.
**Die fünf Swift-Kontexte führen dieselben 501 Testnamen aus.** Sie sind keine
2.505 unterschiedlichen Tests. Pacific/Honolulu ist zwischen den Editorläufen
ein zusätzlicher JavaScript-Kontext ohne Swift-Aufruf. Die
[Zuordnung der tatsächlichen Aufrufer](verification/stability-2026-11-26/native-run-104/swift-context-callers.json)
ist gegen die Git-Objekte von `3f3ec069` und die originalen Logmarker geprüft.

### Echte Prozess- und Appgrenzen

Die neue Prozessprobe verwendet die unveränderte Produktionsdatei
`FileImportProcess.swift`, die tatsächlich gebauten BetaCore-Objekte sowie
den signierten Interpreter und ImportHelper aus dem App-Bundle. Sie bestätigt
auf beiden Architekturen das Lesen der originalen **155.648-Byte-OR6-Fixture**,
**22 bekannte Felder aus vier Sammlungen**, die isolierte Python-Umgebung und
die Ablehnung strukturierter Helperfehler, ausgewählter Symlinks, leerer und
übergroßer Dateien. Originalfixture und gebundene Appbytes bleiben erhalten;
die App-Signaturen sind nativ vor und nach der Probe geprüft.

Der App-Smoke bestätigt einen Start mit sichtbarem, an den Prozess gebundenem
Fenster, ein frisch normalisiertes gespeichertes Profil, normales Beenden,
Wiederöffnen, erneutes atomares Speichern und Datenerhalt. Die Profilhashes
sind jeweils vor/nach Wiederöffnen identisch. Beide tatsächlichen Screenshots
wurden visuell angesehen: gerenderte Buch-Startseite im richtigen nativen
Fenster, Datum und Bedienelemente sichtbar, keine leere WebView oder sichtbarer
Absturz. Dies ist eine Startansicht; Kalender-/Editorbedienung, Picker und
Berechtigungen sind dadurch nicht vollständig abgenommen. Der später erfolgte
Intel-Sichtreview ist separat erhalten und schreibt den früher eingefrorenen
Gesamtcapture nicht um.

### Paket-, Quellen- und Logbindung

Beide Audits binden **3921 Quelldateien** an den nativen Quellcommit,
**555 Projektionsinputs** (535 Git-Dateien, 19 erzeugte Kataloge, ein gepinntes
Wheel), **1312 tatsächliche Projektionsausgaben** sowie **706 Runtime-Dateien**
mit **52 Mach-O-Dateien**. Die tatsächlichen Header bestätigen ARM64 bzw.
x86_64, macOS-Plattform 1 und Mindestversion 12.7.0. **1967 Ressourcenhashes**,
ein Helper-Codeverweis und 51 Plug-in-Codeverweise stimmen mit den tatsächlichen
Paketbytes überein.

Die vollständige Quellenprüfung wurde für ARM gegen 3817 verschiedene Git-Blobs
ausgeführt. Intel verwendet diesen Vergleich erst nach bewiesener Byteidentität
seines Quellenmanifests und bindet den vollständigen ARM-Audit-Hash; die
architekturspezifischen Paketbytes, Header, Runtime und Signaturreferenzen wurden
für Intel neu geprüft. Acht Prozessdateien wurden aus jedem echten Paket neu
gehasht. Die nicht mitgelieferten BetaCore-Objekte und das kompilierte
Probeprogramm sind ausschließlich durch die originalen nativen Receipts
belegt. Ihre Bytes wurden im unabhängigen Linux-Audit nicht erneut gelesen.
Die native `codesign`-Prüfung stammt aus den Mac-Jobs; der anschließende Audit
prüft Strukturen, CodeDirectory-Verweise und Ressourcenhashes.

| Entwicklungspaket | Bytes | SHA256 des inneren App-ZIP |
| --- | ---: | --- |
| ARM64, Artefakt `15122996395` | 23.986.905 | `a7eeb56c95387e1f40370b8b808bfd13e16fc9dc51e7787cdfb900c38135e908` |
| Intel, Artefakt `15122883740` | 24.200.163 | `353f0763aa8c5de4bcd284c3def66de56023c8de211abe723909e456d2624dda` |

Auch die äußeren Artefakt-ZIPs sind vollständig heruntergeladen und gegen die
API-Digests geprüft. Die Pakete bleiben **ad hoc signierte Debug-Entwicklungsapps**.
Die separaten optimierten Swift-Tests erzeugen keine notarisierten
Produktionspakete. Die [ARM-](verification/stability-2026-11-26/native-run-104/arm64/independent-candidate-audit.json)
und [Intel-Audits](verification/stability-2026-11-26/native-run-104/intel/independent-candidate-audit.json)
halten alle 65 Kriterien und die Grenzen fest.

Der dauerhafte Belegsatz bewahrt beide vollständigen originalen Joblogs und
acht zusätzliche vollständige native Runtime-, Release-, Konsolen- und
Smoke-Protokolle verlustfrei als gzip; ursprüngliche Bytes, Größen und
SHA256 stehen im
[Dateimanifest](verification/stability-2026-11-26/native-run-104/durable-evidence-manifest.json).
Auch die ursprünglichen JSON-Belege und das gemeinsame Quelleninventar sind
enthalten. Gzip-Dateien müssen nach dem Entpacken wieder die dort angegebene
Originalgröße und SHA256 besitzen. Die App-ZIPs und Screenshot-Bilddateien
bleiben zeitlich begrenzte Actions-Artefakte mit 14 Tagen Aufbewahrung (bis
10. Dezember 2026); ihre Hashes, Inventare und Sichtprüfungen sind dauerhaft
im Git-Belegsatz erhalten.


## Gemeinsame Regressionen

Die isolierte Prüfung verwendet unveränderte Quellen des oben genannten
Hoststands. Nach Abschluss wurden alle **3912 gebundenen Quelldateien** erneut
geprüft; der isolierte Git-Arbeitsbaum ist sauber. Die neuen Bauprüfer- und
nativen Prüftreiberänderungen sind gesonderte Eingaben und erhalten ihre eigenen
Nachweise. Die folgenden Umfänge überlappen; sie werden nicht zu einer erfundenen
Gesamtzahl eindeutiger Tests addiert.

| Prüfung | Ergebnis | Aussagegrenze |
| --- | --- | --- |
| Gemeinsame Python-Auswahl für OR6, Serien, Unicode, Reminder, Kalender und Archivlayout | **444 Tests und 14 Untertests bestanden**, keine Fehler oder Skips; darin 131 OR6-Fälle aus 18 Dateien | Gemeinsame Parser-/Modellverträge |
| Mac-Quell-, Runtime-, AirPlay- und Helperverträge auf dem Hoststand | **7 / 21 / 25 / 17 Tests bestanden** | Die spätere #806-Erweiterung ist separat geprüft |
| Mac-Host | **35 unterschiedliche Fälle bestanden**: 34 im Erstlauf, der zunächst blockierte Fall anschließend gezielt | Keine native Mac-Ausführung auf diesem Linux-Host |
| Tatsächlicher OR6-Helper → projizierte Mac-UI | **90 Checks bestanden** | Transport und Speicherbestätigung an der ausgewiesenen Testgrenze synthetisch |
| Vollständiges Linux-Parser-/Abgleichscript | **1137 ausgegebene erfolgreiche Prüfungen**, Abschluss erfolgreich | Echtes PyGObject/GTK im direkten Headless-Aufruf; kein GUI-Lebenszyklus |
| Linux-Import-/Export-Vertrag | **26 ausgegebene Prüfungen**, erfolgreich | Gemeinsamer Formatvertrag |
| Linux-Gesamt-DOM und Windows-Web-Smoke | Beide erfolgreich | Kein nativer GTK-/WebView2-Paketlauf |
| Alter Android-ICS-Wiederimport auf aktueller Linux-/Windows-UI | Beide Kontexte erfolgreich | Tatsächlicher Python-Codec, synthetischer Save-ACK; kein C#-Nachweis |
| Zeitzonen | **597 Zonen**, 37 Uhrkontexte / 370 Localeformate, 44 Projektorchecks, 9 TZif-Tests und ein tatsächlicher CRLF-Git-Checkout-Test bestanden | Bestehende gemeinsame Quell-/Hostverträge |

Der zunächst fehlgeschlagene Mac-Hostfall benötigte zwei historische
Referenzblobs aus `067c389`. Nach Prüfung ihrer Git-Objekt-IDs wurden diese
ausschließlich im isolierten Objektspeicher ergänzt. Der gezielte Wiederholungslauf
bestand; die übrigen 34 bestandenen Fälle wurden nicht unnötig wiederholt.
Ursprüngliche Fehlerausgaben und der konkrete Wiederholungslauf bleiben erhalten.

Die vollständige Parserprüfung verwendet die echten erzeugten Kataloge und
Klangdateien sowie das vorhandene System-Python mit PyGObject/GTK. Der Wrapper
`dbus-run-session` konnte im Prüfhost keinen Sitzungsbus-Socket öffnen
(`Operation not permitted`). Der dokumentierte direkte Parseraufruf bestand.
Ein bestandener Debian-Paket- oder Sitzungsbustest wird daraus nicht abgeleitet.
Zwei pytest-Warnungen betreffen angekündigte API-Änderungen; die betroffenen
Testfälle bestanden.

Die [ausführliche Lesefassung](verification/stability-2026-11-26/SHARED-REGRESSION-2026-11-26.md)
und der [vollständige strukturierte Nachweis](verification/stability-2026-11-26/shared-regression.json)
sichern alle 44 Befehlsprotokolle sowie zwei zusätzliche Abhängigkeitslogs.
Ursprüngliche und normalisierte Größen/Hashes sind getrennt festgehalten;
die ursprünglichen 63 Belegreferenzen kennzeichnen ausdrücklich die
46 eingebetteten Logs und 17 nur über Hash referenzierten Artefakte.
Der spätere reine Git-Vergleich bestätigt die byte-/modusgleichen gemeinsamen
Produktbäume bis `8c860a14`; er benennt sämtliche davon abweichenden Bauprüfer,
neuen Prüftreiber und Dokumentationsdateien. Der Hosttestanker bleibt unverändert.
Die [anschließende gezielte Git-Nachprüfung](verification/stability-2026-11-26/integration-3f3ec069.json)
erweitert diese Eingabeidentität bis `3f3ec069`: alle 20 Verzeichnisbäume
außerhalb des Mac-Unterbaums und der gemeinsame Workflow sind gegenüber
`8c860a14` unverändert. Seitdem ändern sich ausschließlich der Arbeitsstand,
zwei Mac-Bauwerkzeuge und deren zwei Testdateien. Die neuen Prüfungen dieser
geänderten Eingaben werden separat ausgewiesen.

## Getrennte erneute Windows-CI

Der automatisch gestartete [Windows-Lauf Nr. 552 / 45820275770](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45820275770)
prüft `8c860a14f7e10904c1b3a159ae84619c2c24ba82`. Er endete am
26. November um **14:19:03 Uhr Europe/Berlin** mit `failure`; das ist die
Abschlussaktualisierung des Laufs, nicht die Dauer einer einzelnen Testgruppe.

Die Core-Ausgabe bestätigt **551 von 552 Testgruppen bestanden**. Einzig
„Media support draft / original Windows WLAN reader and withdrawal“ scheitert
mit `IOException` beim Löschen der noch geöffneten `phone.db`:
`PhoneCameraParentTests.Fixture.Dispose():93` →
`SharedSyncTransportTests.NativeMediaSupportAsync():201`. Damit ist der bereits
bekannte getrennte Cleanupbefund [#794](https://github.com/maik3531/Magnolie-Organizer/issues/794)
auf dem neueren Quellstand tatsächlich erneut belegt. Die vier dort relevanten
C#-Quellen waren gegenüber dem früheren Fehlerstand bytegleich; diese
Mac-Nachprüfung enthält dafür keinen Produktfix.

Das Windows-Quellarchiv-Gate endet mit Fehler. ZIP-, Installer- und
Artefaktupload folgen nicht; die Artefaktliste ist leer. Dieser neue Befund
wird weder als bestandene Windows-Abnahme noch als Fehler der Mac-Runtime
umgedeutet. Die genaue ursprüngliche Cleanupursache und eine passende
Windows-Korrektur bleiben unter #794 weiter zu bearbeiten.

Die [Lesefassung des Windows-Abschlusses](verification/stability-2026-11-26/windows-run-552/WINDOWS-RUN-552-FINAL.md)
und der [strukturierte Nachweis](verification/stability-2026-11-26/windows-run-552/windows-run-552-final.json)
sichern die vollständigen **1164 Logzeilen**, getrennte Original-/Normalisierungs-
Hashes und die gelesenen GitHub-Metadaten. Die #787-Quell-/Privatpfad-/Provenienz-
und Prüfsummenfixtures bestehen ausdrücklich; der gesamte Archivschritt scheitert
erst am genannten CoreTests-Ergebnis. Die SQLite-Poolvariante bleibt eine
unbestätigte Ursachenhypothese.

## #806: bestätigter Befund und begrenzte Korrektur

Der bisherige Runtime-/App-Metadatenprüfer kontrollierte die CPU und
Mindestversion, ohne die Apple-Zielplattform ausreichend zu binden. In einer
isolierten Negativprobe akzeptierte er dadurch passende iOS-, Catalyst- und
Simulatorangaben. Beim optionalen AirPlay-Prüfer konnten spätere
Deploymentdeklarationen eine widersprüchliche frühere Angabe verdecken.

Der gemeinsame Parser verlangt nun genau eine eindeutige zulässige
macOS-Deploymentdeklaration. Runtime-Minimum höchstens 12.7, äußeres App-Minimum
exakt 12.7/12.7.0, die ausdrücklich erlaubte AirPlay-Legacy-Deklaration sowie
Architektur-, Systembibliotheks-, RPath-, Inventar- und Signaturregeln bleiben
erhalten. Vor der Änderung wurde [#806](https://github.com/maik3531/Magnolie-Organizer/issues/806)
angelegt; der Fix ist als eigener Commit reviewbar.

Die echten #97-Pakete besitzen korrekte macOS-Metadaten. Die Negativprobe
ändert nur Metadatenfelder und verletzt bestehende Signaturen; sie belegt keinen
Erfolg manipulierter Pakete durch die vollständigen Signatur- oder Relokationsgates.
Lokal bestanden **23 von 24 Runtimefällen** mit einem ausdrücklich Darwin
vorbehaltenen Skip sowie **26 von 26 AirPlayfällen**. Der zusätzliche Darwin-Fall
kompiliert eine kleine echte Mach-O-Datei und prüft die gezielt veränderten
Plattformfelder mit Apples tatsächlichen Werkzeugen. Er führt die veränderten
Binärdateien nicht aus.

[Dauerhafter Vorher-/Nachherbeleg](verification/stability-2026-11-26/runtime-review.json)
enthält Quellenhashes und die lokalen Prüflogs.

### Erhaltener Zwischenfehler aus #100

[Lauf #100](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45821167801)
hat auf `8c860a14` in beiden Architekturen den positiven Originalfall der neuen
Darwin-Probe abgewiesen: **je 24 Runtimefälle, 23 bestanden und ein Fehler**.
Die Zeitzonenprüfungen waren erfolgreich, die nachfolgenden Runtimebau-,
AirPlay-, Host-, Import-Prozess-, Swift-, Signatur-, App- und Paketphasen wurden
nicht ausgeführt. Der Lauf endete um **13:40:50 Uhr Europe/Berlin** mit `failure`.

Der gemeinsame Metadatenparser zählte die im modernen `LC_BUILD_VERSION`
zusätzlich ausgegebenen Compiler-/Linker-`version`-Felder irrtümlich als weitere
Deploymentversionen. Die nachträgliche Reproduktion verwendet die durch Apples
Formatterquelle belegte Struktur; der konkrete native `vtool`-Rohtext wurde in
#100 noch nicht ausgegeben. `62523306` liest beim modernen Command ausschließlich
`minos`, beim Legacy-Command ausschließlich dessen `version`. Zwei neue
Regressionen prüfen diesen Unterschied, und der positive native Fehlerfall
druckt künftig seine tatsächlichen Metadaten.

Nach dieser Korrektur bestehen lokal **25 Runtimefälle: 24 bestanden und ein
Darwin-only Skip**, sowie **27 von 27 AirPlayfällen**. Die unveränderten
Plattform-, Mehrdeutigkeits- und Mindestversionsgrenzen bleiben Bestandteil der
Suite. Der [dauerhafte #100-Beleg](verification/native-run-100.json) erhält den
Fehler, beide heruntergeladenen Diagnosearchive, die zugehörigen Quellenhashes,
die vollständigen lokalen Korrekturlogs und den getrennten Publikationsnachtrag.

### Erhaltener Testwurzelbefund aus #102

[Lauf #102](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45823313660)
prüft `62523306` auf beiden Architekturen. Beide bestehen die **25 Runtimefälle
ohne Skip**, einschließlich der echten Mach-O-Prüfung. Die erstmals nativ
ausgeführte AirPlay-Suite zeigt anschließend je **zwei Fehler unter 27 Fällen**:
Die selbst erzeugte Testwurzel verwendet `/var`, während das Produkt dieselbe
SDK-Wurzel korrekt als `/private/var` kanonisiert.

Eine echte Linux-Elternaliasprobe reproduziert beide Vergleiche. Der enge
Callerfix zu #793 in `f7957801` löst ausschließlich die neu erzeugte
Testwurzel kanonisch auf. Produktpfade und SDK-/Symlinkgrenzen bleiben
unverändert. Danach bestehen lokal alle 27 Fälle sowie beide gezielt
wiederholten Aliasfälle. #103 bestätigt anschließend auf beiden echten Macs
**27/27 AirPlayfälle ohne Skip**. Der
[#102-Beleg](verification/native-run-102.json) bewahrt den ursprünglichen Fehler,
die lokale Reproduktion und die getrennte Bindung an den Korrekturcommit.

## #808: Archivzeitstempel im tatsächlichen XZ-Bau

[Lauf #103](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45824626525)
auf `f7957801` besteht auf beiden Architekturen die Quell-/Zeitzonenphase,
**25/25 Runtimefälle und 27/27 AirPlayfälle**. Der anschließende private
XZ-Bau erreicht erfolgreich `configure`, löst dann aber über `am--refresh`
unnötig `aclocal-1.18` aus und bricht mit dem fehlenden Befehl ab. CPython,
Host-, Importprozess-, Swift-, App- und Paketgates werden danach nicht erreicht.

Der vorhandene sichere Extraktor kopiert Quelldateien in Archivreihenfolge,
übernimmt aber deren Änderungszeit nicht. Im echten hashgeprüften Archiv ist
`configure.ac` 46 Sekunden älter als `aclocal.m4`, steht jedoch später.
Nach dem Kopieren sieht Make die Eingaben fälschlich als neuer an. Eine
isolierte Linux-Probe mit unverändertem Extraktor, demselben gepinnten Archiv,
erfolgreichem `configure` und echtem lib-only `make -n` reproduziert exakt
den Abbruch. Der neue Befund wurde vor der Änderung in
[#808](https://github.com/maik3531/Magnolie-Organizer/issues/808) erfasst.

Der Korrekturumfang in `3f3ec069` beschränkt sich auf die Archivzeitstempel
bereits validierter regulärer Quelldateien und eine echte Make-Regression. Pins, Downloadhash,
Pfad-/Link-/Größengrenzen und die vorhandenen Baubefehle bleiben erhalten.
Der neue Regressionstest scheitert vor dem Fix und besteht danach: keine
unnötige Regenerierung bei unveränderten Eingaben, weiterhin ein tatsächlicher
Rebuild nach einem echten `touch`. Die lokale Runtime-Suite führt **26 Fälle**
aus, davon **25 bestanden und ein Darwin-only Skip**. Der produktive Bauhelfer
besteht mit dem echten gepinnten XZ-Archiv `configure`, statischen lib-only-Bau
und private Installation; **655 Quelldateien** stimmen anschließend in Bytes
und mtime mit dem Archiv überein. Ein unabhängiger Diffreview bestätigt die
beiden eingefrorenen Quell-/Testdateien ohne Blocker.

Der [dauerhafte #103-Beleg](verification/native-run-103.json) erhält den
ursprünglichen nativen Fehler, beide Diagnosedigests, den separaten lokalen
Korrektur- und Publikationsnachtrag sowie sieben vollständig eingebettete
Vorher-/Nachherdateien einschließlich des tatsächlichen lokalen XZ-Bauprotokolls.
Die getrennte Hostreproduktion wird durch den tatsächlich erfolgreichen
nativen Lauf #104 ergänzt: vollständiger XZ-/CPython-Runtimebau und **26/26
Runtimefälle ohne Skip auf beiden Architekturen** bestätigen den Fix nativ.

## Erweiterter nativer Prüfumfang

Der seit `8c860a14` erweiterte Workflow behält die Quell-, Runtime-, Projektions-, Host-, Swift-,
Signatur- und App-Lebenszyklusgates bei. Hinzu kommen:

1. Die neue tatsächliche Darwin-Mach-O-Negativprüfung und die vollständige
   AirPlay-Boundarysuite auf beiden Architekturen.
2. Ein echter Swift→Python-Prozesslauf mit der unveränderten Produktionsdatei
   `FileImportProcess.swift`, den tatsächlichen BetaCore-Objekten und dem
   signierten App-Bundle. Die originale OR6-Fixture umfasst 155.648 Bytes und
   22 erwartete Felder aus vier Kollektionen. Neun klar benannte Kriterien
   prüfen Lesen, Protokoll, Prozess, Ergebnis und Ablehnungsgrenzen.
3. Ein zusätzlicher vollständiger Swift-Testkontext mit
   `swift test -c release --jobs 2`.

Der Prozesslauf benutzt keinen Dateiauswahldialog, Editor oder gespeichertes
Buch. Die optimierte Swift-Testkonfiguration ändert das tatsächlich paketierte
Artefakt nicht in ein Produktionspaket: Der Entwicklungsbau bleibt Debug und
ad-hoc signiert. Die
[zehn bestandenen lokalen Treiberprüfungen](verification/stability-2026-11-26/native-process-driver-local.json)
sichern die lokale Prüfinfrastruktur. Die tatsächliche native Ausführung
ist anschließend durch #104 auf beiden Architekturen separat belegt.

## Übergabe und spätere stabile Übernahme

Die [Integrationsnachweise](verification/stability-2026-11-26/integration-summary.json)
belegen die tatsächlich angewendeten **24 Originalpatches**, die exakte
Rekonstruktion jedes Zwischenbaums und des historischen Merges sowie alle
30 Publikationsdateien und 29 Prüfsummeneinträge. Fehlende Thin-Pack-
Voraussetzungen einer Teilkopie wurden vor dem erfolgreichen Restore
vollständig beschafft; das Originalbundle bleibt unverändert.

Der [Übernahmeplan](../contracts/macos-stable-integration-2026-11-26.md) legt fest,
wie spätere Änderungen an den gemeinsamen Quellen berücksichtigt, in einem
isolierten Integrationsstand geprüft und mit einem neuen Quellnachweis versehen
werden. Der spätere tatsächliche Zielzweig und sein Commit müssen feststehen;
ein alter Bericht gilt nicht automatisch für einen neuen Integrationscommit.

Die aktuelle Integrationsprobe ist an den Remote-Refstand vom **26. November,
14:16:51–14:16:58 Uhr Europe/Berlin** gebunden. `main` auf `d4da48a5` ist
genau die gemeinsame Basis des Kandidaten `3f3ec069`: **0 / 23 Commits**,
keine Konflikte, berechneter Tree exakt
`176fa7f362227c92ec4d7c4bf08d09b855951ae7`. Der abschließende API-Read um
**14:52:15 Uhr Europe/Berlin** bestätigt weiterhin denselben Main-Head.
Es wurde kein Merge ausgeführt.
Die [Lesefassung des aktuellen Vergleichs](verification/stability-2026-11-26/integration-3f3ec069.md)
trennt dies von dem historischen Android-Parallelvergleich auf `62523306` /
`7a7d90b0`; dessen zwei gemeinsame Pfade wurden ohne Konflikt zusammengeführt,
jedoch nur in einer Git-Berechnung, ohne gemeinsamen Build oder neuen Zweig.

Vor einer stabilen Mac-Auslieferung bleiben die ausdrücklich offenen Teile
von #785, #786, #511 und #465, der getrennte Windows-Rest #794 sowie
vollständige native Bedien-, Monterey-,
TCC-, Konto-/Geräte- und Auslieferungsabnahmen maßgeblich. Die
[Funktionsmatrix](FEATURE-MATRIX.md) und der [native Abnahmeplan](CLOUD-MAC-TESTING.md)
konkretisieren diese Grenzen. Ein eigener Mac beim Nutzer oder eine eigene
Magnolie-Notes-Begleitapp für das iPhone wird nicht vorausgesetzt.

Die Arbeit ist als nachvollziehbare Vorbereitung gesichert. Main-Übernahme,
Issue-Schließungen und Release-Veröffentlichung sind weiterhin eigene,
in diesem Auftrag nicht ausgeführte Schritte.
