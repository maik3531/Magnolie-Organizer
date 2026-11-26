# #786 – nativer Transaktionsanschluss für begrenzte macOS-Feldsynchronisation

## Zweck und Abhängigkeit

Dieser Folgepatch verbindet den Provider-/Planer-Vertrag aus
[macos-786-native-system-sync.md](macos-786-native-system-sync.md) mit der
tatsächlichen gemeinsamen Organizer-Oberfläche und einer dauerhaften nativen
Transaktion. Er setzt den integrierten Providerstand `d57ef304` voraus
(ursprünglicher Providercommit `fdeb6d71`, Basis `9f35d4d0`). Er benennt keine
Kopie in Synchronisation um und aktiviert keine allgemeine DAV-, Telefon- oder
Magnolie-Notes-Brücke.

Hier stehen **Linux x86_64, Python und Node/JSDOM** zur Verfügung. Swift, xcrun,
EventKit, Contacts, AppKit und WKWebView sind nicht vorhanden. Die neuen
Swift-Tests sind vorbereitet, hier weder kompiliert noch ausgeführt. Eine
spätere passende macOS-VM/CI-Umgebung genügt für native Prüfungen; physische
Mac-Hardware ist keine Voraussetzung dieses Vertrags. Ein CI-Workflow ist
noch kein bestandener nativer Nachweis.

## Tatsächlicher Ablauf

1. Die neue Sektion unter System-Internetkonten wählt genau eine native Quelle.
   Kontakte behalten die vorhandene `readOnly`-Discoveryaussage; die getrennte
   `systemSyncFields`-Fähigkeit beschreibt nur den neuen begrenzten Adapter.
   Die Oberfläche erklärt Erstadoption, Feldumfang, nicht unterstützte
   Neuanlagen/Löschungen/Serien und die fehlende atomare Apple-CAS-Garantie.
2. Der vorhandene Entwurfs-/Navigationsguard wird vollständig beendet. Vor dem
   Dispatch muss das aktuelle Buch dauerhaft gespeichert sein. Doppelte
   Starts, neue Entwürfe während des Save-ACK und laufender Restore werden
   abgefangen. Ein Kontoentwurf bleibt erhalten.
3. `macos_system_sync` erhält Quelle, Art, Aktion, Kalenderfenster, Anzeigezone
   und `requestId`. Buchdaten, Freigaben oder Baselines kommen nicht aus
   diesem Request. `DAVBookDiskSnapshot.read` liest die tatsächliche native
   Datei mit bestehender Speicherlease, Datei-/Verzeichnisbarrieren und
   gegebenenfalls authentifizierter Entschlüsselung. Die UI muss genau dieses
   Buch wiedererkennen.
4. Der native Dialog erteilt einmal eine Freigabe für Quelle/Fingerprint,
   gespeicherten `syncEpoch`, Zeitfenster und Anzeigezone. Importherkunft,
   gleichnamige Kontakte, kopierte Provider-IDs oder JSON-Flags erteilen
   keinerlei Freigabe. Die Freigabe liegt ausschließlich im verschlüsselten
   nativen Ledger. Widerruf entfernt die Berechtigung; belegte private
   Zuordnungen bleiben für eine ausdrücklich erneut genehmigte gleiche
   Quellenbindung erhalten, damit Reaktivierung keine Kopien erzeugen muss.
5. Der reine Planer liefert Kandidat und eingefrorene Feldoperationen.
   Vor dem ersten Providerwrite prüft die wirkliche UI einen abgetrennten
   Normalizerlauf. Nur neue/geänderte Zeilen werden daraus übernommen;
   unveränderte Zeilen, andere Bereiche und die vorhandene Aufgabenreihenfolge
   bleiben exakt erhalten. Ein nativer Supersetbeweis weist geänderte oder
   verlorene geplante Werte zurück; zusätzliche normale Objektdefaults sind
   zulässig.
