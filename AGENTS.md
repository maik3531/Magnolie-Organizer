# Verbindlicher Arbeitsablauf

## Eine Produktquelle

Dieses Repository ist die maßgebliche Produktquelle. Änderungen an Organizer,
Notes und Handbuch werden ausschließlich hier vorgenommen. Temporäre Baukopien,
entpackte Pakete und Test-VMs sind keine zusätzlichen Entwicklungsstände.
Ein dort gefundener Fehler wird in der zugehörigen Quelle dieses Repositorys
behoben.

Geprüfte macOS- und Tablet-Quellenstände in `main` aktuell halten, damit Codex
im Terminal dort unmittelbar weiterarbeiten kann. Ein offener Pull Request
ersetzt diese Quellübernahme nicht. Arbeitszweige dürfen zur Vorbereitung dienen;
ihre geprüften Änderungen anschließend mit dem aktuellen `main` zusammenführen
und zwischenzeitliche Änderungen erhalten. Quellübernahme und Freigabe der
installierbaren Pakete getrennt behandeln; offene native Abnahmen bleiben offen.

Zur Mac-/Tablet-Portierung gehört auch die nutzbare iPhone-Anbindung über
vorhandene Apps, insbesondere KDE Connect. Eine eigene Notes-App für das
iPhone wird nicht umgesetzt. Die Notizfunktionen im Organizer bleiben im
Prüfumfang. Unterstützte iPhone-Funktionen anhand der tatsächlichen
Gegenstellenfähigkeiten integrieren und prüfen; fehlende eigene iOS-Notes
schließen die übrige iPhone-Anbindung nicht aus.

Die dauerhaften Quellordner heißen `magnolie-organizer`,
`magnolie-organizer-windows`, `magnolie-notes` und `magnolie-handbuch`. Sie erhalten bei einem Release
keine neue Versionsnummer im Verzeichnisnamen. Versionsnummern bleiben in den
Programmdaten, Tags und Downloadpaketen.

## Jede Änderung gehört zu einem GitHub-Issue

## Wiederholbare Veröffentlichungen

Für Veröffentlichungen den vorhandenen dokumentierten Bauablauf wiederverwenden.
Keine neuen Bauverzeichnisse, Werkzeugvarianten oder Wechsel zwischen Host,
Container und VM auf Verdacht einführen. Vorhandene Werkzeuge, Abhängigkeiten
und geeignete bereits geprüfte Ergebnisse verwenden. Eine notwendige Abweichung
auf einen konkreten Fehler begrenzen und im privaten Betriebsprotokoll festhalten.
Interne Befehle, Signierkonfiguration und Freigabenachweise werden dort gepflegt,
nicht in öffentlichen Release-Hinweisen. Der lokale Ablauf ist in
`.private-testing/RELEASE-VERFAHREN.md` festgehalten.

## Issue-Bearbeitung

1. Vor einer Änderung ein vorhandenes Issue zuordnen oder ein neues anlegen.
   Ziel, betroffene Komponenten und überprüfbare Abschlusskriterien festhalten.
2. Eine Aufgabe nach der anderen abschließen. Neue Befunde als eigene Issues
   erfassen; den Umfang der aktiven Aufgabe nicht stillschweigend erweitern.
3. Nur die zugehörige Änderung umsetzen und passend dazu prüfen. Bereits
   bestandene Prüfungen nur bei geänderten Eingaben oder einem konkreten neuen
   Befund wiederholen.
4. Den geprüften Stand mit Issue-Verweis committen und auf GitHub sichern.
   `Refs #N` kennzeichnet Zwischenstände. Umgesetzte und passend geprüfte Issues
   schließen, statt sie allein wegen ausstehender Rückmeldungen offen zu halten.
   Bei teilweise abgearbeiteten Issues den erledigten Umfang dokumentieren,
   den konkreten Rest in ein neues Issue übernehmen und beide gegenseitig
   verlinken; anschließend das alte Issue schließen und im Nachfolge-Issue
   weiterarbeiten. Den offenen Rest nicht als behoben darstellen. Wiederkehrende
   Fehler durch Wiederöffnen oder einen verknüpften neuen Befund verfolgen.
5. Im Issue knapp festhalten, was umgesetzt wurde, was tatsächlich geprüft wurde
   und was noch fehlt. Eine Quellstandsicherung ist keine Veröffentlichung.

## Befunde zuerst bestätigen

Ein Nutzerbericht ist noch kein Nachweis für einen Programmfehler. Vor einem Fix
Paketformat, Version, System, Einstellungen, Installationsvoraussetzungen und
konkrete Schritte prüfen. Reproduzierten Programmfehler, Konfigurations- oder
Bedienungsursache und weiterhin unbestätigten Befund im Issue auseinanderhalten.
Nutzern keine Ursache unterstellen, die nicht überprüft wurde.

