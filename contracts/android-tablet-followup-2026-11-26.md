# Android-Tablet: Folgekorrekturen vom 26. November 2026

Ausgangspunkt ist der veröffentlichte Stand von [PR #795](https://github.com/maik3531/Magnolie-Organizer/pull/795),
Commit `29acde7e3df2b8bcaaab0cc19b3377b8dbf4bd14`. Der erste
[Issue-Audit](android-tablet-audit-2026-11-26.md) bleibt als Verlauf erhalten.
Zu dessen 26 maßgeblichen Issues kommen vier reproduzierte UI-/Herkunftsfehler
und zwei im echten CI-Bau bestätigte Prüfcodefehler (#804/#805) sowie der
native Serienfixture-Befund #807 hinzu: insgesamt 33 zugeordnete Issues.
Die Änderungen werden weiterhin als überprüfbare Patchserie bereitgestellt.

## Änderungen und Zuordnung

| Issue | Belegter Fehler | Korrektur und Grenze |
| --- | --- | --- |
| [#798](https://github.com/maik3531/Magnolie-Organizer/issues/798) | Ein Neuzeichnen des Importabschnitts entfernte das fokussierte Steuerelement; der Tastaturfokus landete außerhalb des Dialogs. | Fokus innerhalb des betroffenen Abschnitts an der passenden Aktion bzw. einem beschrifteten Statusanker wiederherstellen; externen Fokus nicht übernehmen. Chromium-Beleg, native IME-/TalkBack-Abnahme offen. |
| [#799](https://github.com/maik3531/Magnolie-Organizer/issues/799) | Neue lokale Kontaktzeilennummer trotz gleicher Providerherkunft erzeugte eine zweite Importidentität. | SOURCE_ID, ersatzweise BACKUP_ID verwenden; erst danach geräte-/nutzergebundene lokale Kennung. Vor-/Nach-Snapshots prüfen auch Herkunftskennungen. |
| [#800](https://github.com/maik3531/Magnolie-Organizer/issues/800) | Verschieben eines Einzeltermins änderte durch BEGIN dessen Importidentität. | Einzeltermine nach Event-ID; Serieninstanzen nach ursprünglichem Slot; Ausnahmen nach ORIGINAL_ID und ORIGINAL_INSTANCE_TIME. Geräte-/Nutzerscope einbeziehen. |
| [#801](https://github.com/maik3531/Magnolie-Organizer/issues/801) | Die korrekte Konfliktmeldung lag außerhalb des offenen Einstellungsdialogs und wurde verdeckt. | Systemimportmeldungen im zugehörigen Dialogabschnitt anzeigen; die echte Browserprüfung muss ihre Sichtbarkeit und Erreichbarkeit belegen. |
| [#790](https://github.com/maik3531/Magnolie-Organizer/issues/790) | Der vollständige APK-Bau war nicht unabhängig von der nativen Emulatorabnahme ausführbar. | Explizites Workflowziel `tablet-build-only`: gleicher vollständiger Build-/Quellbindungsweg, keine Emulatorvorbereitung oder native Abnahme. Der vollständige APK-Gate ist durch Lauf #99, Versuch 2, auf Head `92e2c645cf0a8075325874f335087412e7f79c79` belegt. Spätere Quellstände benötigen ihre eigene Quellbindung und Prüfung; der Buildnachweis ersetzt keine native Abnahme. |
| [#463](https://github.com/maik3531/Magnolie-Organizer/issues/463) | Fehlende Accessibility-Fensterbindung wurde pauschal als fremder Eingabeblocker klassifiziert. | Unbelegte Bindung, Lesefehler, belegtes fremdes Fenster und eigener nicht bereiter Appzustand unterscheiden. Besitzprädikat unverändert; keine Lösung für Fensterkennung -1 behauptet. |

## Tatsächliche CI-Fortsetzung und gemeinsame Prüfcodefehler

Der vollständige [Lauf #96](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45806941029)
auf `e7d396ed39641338ce9a7b57929623bc1dbd2fe1` bestand 194/46 Web-/Importchecks,
Readiness und Quellprovenienz. Er stoppte vor Gradle im gemeinsamen Setupprüfer,
weil eine generierte Desktop-Zeitzonendatei im frischen Checkout fehlte.
Folgepatch 8 / [#804](https://github.com/maik3531/Magnolie-Organizer/issues/804)
erzeugt diesen Bootstrap mit dem vorhandenen validierenden Generator im Speicher.
Beide echten Desktop-Appskripte bleiben Testziele; 88 Fälle in 20 Sprachen sind
auch ohne Desktopcaches bestanden. Alte Caches werden nicht gelesen und
beschädigte normative Daten bleiben ein harter Fehler.

Der folgende [Lauf #98](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45809316206)
auf `2dd93930ecff3752fdea22121813a1b6ee4b79a7` bestätigt diesen Fix im echten
frischen CI-Checkout. 22 Provenienztests, 194 Webchecks, 46 Import-/Anhangschecks
und 88/20 Setupfälle sind bestanden. Gradle kompiliert Produkt-Kotlin, Manifest
und Ressourcen. Anschließend scheitert `compileDebugUnitTestKotlin` an fünf
`JSONObject.similar`-Aufrufen; dieser eigene Befund steht in
[#805](https://github.com/maik3531/Magnolie-Organizer/issues/805).
Die unveränderten Fehlerpassagen und gebundenen Receipts stehen unter
`pruefnachweise/android-tablet-followup-2026-11-26/ci-run-45809316206/`.

Der enge Testvergleich muss sämtliche Werte und Strukturen über die vorhandenen
öffentlichen Android-JSON-APIs vergleichen. Schlüsselreihenfolge ist bei Objekten
unerheblich, Arrayreihenfolge und Typen sind entscheidend; Null und fehlende
Schlüssel dürfen nicht verwechselt werden. Insbesondere darf `2^63` nicht durch
einen Double- oder Stringify-Umweg mit `Long.MAX_VALUE` gleichgesetzt werden.
Der geschlossene Produkt-Zahlenfix #466 wird dadurch nicht wieder geöffnet.
Der enge Vergleichsfix kompiliert gegen die echte Android-37.2-API und besteht
42/42 gezielte JVM-Tests, darunter zwölf unabhängige Vergleichsregressionen.
Alle 38 Produktquellen bleiben bytegleich. Aus diesen gezielten Tests und der
erfolgreichen Produktkompilierung folgt weiterhin kein gebautes APK.

## Vertrag für lokale Kopien

Erfolgreiche native Kontakt- und Kalenderantworten tragen `identitySchema:2`.
Jeder Record besitzt eine passende `identityKind`. Kontakte enthalten zusätzlich
eine gehashte `rowBinding`; die rohe ANDROID_ID verlässt den nativen Code nicht.
Die Metadaten werden mit der lokalen Kopie gespeichert und beim Wiederöffnen
erhalten. Sie begründen keine Schreib-, Lösch- oder Synchronisierungsrechte.

Bereits bekannte Identitäten werden übersprungen. Eine neue Zeilenbindung
derselben stabilen Kontaktidentität überschreibt keine lokalen Bearbeitungen.
Eine unbekannte Identität auf einer bereits anders gebundenen Kontaktzeile
verwirft den gesamten Kandidaten. Das gilt auch dann, wenn eine vorher nur lokal
identifizierte Quelle später eine Serverkennung erhält. Gleiche Namen oder
Telefonnummern werden nicht als Identitätsbeweis verwendet.

Vorhandene experimentelle Schema-1-Kopien derselben ausgewählten Quelle führen
bei einem nicht leeren neuen Ergebnis zu einem sichtbaren Identitätskonflikt.
Ein leeres Ergebnis bleibt ohne Änderung möglich; alte Kopien anderer Quellen
blockieren die ausgewählte neue Quelle nicht. Die Originaleinträge bleiben
unverändert. Alle bisherigen Mengen-, Sitzungs-, Revisions-, Speicher- und
Wiederöffnungsprüfungen bleiben erhalten.

Ohne stabile Providerherkunft können vollständige Kontakt- oder Kalenderresets
nicht verlässlich zugeordnet werden. Wird eine nur lokal identifizierte
Kontaktzeile für eine andere Person wiederverwendet, kann die Fallbackkennung
diese nicht zuverlässig unterscheiden; die vorhandene Kopie bleibt erhalten.
Lokale Fallback- und Kalenderkennungen
sind keine dauerhafte kontoübergreifende Syncidentität. Änderungen kompletter
Serienstrukturen und eine automatische Migration alter Kopien sind nicht Teil
dieses Fixes. Die direkte Android-Anbindung bleibt ein ausdrücklich ausgelöster
Kopiervorgang; Magnolie Notes und KDE Connect sind weiterhin keine Voraussetzung.

## Bedienung und Sprache

Der Importdialog erhält den Fokus bei Berechtigungs-, Lese-, Speicher-, Abbruch-
und Abschlusszuständen. In allen 20 vorhandenen Sprachen sind die neuen Texte
für Zugriff erlauben, Startdatum, Enddatum und Identitätskonflikt ergänzt.
Die Projektion verlangt neun nicht leere Systemimporttexte je Sprache. Die
deutschen Beschriftungen wurden in der tatsächlich gerenderten Oberfläche
geprüft. Eine Muttersprachlerprüfung aller Übersetzungen ist nicht dokumentiert.

## Native Providerprüfung zu #791

Das zusätzliche manuelle Workflowziel `tablet-system-records` baut zuerst das
vollständige APK-Paar mit unveränderten Gates. Anschließend führt es ausschließlich
die neue Stufe `system-records` auf API 34 / `google_apis` aus. Elf Prüfgruppen
verwenden echte Android-Provider und die tatsächlichen Produktleser; alle
Kontakte und Kalender sind synthetische eigene Fixtures auf dem eigenen Emulator.
Schreibberechtigungen gelten nur während Anlage/Änderung/Bereinigung der Fixtures.
Vor jedem Produktzugriff wird diese Identität abgelegt und das Fehlen effektiver
Schreibrechte geprüft. Die App erhält keine neue Produktberechtigung.

Zum Prüfumfang gehören verweigerte Lesezugriffe, Quellenentdeckung, Kontaktfelder,
stabile Kontaktidentität nach neuer RawContact-ID, Herkunftswechsel auf derselben
Zeile, Kalenderauswahl und Datumsfenster, verschobene Einzeltermine,
Serieninstanzen/Ausnahmen, vorab abgebrochene Abfragen und vollständige Bereinigung.
Die zwei echten Kalender belegen im Erfolgsfall deren Quellenisolierung. Für
Kontakte existiert nur eine lokale Testquelle: `contactsSourceIsolationTested:false`
bleibt ausdrücklich im Receipt; `calendarSourceIsolationTested:true` benennt den
getrennten Kalenderumfang. Ein UI-Dialog, Live-Widerruf, Import-/Save-ACK,
Abbruch während einer laufenden Abfrage oder TalkBack werden dabei nicht ausgeführt.

24 Quellen-/Workflowtests und vier gezielte Owner-Verträge bestehen. Die
Produkt- und Instrumentierungsquellen kompilieren gegen die echte Android-37.2-API.
Die beiden abschließend ergänzten Scope-Literale wurden gesondert nachkompiliert;
Rohbelege, ausgeführte Skripte und Quellhashes stehen unter
`pruefnachweise/android-tablet-followup-2026-11-26/system-records/`.
Diese Vorbereitungsbelege enthalten noch keine Provider-/Emulatorausführung;
die nachfolgenden tatsächlichen Läufe sind separat unten ausgewertet.
`systemProviderOnly:true` und `API34-provider-only` halten diesen Prüfumfang
von einer vollständigen nativen Abnahme getrennt.

## Vollständiger APK-Nachweis und native Fortsetzung zu #807

[Lauf #99, Versuch 1](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45817099578/attempts/1)
erreicht mit Head `92e2c645cf0a8075325874f335087412e7f79c79` Gradle, scheitert
aber beim externen Maven-Central-Download an HTTP429. Der unveränderte
[zweite Versuch](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45817099578/attempts/2)
besteht den vollständigen ursprünglichen APK-Gate: **303 Tests in 42 JUnit-Reports,
0 failures, 0 errors, 0 skipped**. Tatsächliche App-/Instrumentation-Bytes,
Kandidatenmanifest und die Projektionsdatei aus der App-APK stimmen mit der
Quellbindung überein. Dieser Erfolg bestätigt auch #805 im regulären Gradlepfad.

Die echte API34-Providerstufe bestätigt acht Fachgruppen: verweigerte Reads,
Discovery, Kontaktfelder, beide Kontaktidentitätswechsel, Kalenderauswahl und
Zeitfenster sowie Verschieben eines Einzeltermins. Danach scheitert die erwartete
Zweiermenge nach Anlage der Serienausnahme. Die Ist-Anzahl wurde im ursprünglichen
Receipt nicht protokolliert; die alte Fehlermeldung beweist kein Duplikat.
Alle 16 aufgezeichneten Produktaufrufe sind ohne WRITE-Rechte. Zwei eigene
Kontaktzeilen und zwei eigene Kalender sind anschließend vollständig entfernt.
Die nachfolgende Cancellation-Gruppe wurde nicht erreicht. Der Gesamtjob ist
fehlgeschlagen, obwohl der APK-Gate bestanden ist.

Der AOSP-14-Quellabgleich in #807 zeigt einen besonderen Expansionspfad ohne
Serien-Sync-ID; er liefert eine begründete Fixture-Hypothese, keine nachträgliche
Messung der fehlenden Instanzanzahl. Die korrigierte synthetische Syncadapter-
Fixture bindet Master und Ausnahme vollständig über `_SYNC_ID`/`ORIGINAL_SYNC_ID`;
`ORIGINAL_ID`, ursprünglicher Slot und Ganztagskennung bleiben zusätzlich geprüft.
Direktes Rücklesen der eigenen Eventzeilen sowie begrenzte Vorher-/Nachher-
Slotbelege ergänzen die unveränderten Zweier-/Identitäts-/12:00-/Folgetagprüfungen.
Der Produktleser, Produktberechtigungen und alle Ressourcengates bleiben unverändert.

Der Umfang wird ausdrücklich als `recurrenceFixtureUsesSyncMetadata:true` und
`unsyncedLocalRecurrenceExceptionsTested:false` aufgezeichnet. Nicht synchronisierte
lokale Serienausnahmen sind durch diese Fixturekorrektur nicht allgemein abgenommen.
Bei Erstellung von Folgepatch 11 stand dessen native Wiederholung noch aus.
Originalbelege beider Versuche des vorherigen Laufs liegen unter
`pruefnachweise/android-tablet-followup-2026-11-26/ci-run-45817099578/`.

## Erfolgreicher vollständiger Wiederholungslauf #101

[Actions #101, Versuch 1](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45822320243)
prüft exakt Head `7a7d90b04796cf338b98f0fdbb87e8da1c967043`, Tree
`06c1a8cf6f115908dc21252682c2a358246f2cb7`, Projektionsbind
`dbe502cf4ad4661be79dca584c120d8623676cf8be5c3ff0d61eba840b676c09`.
Der vollständige APK-Gate und die nachfolgende echte API34/google_apis-
Providerstufe sind erfolgreich. Alle 42 Original-JUnit-Reports ergeben erneut
**303 Tests, 0 failures/errors/skips**. Die tatsächlichen App-/Instrumentierungs-
APKs und die Projektionsbytes innerhalb der App sind geprüft.

Die Originalreceipt bestätigt **zehn Fachgruppen plus Cleanup**. Vor und nach
der Serienausnahme stehen jeweils genau zwei Instanzen. Der 1. April 2030 wechselt
von 09:00 auf 12:00 bei unveränderter ursprünglicher Record-ID; der 2. April bleibt
bei 09:00 mit unveränderter ID. Die tatsächlichen Providerzeilen bestätigen
Master-/Ausnahmeverknüpfung. Beide vorab gesetzten CancellationSignals werden
als `OperationCanceledException` abgewiesen. Alle 19 protokollierten Produkt-/
Readbackaufrufe haben keine effektiven WRITE-Rechte oder aktive Fixtureidentität.
Cleanup entfernt die zwei eigenen RawContacts und zwei Kalender vollständig.

Damit ist der konkrete Fixture-Prüfpfad #807 korrigiert und nativ bestätigt.
`unsyncedLocalRecurrenceExceptionsTested:false` und
`contactsSourceIsolationTested:false` bleiben bestehen. Der erfolgreiche
Providerlauf ist keine Activity-/Berechtigungsdialog-/Live-Widerruf-/Save-ACK-/
IME-/TalkBack-Abnahme und testet keinen Abbruch während einer laufenden Abfrage.
Die unbekannte Instanzanzahl des alten Fehllaufs wird nicht rückwirkend abgeleitet.

Originalbelege, Prüfsummen und ausgeführter Artefaktprüfer:
`pruefnachweise/android-tablet-followup-2026-11-26/ci-run-45822320243/`.
Der abschließende Nachtrag ändert ausschließlich Dokumentation und Nachweise.
Der tatsächlich geprüfte APK-/Laufzeitstand bleibt der oben gebundene Head;
ein neuer Dokumentationscommit wird nicht als erneut gebautes APK bezeichnet.

## Prüfumfang und Restabnahme

Die konkreten Quellhashes, ausgeführten Befehle, Rohprotokolle und Ergebnisse
stehen unter `pruefnachweise/android-tablet-followup-2026-11-26/`.
Die Belege trennen diese Ebenen:

- Reproduktion am vorherigen Produktionsmapper bzw. an der vorherigen Oberfläche;
- JVM-Tests mit synthetischen Providerabfragen sowie echte Android-API-/Ressourcenkompilierung;
- erzeugte Organizeroberfläche in jsdom und echtem Chromium mit synthetischer Bridge;
- Provenienz-/Workflowtests mit tatsächlichen Git-Fixtures und Workflowausdrücken;
- vollständiger Gradle-/D8-/APK-Bau und echte Android-Laufzeit, soweit tatsächlich ausgeführt.

Für #463 werden ausschließlich begrenzte Root-/Fenster-/Service-Metadaten gelesen.
Fenstertexte, Titel, Knoteninhalte und Exception-Nachrichten werden nicht erfasst.
Die bestehende Besitzbedingung, Gestendauer und die Abbruchentscheidung vor
unbelegter Eingabe bleiben erhalten; keine Flags, Retries oder Prewarms kommen hinzu.

Über die oben nachgewiesenen Providerfälle hinaus bleiben insbesondere
unsynchronisierte lokale Serienausnahmen, eine zweite Kontaktquelle,
Berechtigungsdialoge und Live-Widerrufe, UI-/Save-ACK, laufende Query-Cancellation,
Rotation/Prozessneustart, native Eingabe und TalkBack sowie die bestehende
native Speicher-/SAF-/Restore- und Pixelmatrix. Ein reiner Buildnachweis kann
diese Abnahmen nicht ersetzen. Die Issues bleiben bis zur passenden Abnahme
und Prüfung der Patchserie offen.

## Primärquellen des Providervertrags

- [Android Contacts Provider](https://developer.android.com/identity/providers/contacts-provider)
- [RawContactsColumns.BACKUP_ID](https://developer.android.com/reference/android/provider/ContactsContract.RawContactsColumns#BACKUP_ID)
- [Settings.Secure.ANDROID_ID](https://developer.android.com/reference/android/provider/Settings.Secure#ANDROID_ID)
- [Calendar Provider](https://developer.android.com/identity/providers/calendar-provider)
- [EventsColumns.ORIGINAL_ID](https://developer.android.com/reference/android/provider/CalendarContract.EventsColumns#ORIGINAL_ID)
- [UiAutomation](https://developer.android.com/reference/android/app/UiAutomation)