6. `SystemAccountSyncLedger` reserviert dauerhaft Platz für alle zukünftigen
   Readbacks, den normalisierten Kandidaten und die nächste Baseline. Die
   Berechnung berücksichtigt JSON-/Base64-Mehrbedarf und andere behaltene
   Läufe. Ohne passende Reservierung darf `willApply` keinen Write beginnen.
   Jedes begonnene Write wird **vor** dem nativen Aufruf gespeichert; nur ein
   tatsächlicher, quell- und feldgeprüfter Readback wird quittiert.
7. Nach den Providerantworten wird der endgültige Kandidat erneut in der UI
   geprüft und exakt im Ledger vorgemerkt. `normalizedBaseline` bindet
   ausschließlich konfliktfreie Baselineeinträge an die tatsächlich
   normalisierten lokalen Felder. Zurückgestellte Konflikte behalten ihre
   alte Baseline und verschwinden nicht durch einen Defaultwert.
8. Die UI übernimmt den Kandidaten und wartet auf Save-ACK. Der Save-Callback
   wird vor dem Renderer registriert; ein Rendererfehler behauptet keinen
   Rollback. Die native Schreibsperre erlaubt währenddessen nur den exakt
   vorgemerkten Buchkandidaten. Erst ein unabhängiger erneuter Diskabruf mit
   passendem Epoch und vollständigem Kandidateninhalt bestätigt den Abschluss.
   Danach wird die Baseline atomar fortgeschrieben und der passende Lauf
   entfernt. Eine verlorene UI-Quittung kann anhand des tatsächlich bereits
   gespeicherten Kandidaten beendet werden, ohne Providerwrites zu wiederholen.

Der Host sperrt parallele Mutationen und Beenden während der Transaktion.
Dateiimporte aus #785 müssen diese Sperre in beiden Richtungen beachten:
`dispatch` blockiert neue Importstarts; `startSystemSync` darf nicht starten,
während `fileImport.active` ist. Die Integration enthält diese Gegenprüfung.

## Fehler- und Wiederaufnahmegrenzen

Das eigene Ledger verwendet einen privaten `AtomicStore`-Unterordner und einen
separaten Keychain-Schlüssel für AES-GCM. Es verwendet nicht die noch ohne
produktiven Abschlussprüfer bestehende DAV-Journal-Retirement-API. Fehlendes
Journal bei vorhandenem Schlüssel wird nicht zu leerem Zustand umgedeutet.
Das Ledger verwaltet keine Providerkennwörter; seine Buch-, Baseline- und
Journalpayloads bleiben verschlüsselt. Ein manuell zurückgespielter älterer gültiger Journalstand über
Prozessstarts hinweg hat keinen zusätzlichen Hardware-/Keychain-Zähler gegen
Rollback; normale Buchwiederherstellung erhält eine neue native Epoch.

Nachweislich wirkungslose Läufe dürfen entfernt werden: kein gestagter
Kandidat, kein ACK und entweder gar kein begonnener Write oder ausschließlich
typisierte Ablehnungen **vor** dem nativen Save. Unsichere Versuche,
Teil-ACKs und gestagte Kandidaten bleiben erhalten. Bei einem ungewissen
Write oder Teil-ACK mit späterer Ablehnung fehlt in dieser Fassung weiterhin
eine geführte manuelle Recovery-Oberfläche. Codex darf das Journal nicht
löschen oder einen unbedingten Retry ergänzen; zuerst müssen die tatsächlichen
nativen IDs/Felder erneut gelesen und gegen die eingefrorenen Belege geprüft
werden.

Die Quellenliste muss eine Quelle noch anzeigen können, um ihre Freigabe über
den neuen UI-Knopf zu entfernen. Eine Verwaltung aller gespeicherten Freigaben
auch bei entzogener TCC-Berechtigung/verschwundener Quelle bleibt ein konkreter
UI-Folgeschritt; die native `revokeSource`-Operation benötigt keinen Providerabruf.

