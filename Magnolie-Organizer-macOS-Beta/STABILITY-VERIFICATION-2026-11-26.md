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
| AirPlay-Testwurzelfix #793 | `f7957801ba99c0e65e7eaeb70f69824efcd55fd0` |
| Archivzeitstempelfix #808 und aktueller nativer Prüfkandidat | `3f3ec069895dec254c53660d14e6851cb23077cd`, Tree `176fa7f362227c92ec4d7c4bf08d09b855951ae7` |
| Aktueller nativer Lauf | [#104 / 45827353062](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45827353062), Attempt 1; am 26. November um 14:15:18 Uhr Europe/Berlin gestartet, Ergebnis ausstehend |
| Native Jobs | ARM64 `139934825830`, Intel `139934826621`; Tablet nicht ausgewählt |
| Arbeitszweig | `work/macos-issue-fixes-20261126`; entfernten Head bei Fortsetzung erneut lesen |

**Zwischenstand:** Die gemeinsamen Hostregressionen und die funktionale
Wiederherstellung sind abgeschlossen. Der konkrete Extraktionsfehler #808 aus
#103 ist mit echter Vorher-/Nachherreproduktion korrigiert und gesichert.
Lauf #104 prüft den neuen Stand auf beiden Mac-Architekturen. Sein Abschluss
steht noch aus; ein laufender oder nur vorbereiteter Test zählt nicht als bestanden.

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
Diese Hostreproduktion ersetzt nicht den anschließenden nativen Lauf #104.

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
sichern die Prüfinfrastruktur, nicht die noch gesondert nachzuweisende native
Ausführung.

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

Vor einer stabilen Mac-Auslieferung bleiben die ausdrücklich offenen Teile
von #785, #786, #511 und #465 sowie vollständige native Bedien-, Monterey-,
TCC-, Konto-/Geräte- und Auslieferungsabnahmen maßgeblich. Die
[Funktionsmatrix](FEATURE-MATRIX.md) und der [native Abnahmeplan](CLOUD-MAC-TESTING.md)
konkretisieren diese Grenzen. Ein eigener Mac beim Nutzer oder eine eigene
Magnolie-Notes-Begleitapp für das iPhone wird nicht vorausgesetzt.

Die Arbeit ist als nachvollziehbare Vorbereitung gesichert. Main-Übernahme,
Issue-Schließungen und Release-Veröffentlichung sind weiterhin eigene,
in diesem Auftrag nicht ausgeführte Schritte.
