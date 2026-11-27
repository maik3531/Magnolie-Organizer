# #786 – nativer Feldabgleich für macOS-Systemkonten

## Zweck und Umfang

Dieser Patch ergänzt die nativen Provider und den reinen Swift-Core für einen
bewusst freigegebenen Zweiwege-Feldabgleich. Er wird gemeinsam mit dem getrennten
Host-/UI-/Ledger-Patch für #786 übernommen. Ein Providerpatch allein ist keine
freigegebene Synchronisationsoberfläche.

Die erste Einrichtung bindet genau eine native Quelle an das gespeicherte Buch.
Unterstützte native Einträge erhalten neue lokale UUIDs und eine private
Baseline. Spätere Läufe erkennen Änderungen gegenüber dieser Baseline auf beiden
Seiten, übernehmen einseitige Änderungen und behalten echte Konflikte. Die
bekannten Import-/Kopiefelder bleiben passive Herkunft; sie erteilen keine
Schreibberechtigung und werden nicht zum nachträglichen Zuordnen vorhandener
Kopien verwendet. Gleichheit von Namen, Telefonnummern oder E-Mail-Adressen
führt zu keiner Verknüpfung.

**Dies ist keine vollständige Linux-Parität.** Es gibt keine native Neuanlage,
keine native Löschung, keine automatische Übertragung beliebiger lokaler neuer
Einträge und keinen Hintergrunddienst. Die Benutzeroberfläche muss die
nachfolgenden Feldgrenzen sichtbar nennen. Manuelle Abgleiche nutzen die einmal
erteilte native Berechtigung; neue Quellen-/Buchidentitäten benötigen eine neue
Bindung. Widerruf und unverstandene Journalzustände liegen beim Host.

| Quelle | Änderungen in beide Richtungen | Bewusste Grenzen |
| --- | --- | --- |
| EventKit-Kalender | Titel, Klartextnotiz, Ort, Beginn/Ende und Ganztagsdatum für verlustfrei darstellbare Einzeltermine | Keine Serien/Ausnahmen, Teilnehmer/Organisatoren oder Alarme; kein Status-Schreiben. Anzeigezone ist gebunden. Mehrdeutige bzw. nicht existierende explizite Ortszeiten werden zurückgestellt. |
| EventKit-Erinnerungsliste | Titel, Klartextnotiz, Erledigtstatus, unterstützte Start-/Fälligkeitsdaten und drei sichtbare Prioritätsgruppen | Keine Serien oder Alarme; Unteraufgaben, Tags, Anhänge, Zuweisungen, Rich Text und Providerfelder fehlen in der öffentlichen Projektion. Native Priorität wird nur bei einer bewussten lokalen Prioritätsänderung auf 1/5/9 gesetzt; sonst bleibt z. B. 0 erhalten. |
| Contacts-Container | Vorname, Nachname, Firma, Geburtstag sowie Werte bestehender Telefon-/E-Mail-Einträge und Straße/Ort/Region/PLZ bestehender Anschriften | Keine Änderung der Mehrfachwert-Anzahl, Labels oder Länderzuordnung. Native Mehrfachwertkennungen, versteckte Anschriftenteile, ursprüngliche Namensteile und sonstige nicht bearbeitete Felder bleiben erhalten. Formatierter Anzeigename, Fotos und zusätzliche vCard-Felder werden nur eingehend übernommen; lokale Änderungen daran führen zum Konflikt. Das entitlementgeschützte Notizfeld wird nicht angefordert. |

Geburtstage behalten einen ausdrücklich vorhandenen Jahrgang 1604. Jahrfreie
Geburtstage bleiben jahrfrei, auch beim nativen Readback. Die bestehende
`contact-only`-Semantik verhindert automatische Jahrestage. Für E-Mail-Adressen
wird dieselbe ausdrücklich definierte Kleinschreibung wie im etablierten
Kontaktkopiepfad verwendet; die originale Schreibweise bleibt in der privaten
Baseline. Eine unveränderte kleingeschriebene lokale Projektion löst keinen
nativen Write aus.