Der Umfang bleibt manuell gestartet: unterstützte native Einträge werden
zuerst neu gebunden, danach unterstützte Feldänderungen abgeglichen. Es gibt
keinen Export beliebiger neuer lokaler Einträge, keine native Anlage/Löschung,
keine implizite Adoption vorhandener Kopien, keine Behandlung bloßer Abwesenheit
als Löschbeweis und keinen periodischen Scheduler. Apple Notes bleiben beim
getrennten Textkopiepfad. Eine zusätzliche Magnolie-Notes-App wird nicht benötigt.
KDE Connect bleibt ein eigenständiger zulässiger Geräte-/Dateiweg.

## Tatsächlich ausgeführte UI-Prüfung

`ProjectionTests.test_system_account_sync_transaction` arbeitet mit der
wirklich erzeugten gemeinsamen UI, öffentlichem Rendererhook und dem echten
Speicher-/Editorzustand. Der aktuelle Lauf enthält **107 Checks** in EN/DE:
Quellenkontrollen, keine Rechte durch Discovery, Save vor Dispatch, Doppelstart,
falscher/staler Buchbeleg, Kandidatenprobe, Save-ACK/NACK, verlorener ACK/Retry,
Rendererfehler, späte und vorbestehende Entwürfe, Restore, konkurrierende lokale
Änderungen, unveränderte fremde Bereiche und Kopierstarter während Sync.
Die gemeinsame Dreierfixture aus dem Providerpatch umfasst Termine, Kontakte
und Erinnerungen einschließlich Herkunft, jahrfreiem Schaltgeburtstag und
vorhandener Aufgabenreihenfolge. Ihre Herkunft ist ausdrücklich synthetisch
und manuell aus den bereits geprüften Kopiefixtures abgeleitet, nicht durch
Swift-Ausführung erzeugt. Die native Transport-/Diskantwort wird simuliert.

Die unabhängige Quellprüfung führte zusätzlich zu konkreten Korrekturen:
Kapazität vor Writes reservieren; sichere Nullwirkungsläufe freigeben; Baseline
erst an normalisierten, dauerhaft belegten Feldern fortschreiben. Die
bestehenden Import-/Host-/Reproduzierbarkeitsgruppen werden im finalen
Issue-Nachweis mit ihren einzelnen Ergebnissen aufgeführt, nicht als neue
Apple-API-Prüfungen oder als eine addierte Assertionzahl.

## Konkrete native Abnahme für Codex

In einer geeigneten macOS-VM/CI mit passendem Xcode zunächst den integrierten
Quellstand samt SHA sichern, vorhandenen dokumentierten UI-/Runtime-Bauablauf
verwenden und die getrennten Produkt-/Testgrenzen beibehalten:

```sh
swift build --product 'Magnolie Organizer macOS Beta'
swift test --filter SystemAccountSync
```

Die Providergruppe enthält 26 vorbereitete Methoden, die Ledgergruppe 10.
Das sind vorbereitete Prüfungen, keine hier ausgeführten Ergebnisse. Die
Ledgergruppe muss tatsächliche temporäre private Stores prüfen: Klartext und
verschlüsseltes Buch, unabhängiger Diskabruf, falscher Kandidat/Epoch,
verlustfreie Defaultprüfung, NFC/NFD-Unterscheidung, fehlender Schlüssel/
fehlendes Journal, Kapazität **vor** Write, ungewisser Neustart, Revoke sowie
Nullwirkungsabbruch. Die Coregruppe prüft zusätzlich Plan-/Quellen-/Feldverträge,
Richtungen, Konflikte, Datumsdarstellungen und Quellenänderungen.

