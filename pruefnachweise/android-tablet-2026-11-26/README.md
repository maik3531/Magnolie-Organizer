# Android-Tablet: Prüfnachweise vom 26. November 2026

Diese Textbelege gehören zum aktuellen Tablet-Quellstand und insbesondere zu
[#121](https://github.com/maik3531/Magnolie-Organizer/issues/121),
[#791](https://github.com/maik3531/Magnolie-Organizer/issues/791) und
[#682](https://github.com/maik3531/Magnolie-Organizer/issues/682).
**Hostprüfungen und Quellkompilierung sind bestanden. Eine native
Android-Abnahme oder Veröffentlichung wird damit nicht bestätigt.**

## Exakte geprüfte Quelle

| Bindung | Wert |
| --- | --- |
| Lokaler Quellcommit | `f64efcb2cf056107468a77d6597762d0706c68c9` |
| Git-Baum dieses Quellcommits | `0cd7dd930922933cf40444251f65d1ec1c7a0009` |
| Projektionshash | `7e12da62e214e085154204b0dc8fd5f49c09c087af71d66c534d47133ea662eb` |
| Eingabemengen-Hash | `5d14eac1de81a6cddd7514fd73765422a902f050a5444a85a80af203da6156c1` |
| Projektions-Eingabedateien | 455 |

[source-projection-summary.json](source-projection-summary.json) übernimmt die
skalaren Angaben und Hashes aus dem tatsächlich geprüften
`artifacts/source-projection.json`; die umfangreiche vollständige Eingabeliste
wird hier nicht dupliziert. Die lokalen Commit-IDs bleiben als Herkunftsbeleg
erhalten. Die Zuordnung zum veröffentlichten GitHub-Commit wird im zugehörigen
Issue dokumentiert; Quellbaum und Dateihashes ermöglichen den inhaltlichen
Vergleich unabhängig von Commit-Metadaten.

## Ergebnisse und Grenzen

| Lauf | Bestandener Umfang | Beleg |
| --- | --- | --- |
| Import-/Anhangsintegration | 31 Prüfungen, Exit 0 | [system-import.log](frontend/system-import.log) |
| Bestehende Tablet-Webprüfung | 194 Prüfungen, Exit 0 | [web.log](frontend/web.log) |
| Browserlayout | 150 von 150 Prüfungen in 10 Fällen, Exit 0 | [layout.log](frontend/layout.log), [vollständiges Ergebnis](frontend/layout-results.json) |
| JVM-Regeln | 31 Tests, keine Fehler oder Skips | [jvm-results.log](native/jvm-results.log), [Aufruf und Ausgabe](native/junit.log) |
| Produktkompilierung | Alle 38 Kotlin-Produktdateien erfolgreich | [product-kotlin.log](native/product-kotlin.log) |
| Ressourcen | Tatsächliche XML-Ressourcen kompiliert und gelinkt; daraus `R.java` erzeugt und kompiliert | `native/resource-*.log` |

[verification-summary.json](verification-summary.json) ordnet diese Läufe dem
Quellcommit zu. Der eigenständige native Kompilierungslauf fand vor dessen
Commit-Erstellung statt. Deshalb wurden seine **38 Quellhashes, sieben
Testeingaben und 22 Ressourceneingaben** zusätzlich mit den Dateien dieses
committeten Standes verglichen: jeweils keine Abweichung.

Die Frontend-Läufe verwenden die tatsächlich erzeugte Oberfläche mit
synthetischen Provider- und Speichergegenstellen. Sie prüfen unter anderem
konservative lokale Kopien, Quellen- und Fensterbindung, erhaltene bestehende
Einträge, Geburtstagsableitung einschließlich Konfliktfällen, Speicherung und
Wiederöffnen, Heimatland-Telefonnummern, ein 23-Stunden-Zeitfenster bei
Sommerzeitwechsel, erhaltene UTC-Zeitpunkte, alte Antworten, fehlgeschlagene
Speicherquittungen und bewusst ausgelöste HTTPS-Anhangsaktionen.

Der Layoutlauf verwendet **Chromium 156.0.8078.108** auf dem Host. Er belegt die
protokollierten Geometrie- und Bedienoberflächenprüfungen in diesem Browser.
Er belegt weder eine Android-WebView noch physische Touch-/Stifteingabe,
TalkBack oder eine Android-Tastatur.

Die 31 JVM-Tests bestehen aus 17 Importregeltests, sechs bestehenden
Systemquellen-Vertragstests und acht Anhangsregeltests. Die Datumsfälle trennen
Ganztage von Uhrzeit-Terminen: Ganztage werden nach expliziten ausgewählten
Kalendertagen gefiltert, Uhrzeit-Termine nach Zeitpunkten. Berliner Vorabend,
westlicher Tagesrand, mehrtägige Spannen und exklusive Enden sind abgedeckt.

Der Import erzeugt eine **lokale Kopie**, keinen vollständigen Providerabgleich.
Er aktiviert keine Schreib-, Lösch- oder Synchronisierungsrechte. Eine
Magnolie-Notes-Installation oder KDE-Connect-Verbindung ist nicht erforderlich.
Lokale Erinnerungen folgen den bestehenden Organizer-Einstellungen.

## Native Kompilierung reproduzieren

[verify-tablet-native.py](verify-tablet-native.py) ist das tatsächlich ausgeführte
Reproduktionsskript. Seine SHA-256 lautet
`dd804c94d3e41aa5377bb0b66ab38c4acd5e6eadde22867194acd4c949f56f03`.
**Es ist ein Historien- und Prüfbarkeitsbeleg; es ersetzt keine vorhandenen
Bau-, Ressourcen-, Abhängigkeits-, Paket- oder Freigabegates des Projekts.**

Verwendet wurden Kotlin **2.4.21**, OpenJDK **21.0.13.1**, JVM-Ziel **17**,
JUnit **4.13.2**, das offizielle Android-API-JAR **37.2**, Google **aapt2 36**
und die in [dependencies](dependencies) exakt bezeichneten echten Artefakte.
Die Ressourcenprüfung verwendet `minSdk=26`, `targetSdk=35`. Sie behauptet
keine erfolgte Ziel-SDK-Migration. Das Host-JDK enthält den Java-Compiler als
Modul, aber keine `ct.sym`-Daten für `--release 17`; die generierten
R-Konstanten wurden mit `-source 17 -target 17` kompiliert. Die entsprechende
Optionswarnung und bestehende Kotlin-Warnungen stehen unverändert in den Logs.

Nach Erzeugung der aktuellen Webprojektion mit dem vorhandenen Projektwerkzeug
und Bereitstellung der exakt bezeichneten Abhängigkeiten kann das Skript vom
Repository-Stamm aus so ausgeführt werden:

```sh
python3 pruefnachweise/android-tablet-2026-11-26/verify-tablet-native.py \
  --repository . \
  --dependencies /pfad/zu/tablet-build-dependencies \
  --output /tmp/tablet-native-verification
```

Der Abhängigkeitspfad ist an die eigene Umgebung anzupassen. Die vier
Herkunftsmanifeste aus `dependencies` gehören zusammen mit den dort
bezeichneten Dateien in dieses Verzeichnis. Das Skript prüft deren SHA-256,
führt keine Downloads oder Installationen aus und verwendet kein Gerät.
Es protokolliert einzelne Befehle und prüft, dass Quellen, Tests und Ressourcen
während der Kompilierung unverändert bleiben.

[native/receipt.json](native/receipt.json) enthält die vollständigen geprüften
Dateihashes, Abhängigkeitshashes und die Herkunft des ursprünglichen Laufs.
Absolute Arbeitsverzeichnisse in Receipt und Rohprotokollen kennzeichnen diese
Herkunft; sie sind keine zusätzlichen Entwicklungsquellen. Enthalten sind
ausschließlich Textbelege, keine JARs, Bilder, Pakete oder Signierschlüssel.

## Noch erforderliche native Abnahme

1. Regulären vollständigen APK-Bau einschließlich aller vorhandenen Gates
   durchführen und Paket-/Quellhash binden.
2. Auf Android synthetische Konten und Kalender prüfen: tatsächliche
   Berechtigungsdialoge, Ablehnung und Widerruf, Quellenisolation, veränderte
   Providerdaten, Zeitlimit und hohe Mengen. Kein Teilbestand darf gespeichert
   werden.
3. Rotation, Hintergrundwechsel, Renderer-/Prozessneustart sowie verschlüsseltes
   Speichern und Wiederöffnen mit echten Android-Komponenten prüfen.
4. Native Ganztags-, Zeitzonen- und Serieninstanzenabnahme sowie Erinnerungen
   gemäß den gesetzten Organizer-Einstellungen durchführen.
5. HTTPS-Anhänge ausdrücklich öffnen, fehlende oder ablehnende Android-Handler
   prüfen und zum unveränderten Buch zurückkehren. `localOnly` und ungespeicherte
   Anhänge müssen gesperrt bleiben. Zwischenablage getrennt nativ prüfen.
6. Physische Tabletbedienung, Android-WebView, Bildschirmtastatur, TalkBack und
   gegebenenfalls Stift separat abnehmen.

**Kein vollständiger Gradle-/D8-/APK-Nachweis, keine Signierung, keine
Installation, kein Gerätetest und keine Releasefreigabe sind Bestandteil
dieser Belege.** Die bei der Ressourcenprüfung intern erzeugte
`resources-only.ap_` enthält keinen ausführbaren App-Code und ist hier nicht
beigefügt. [SHA256SUMS](SHA256SUMS) bindet alle beigefügten Textdateien.

## Nachfolgende Belegsicherung

Die Belegsicherung entfernt zusätzlich genau eine überzählige Schlussleerzeile
in jedem der beiden neuen Provenienz-Pythondateien. Der ausführbare Code bleibt
identisch. Die vier eigentlichen Patches wurden nacheinander mit `git apply
--cached --check` gegen die dokumentierte Basis geprüft; ihr resultierender
Git-Baum ist exakt der lokal geprüfte und auf GitHub veröffentlichte Produktbaum.
Der fünfte Patch enthält diese Belege und die reine Leerzeilenbereinigung.