## Quellen, Fenster und Identitäten

`SystemAccountSync.Source` bindet Art, opaque Source-UID, öffentliche
Konto-/Containerdaten, Schreibvertrag und Anzeigezone in einen SHA-256-Beleg.
Native Eintragskennungen werden mit `OpaqueUTF8Identity` bzw. bytegenau verglichen.
Unicode-kanonische Gleichheit ist keine Identitätsgleichheit. Einträge aus anderen
Kalendern, Listen oder Containern dürfen nicht an die Stelle der freigegebenen
Quelle treten. Kontakte werden weiterhin nicht vereinheitlicht (`unifyResults =
false`); der Writer speichert den frisch gelesenen einzelnen `CNMutableContact`.

Ein Lauf enthält höchstens 100 Einträge einschließlich Ausschlüssen; die
Kalenderabfrage ist auf höchstens 366 verstrichene Tage begrenzt. Der gesamte
Core-Plan einschließlich eingefrorenem Buch ist auf 32 MiB begrenzt. Der Host
muss zusätzlich die Kapazität seines verschlüsselten Journals einschließlich
Readbacks und endgültigem Kandidaten vor Writes prüfen. Ein größeres Quellfenster
oder eine größere Liste wird abgelehnt, nicht abgeschnitten.

Ein kleineres Ereignisfenster ist weiterhin eine beschränkte Beobachtung.
Fehlende, verschobene, ausgeschlossene oder außerhalb des Fensters liegende
gebundene Datensätze erzeugen einen wartenden Konflikt. Sie werden weder gelöscht
noch als neue native Einträge wieder angelegt. Dasselbe gilt für lokale Einträge,
die nicht mehr im aktiven Array stehen, etwa nach Verschieben in den Papierkorb.
Quellen-/Berechtigungsfehler verhindern den Lauf vollständig.

## Transaktionsschnittstelle

Der Core stellt folgende typisierte Bausteine für den Host zur Verfügung:

1. `SystemAccounts.syncSnapshot(sourceUID:start:end:context:displayTimeZone:)`
   liest genau eine Quelle über die bestehende serielle Native-Store-Warteschlange.
2. `SystemAccountSync.prepare(snapshot:currentBook:baseline:context:)` erzeugt
   einen eingefrorenen Kandidaten, einzelne Feldoperationen, Konflikte,
   Ausschlüsse und eine mögliche nächste Baseline. Keine dieser Strukturen ist
   selbst eine Freigabe.
3. Der Host prüft vor einem Write die tatsächliche UI-Normalisierung und schreibt
   einen dauerhaften Intent in sein separates, verschlüsseltes Journal.
4. `SystemAccounts.applySync(operation:source:context:)` liest Quelle und Eintrag
   unmittelbar neu, vergleicht die Revision der tatsächlich serialisierten
   Felder, berechnet den gespeicherten Feldpatch unabhängig erneut und schreibt
   nur die betreffenden Eigenschaften des vorhandenen nativen Objekts.
5. Erst ein neu gelesener Datensatz mit derselben Identität und bestätigten
   Werten ist ein Readback. `Operation.validateReadback` prüft auch die übrigen
   gelesenen Felder. Fremde Änderungen werden nicht still als Erfolg behandelt.
6. `Plan.finalize(readbacks:)` setzt bestätigte Reprojektionen in den Kandidaten
   ein. Der Host prüft erneut die Normalisierung, journalisiert den exakten
   Kandidaten, übernimmt ihn in die UI und bestätigt die Baseline erst mit
   unabhängig gelesenem, tatsächlich gespeichertem Buchinhalt und passendem
   Buch-Epoch. `Finalized.normalizedBaseline(in:source:)` bindet zulässige
   Normalizer-Defaults erst nach erneuter strikter Supersetprüfung. Zurückgestellte
   Konflikt-/Missing-Baselines werden dabei ausdrücklich nicht fortgeschrieben.
   Eine WebView-Save-ACK allein genügt nicht.