Danach die tatsächlich aus Swift exportierte Fixture mit
`MACOS_BETA_SYSTEM_SYNC_FIXTURE_OUTPUT` erzeugen und als
`MACOS_BETA_SYSTEM_SYNC_UI_FIXTURE` dem neuen JSDOM-Runner geben. Diese zweite
Runde soll die bisher synthetische Quelle ersetzen und denselben Inhalt über
Core → echte UI → gespeichertes JSON beweisen. Der Providervertrag benennt den
zugehörigen XCTest-Export. Kein vorhandenes synthetisches JSON als bereits
native erzeugte Ausgabe etikettieren.

Für die echten Frameworkadapter eine angemeldete grafische macOS-Sitzung mit
temporärem App-Profil und ausschließlich eigens angelegten Testdaten verwenden:

| Prüfung | Voraussetzungen | Erwartetes Ergebnis |
| --- | --- | --- |
| TCC verweigert, dann ausdrücklich erlaubt | Gebautes App-Bundle mit UsageDescriptions; echte grafische Sitzung | Keine Providerwrites bei Ablehnung; getrennte native Sync-Freigabe nach Zugriff weiterhin nötig |
| Erste Runde je Kalender/Kontakte/Erinnerungen | Tatsächlich verfügbarer lokaler beschreibbarer Kalender, Kontaktecontainer bzw. Erinnerungsliste, höchstens 100 Einträge | Lokale neue IDs, unveränderte native IDs/Anzahl; keine Fernanlage oder Löschung; durable Baseline erst nach Diskbeleg |
| Organizer → native App | Bereits bestätigte Baseline; je ein unterstütztes Feld ändern | Genau eine Änderung am gebundenen bestehenden nativen Objekt; unveränderte Felder/Identität im Readback |
| Native App → Organizer | Native Änderung nach bestätigter Baseline | Derselbe lokale Datensatz wird aktualisiert; keine zusätzliche Kopie, keine fremde Bereichsänderung |
| Gleichzeitige Änderungen | Dasselbe Feld beidseitig verschieden ändern | Konflikt bleibt erhalten, kein Last-write-wins; derselbe Konflikt bleibt beim Folgelauf bestehen |
| Verlorener Save-ACK | Kandidat tatsächlich speichern, Frontendantwort gezielt unterdrücken | Neustart/erneuter Start bestätigt tatsächliche Datei und beendet Journal ohne erneuten Providerwrite |
| Absturz an Writegrenze | Kontrollierter synthetischer Adapter/Prozessprüfer vor/nach Save; keine echten persönlichen Konten | In-flight ohne beweiskräftige Antwort bleibt ungewiss; kein automatischer Retry, keine vorgezogene Baseline |
| Speicher-/Kapazitätsfehler | Gezielt erschöpfte reservierte Kapazität bzw. fehlschlagende private Datei | Kapazitätsfehler vor erstem Write; Savefehler lässt Kandidat/Journal sichtbar bestehen |
| Konkurrenz/Beenden | Dateiimport aktiv oder System-Sync aktiv; Schließen/Restore versuchen | Kein paralleler Import-/Syncstart; native Mutation/Schließen bleibt bis zum eindeutigen Abschluss gesperrt |
| Apple-Racegrenze | Zweite App verändert/löscht dasselbe Objekt zwischen Vergleich und Save | Reale Grenze dokumentieren: keine atomare CAS-Zusage. Identitätswechsel/abweichender Readback bleiben ungewiss; kein blinder Retry |

Eine leere Cloud-VM muss weder einen nutzbaren lokalen EKSource noch einen
beschreibbaren Kontaktecontainer, iCloud, Netzwerkfreigaben oder bereits
erteiltes TCC besitzen. Fehlende Voraussetzungen als **nicht ausgeführt** mit
konkretem Grund erfassen. Die synthetischen Core-/WebKit-Prüfungen können ohne
persönliche Apple-Konten laufen; tatsächliche Konten/Gegenstellen und der
separate Apple-Notes-Automationspfad benötigen jeweils ihre eigenen verfügbaren
Voraussetzungen und Belege.