Bei allen künftigen Tests und Fehlerkorrekturen prüfen, ob ein Befund auch andere
Editionen oder Plattformen betreffen kann, insbesondere Linux und Windows.
Solche gemeinsamen oder möglicherweise übertragbaren Befunde als eigenes Issue
erfassen; Reproduktion, betroffene Quell-/Paketstände und nachgewiesene Auswirkungen
von noch ungeprüften Verdachtsfällen klar trennen. Vorhandene Issues zuvor auf
Dopplungen prüfen. Einen vorhandenen Fix oder übertragbaren Korrekturansatz direkt
im Issue mit konkretem Patch bzw. Quellverweis, erforderlichen Anpassungen und
Prüfstand dokumentieren. Auch bei späteren Fixes diese Hinweise im Issue ergänzen;
eine Mac-/Tablet-Korrektur nicht als bereits geprüften Linux-/Windows-Fix ausgeben.
Diese Regel gilt dauerhaft, nicht nur für die aktuell bearbeitete Portierung.

## Aktuelle Abhängigkeiten und gezielte Rückfallwege

Grundsätzlich die aktuellste unterstützte, funktionierende Version einer
Abhängigkeit verwenden. Eine ältere Version nur als gezielten Fallback vorsehen,
wenn die neuere in der konkreten Distribution oder Umgebung nachweislich nicht
funktioniert. Ein einzelner Kompatibilitätsfall rechtfertigt keine allgemeine
Bindung aller Distributionen an eine alte Version. Das gilt insbesondere auch
für WebKit, Java sowie Python/Pillow (`python3-pil`) beim Handbuch. Der gemeldete
Handbuch-2.0.30-Installationsfall auf Mate 21.3 ist gezielt zu prüfen: Unterstützung
der dort vorhandenen älteren Pillow-Version darf aktuelle Versionen auf anderen
Systemen nicht ausschließen oder einen pauschalen Downgrade erzwingen. Mindest-
und Versionsgrenzen nur aus tatsächlich benötigten und geprüften Funktionen
ableiten, nicht ohne Nachweis anheben oder auf eine alte Version festschreiben.

Dasselbe gilt für Geräte-APIs, insbesondere Notes/Android in #558: aktuelles
unterstütztes `compileSdk`/`targetSdk` und aktuelle APIs bevorzugen, ältere Geräte
über geprüfte API-Level-/Fähigkeitsabfragen und gezielte Rückfallwege unterstützen.
`minSdk` getrennt vom Ziel-SDK behandeln und nur bei eigenständig belegter
technischer Notwendigkeit anheben; ein modernes Ziel-SDK ist allein kein Grund,
die bisher unterstützten älteren Geräte auszuschließen. Kein pauschaler alter
API-Pfad für alle Geräte. Bestehende Geräte-/Build-/Store-Pausen bleiben wirksam.

Optionale Systemdienste oder Werkzeuge nur bei tatsächlicher Verfügbarkeit
voraussetzen; andernfalls einen geeigneten geprüften Rückfallweg verwenden.
Beispielsweise darf NetworkManager nicht vorausgesetzt werden, wenn dieselbe
Funktion unabhängig vom verwendeten Netzwerkdienst sicher umgesetzt werden kann.
Rückfallbedingungen, betroffene Umgebungen und Prüfnachweise konkret festhalten;
keine unbemerkten automatischen Downgrades, Installationen oder Erweiterungen
bestehender Freigaben daraus ableiten.

## Native Startprüfung vor jeder Veröffentlichung

Jedes installierbare Release-Paket in einer passenden vorhandenen VM bzw. nativ
unter Windows installieren, starten und bedienen. Ansichtswechsel, längere
Hänger sowie Start-, Dienst- und Absturzmeldungen prüfen. Jedes neue AppImage
ausdrücklich auch unter Arch starten. Paketstand/Prüfsumme, Umgebung und Ergebnis
im privaten Freigabenachweis erfassen. Fehlende oder fehlgeschlagene notwendige
Startprüfungen blockieren die Veröffentlichung.

Bestehende Benutzeränderungen erhalten. Nur beabsichtigte Quelldateien aufnehmen;
keine persönlichen Daten, Zugangsdaten, Signierschlüssel, privaten Nachweise oder
erzeugten Pakete committen. Interne Veröffentlichungsunterlagen bleiben privat.

Der zusammengeführte offene Arbeitsstand für 2.0.19 / Notes 1.0.15 wird in
[Issue #4](https://github.com/maik3531/Magnolie-Organizer/issues/4) verfolgt.