`Source`, `Record`, `Baseline`, `Operation` und `Plan` haben versionierte
JSON-Payload-/Decoder-Verträge. Unbekannte Felder, beschädigte Hashes und
mehrdeutige Kennungen werden abgewiesen. Vollständig bestätigte Writes können
nach einem Absturz aus dem Journal finalisiert werden, ohne sie zu wiederholen.
Die Baseline bleibt getrennt von importierbaren Buchdaten.

### Frist und unsicherer Schreibausgang

Eine eigene Deadline-Warteschlange begrenzt die Sync-Fortsetzung auf 20 Sekunden,
auch wenn eine Apple-API synchron blockiert. Das bedeutet **keinen atomaren
Abbruch der Apple-Operation**. Die lokale Sperre der tatsächlichen Source-UID
bleibt bis zum tatsächlichen Ende der nativen Arbeit bestehen. Ein verspätetes
Ergebnis wird nicht nachträglich an die bereits abgeschlossene Fortsetzung
geliefert. Der Host behält das ungeklärte Journal und wiederholt keinen Write.

Nur `RejectedBeforeWrite` beweist, dass der Adapter noch keine native Save-API
aufgerufen hat. Fehler nach Eintritt in `save`/`execute`, eine verlorene Antwort,
ein abweichender Readback oder ein Identitätswechsel sind ungeklärt. Ein natives
`reset()` nach einem Fehler entfernt lediglich eventuell noch ungespeicherte
Store-Änderungen; es ist kein Rollback eines bereits gespeicherten Datensatzes.

Datums-Readbacks dürfen ausschließlich unschädliche zusätzliche
Kalendermetadaten enthalten. Ein nachträglich eingefügtes Jahr bei einem
jahrfreien Geburtstag, eine neu eingefügte `DateComponents.timeZone` bei einem
floating-Datum oder ein neuer Uhrzeitteil bei einem DATE sind keine erlaubten
Defaults. Bewusst geleerte optionale EventKit-Texte dürfen als `nil` zurückkommen.

## Belegte Apple-API-Grenze

Apple bietet hier keine atomare Compare-and-swap-Bedingung. Der frische Vergleich
vor dem Write und der anschließende Readback begrenzen Risiken, schließen eine
gleichzeitige externe Änderung aber nicht atomar aus.

