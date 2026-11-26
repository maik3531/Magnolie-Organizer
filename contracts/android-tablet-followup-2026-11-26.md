# Android-Tablet: Folgekorrekturen vom 26. November 2026

Ausgangspunkt ist der veröffentlichte Stand von [PR #795](https://github.com/maik3531/Magnolie-Organizer/pull/795),
Commit `29acde7e3df2b8bcaaab0cc19b3377b8dbf4bd14`. Der erste
[Issue-Audit](android-tablet-audit-2026-11-26.md) bleibt als Verlauf erhalten.
Zu dessen 26 maßgeblichen Issues kommen vier reproduzierte UI-/Herkunftsfehler
und zwei im echten CI-Bau bestätigte Prüfcodefehler (#804/#805) hinzu.
Die Änderungen werden weiterhin als überprüfbare Patchserie bereitgestellt.

## Änderungen und Zuordnung

| Issue | Belegter Fehler | Korrektur und Grenze |
| --- | --- | --- |
| [#798](https://github.com/maik3531/Magnolie-Organizer/issues/798) | Ein Neuzeichnen des Importabschnitts entfernte das fokussierte Steuerelement; der Tastaturfokus landete außerhalb des Dialogs. | Fokus innerhalb des betroffenen Abschnitts an der passenden Aktion bzw. einem beschrifteten Statusanker wiederherstellen; externen Fokus nicht übernehmen. Chromium-Beleg, native IME-/TalkBack-Abnahme offen. |
| [#799](https://github.com/maik3531/Magnolie-Organizer/issues/799) | Neue lokale Kontaktzeilennummer trotz gleicher Providerherkunft erzeugte eine zweite Importidentität. | SOURCE_ID, ersatzweise BACKUP_ID verwenden; erst danach geräte-/nutzergebundene lokale Kennung. Vor-/Nach-Snapshots prüfen auch Herkunftskennungen. |
| [#800](https://github.com/maik3531/Magnolie-Organizer/issues/800) | Verschieben eines Einzeltermins änderte durch BEGIN dessen Importidentität. | Einzeltermine nach Event-ID; Serieninstanzen nach ursprünglichem Slot; Ausnahmen nach ORIGINAL_ID und ORIGINAL_INSTANCE_TIME. Geräte-/Nutzerscope einbeziehen. |
| [#801](https://github.com/maik3531/Magnolie-Organizer/issues/801) | Die korrekte Konfliktmeldung lag außerhalb des offenen Einstellungsdialogs und wurde verdeckt. | Systemimportmeldungen im zugehörigen Dialogabschnitt anzeigen; die echte Browserprüfung muss ihre Sichtbarkeit und Erreichbarkeit belegen. |
| [#790](https://github.com/maik3531/Magnolie-Organizer/issues/790) | Der vollständige APK-Bau war nicht unabhängig von der nativen Emulatorabnahme ausführbar. | Explizites Workflowziel `tablet-build-only`: gleicher vollständiger Build-/Quellbindungsweg, keine Emulatorvorbereitung oder native Abnahme. Kein Erfolg dieses bislang ausstehenden Builds wird allein aus Quellkompilierung abgeleitet. |
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

Offen bleiben insbesondere Provider- und Berechtigungsabläufe auf Android,
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