- [EventKit `save(_:span:commit:)`](https://developer.apple.com/documentation/eventkit/ekeventstore/save(_:span:commit:))
  dokumentiert, dass ein inzwischen gelöschtes Ereignis beim Save als neues
  Ereignis wieder angelegt werden kann. Identitätswechsel oder ein verändertes
  Erstellungsdatum dürfen deshalb keinen Baselineabschluss auslösen.
- [Contacts `CNSaveRequest`](https://developer.apple.com/documentation/contacts/cnsaverequest)
  beschreibt bei überlappenden bzw. gleichzeitigen Save-Requests, dass die letzte
  Änderung gewinnt. Ein nicht beobachtbarer Konflikt im Zeitraum zwischen
  Vergleich und Save lässt sich mit diesem öffentlichen API nicht ausschließen.
- [Contacts-Framework](https://developer.apple.com/documentation/contacts)
  beschreibt `mutableCopy()`, `CNSaveRequest.update` und das erneute Lesen nach
  Store-Änderungen. Der vorhandene nicht vereinheitlichte Originalkontakt wird
  geändert; es wird kein Ersatzkontakt aus einer Namenssuche gebaut.
- [CNMutableContact](https://developer.apple.com/documentation/contacts/cnmutablecontact)
  erlaubt nur die Änderung tatsächlich gelesener Eigenschaften. Der Adapter
  prüft die geladenen Keys vor Zugriff und fordert das Notizfeld nicht an.
- [CNLabeledValue.settingValue](https://developer.apple.com/documentation/contacts/cnlabeledvalue/settingvalue(_:))
  erhält Label und Kennung des vorhandenen Mehrfachwerts; diesen Weg verwendet
  der neue Writer statt neuer Werte mit erfundenen Kennungen.
- [EventKit-Änderungsbenachrichtigung](https://developer.apple.com/documentation/eventkit/ekeventstorechangednotification)
  weist auf veraltete Objekte hin und verlangt erneutes Lesen. Gespeicherte
  DTO-Revisionen sind keine vollständigen Provider-ETags.

Diese Grenze muss sowohl im nativen Einrichtungsdialog als auch in der
Codex-Abnahme sichtbar bleiben. Der Patch behauptet keinen atomaren
Nullverlustschutz gegenüber fremden Apps oder Cloud-Servern.

## Prüfnachweis und Codex-Abnahme

Die hier verfügbare Arbeitsumgebung **„Magnolie-Organizer einrichten“** ist Linux
x86_64. Swift, `xcrun`, Apple-SDKs, EventKit, Contacts, AppKit und TCC sind dort
nicht vorhanden. Ein lokaler macOS-Emulator ist nicht nachgewiesen. JSDOM-Tests
prüfen die echte erzeugte Organizer-UI, emulieren aber keinen Mac.

`SystemAccountSyncTests.swift` bereitet 26 reine Swift-Testmethoden mit synthetischen
Quellen vor: stabile Revisionen, alle drei Providerprojektionen,
Erstadoption/Unabhängigkeit früherer Kopien, Updates beider Richtungen,
gleichzeitige gleiche/verschiedene Änderungen, fehlende Datensätze, Quellwechsel,
Unicode-Identitäten, Readback-/Recreate-/Kontakt-Race-Abweisung,
Mehrfachwertidentitäten, Geburtstag 1604/jahrfrei, floating-DST/Schaltjahr,
Sekundenänderungen trotz Minutenanzeige, partielle Zeitänderungen mit unveränderten
Sekunden, UTC-Editorzeilen mit ausdrücklich gebundenen Reminder-Komponenten,
angehängte Aufgabenwurzelränge ohne Veränderung bestehender Kinder,
Journaldecoder und Wiederaufnahme ohne neue Writes. Diese Tests sind hier
**weder kompiliert noch ausgeführt**.

Tatsächlich bestand hier der vorhandene vollständige Projektions-/Importlauf
mit **7/7 Testgruppen in 29,175 Sekunden** (Node 24.22.3 / JSDOM 26.1.0):
Reproduzierbarkeit, Freeze-/Manipulationserkennung, 109 Host-UI-Assertions,
118 Geräte-/Importseitenprüfungen, 327 Kalenderkopieprüfungen,
246 Kontaktkopieprüfungen und 369 Erinnerungskopieprüfungen. Der Lauf verwendet
die echte erzeugte UI und synthetischen nativen Transport. Er prüft bestehende
Wege auf Regression, ersetzt aber keine Ausführung des neuen Swift-Cores.
Der getrennte Host-/UI-Patch enthält den tatsächlichen neuen Transaktionsrunner.

Das vollständige UI-Fixture `system-account-sync-ui.json` ist ausdrücklich
synthetisch aus den bestehenden Kalender-/Kontakt-/Erinnerungskopie-Fixtures
abgeleitet. Es ist kein vorgetäuschter Swift-Output. Der optionale XCTest-Export
`MACOS_BETA_SYSTEM_SYNC_FIXTURE_OUTPUT` erzeugt später aus tatsächlich laufendem
Swift frische vollständige Snapshots für denselben UI-Abgleich.

Für Codex sind nach Übernahme beider #786-Patches folgende Schritte vorgesehen:

1. Den aktuellen Checkout und den ergänzten manuellen macOS-CI-Quellenbeleg
   verwenden; keine alten Desktop-Quellen in den aktuellen Mac-Stand restaurieren.
   `swift test --filter SystemAccountSyncTests` und die neuen Ledger-/Bridge-Tests
   mit dem tatsächlichen Apple-SDK kompilieren und ausführen. Als Umgebung die
   tatsächlich vorhandene CI-/Mac-Ausführung angeben, keine private Hardware
   voraussetzen.
2. Optional `MACOS_BETA_SYSTEM_SYNC_FIXTURE_OUTPUT` auf eine temporäre Datei setzen,
   `testOptionalFreshSwiftFixtureExport` ausführen und die frischen
   `canonicalRecord`-Zeilen durch die echte projizierte UI-Normalisierung schicken.
   Kein erwarteter Wert darf verändert oder entfernt werden; nur gewöhnliche
   zusätzliche Objektdefaults sind zulässig.
3. Für einen echten Providerlauf ausschließlich ausdrücklich eingerichtete
   synthetische Testquellen verwenden. Voraussetzungen sind eine Umgebung mit
   funktionsfähigem EventKit/Contacts/TCC und bewusst erteiltem Zugriff. Eine
   nicht vorhandene Apple-Kontoanmeldung oder nicht verfügbare Testquelle als
   konkrete fehlende Voraussetzung dokumentieren; keine persönlichen Konten
   ersatzweise heranziehen.
4. Je Quelle initial anbinden, extern ein unterstütztes Feld ändern und abgleichen,
   dann lokal ein anderes unterstütztes Feld ändern und erneut abgleichen. Die
   native Änderung muss sichtbar und mit gleichem Identifier zurückgelesen sein;
   ein dritter unveränderter Lauf darf keinen Write erzeugen.
5. Gleiches Feld auf beiden Seiten ändern: beide Werte und die alte Baseline
   bleiben erhalten, der Konflikt ist sichtbar. Ein anderer konfliktfreier
   Datensatz kann im selben Plan weiterlaufen. Ein fehlendes Ereignis außerhalb
   des Fensters darf weder gelöscht noch wieder angelegt werden.
6. Native Quelle verschieben/umbenennen, TCC-Zugriff entziehen, Read-only-Container
   und Identifierwechsel prüfen. Vor-Write-Ablehnung, echte Save-Unsicherheit und
   nachgelagerte Speicherfehler getrennt protokollieren.
7. Mit einem kontrollierten Testadapter Save-Erfolg plus verlorene Antwort,
   Deadline während blockiertem Save, Event-Recreate und Contacts-Race einspeisen.
   Der Write-Intent muss vor Save dauerhaft sein, ungeklärte Ergebnisse müssen
   erhalten bleiben, ein zweiter Write darf nicht beginnen. Nach vollständigen
   Readbacks muss Recovery ohne neue Writes möglich sein. Einen solchen
   kontrollierten Test nicht als Nachweis eines tatsächlich ausgelösten
   Cloud-Race ausgeben.
8. Kontakte: Labels und Mehrfachwertkennungen vor/nach Änderung vergleichen,
   originale Fotos und nicht angefasste Name-/Adressdetails bytegenau behalten,
   1604 und `--02-29` getrennt prüfen. Erinnerungen: DATE/floating/gebundene Zeit,
   DST-Lücke und -Überlappung, erledigt/unerledigt sowie native Priorität 0/1/5/9
   getrennt prüfen. Kalender: Ganztagsende ist exklusiv, Anzeigezone explizit,
   normaler/Schaltjahr-/DST-Fall unverändert korrekt.

## Offene Folgearbeit

Native Create/Delete benötigen eigene explizite Intents, neue Identitätsbelege
und eine Recovery-Strategie für verlorene Erstellungsantworten; die Abwesenheit
eines gelesenen Datensatzes reicht weiterhin nicht. Serien, Teilnehmer, Alarme,
zusätzliche Kontaktwerte/Labels, Bilder, komplexere Reminder-Strukturen und
weitere Providerfelder benötigen eigene verlustfreie Mapper und native Abnahmen.
Ein automatisch laufender Abgleich braucht zusätzlich einen an Widerruf,
Verfügbarkeit und Journalzustand gebundenen Scheduler.

Apple Notes ist kein EventKit-/Contacts-Datentyp. Der vorhandene öffentliche
AppleScript-Anschluss liefert weiterhin ausdrücklich ausgewählte Textkopien.
Dieser Patch greift nicht auf private Datenbanken zu und behauptet keinen
bidirektionalen Rich-Text-/Anhangs-/Ordnerabgleich von Notes. Dafür wären ein
gesonderter belegter öffentlicher Schreibvertrag und eigene Konflikt-/Recovery-
Tests erforderlich.
