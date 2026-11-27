# #128 – Notes: gewöhnlicher Abschluss nach endgültigem Kanalverlust

Basis: 7c9f9395ac7fcac03b0ce229f9707643be4b06fa; TelefonWerk.kt Blob 5985df6ff77e8f852cb4cfe8779a14d0b47c6774; TelefonDatenbank.kt Blob 96c22633689dce456b72b6b22a49d629be2471c7; PersonalSyncActorJournal.kt Blob 54a7d4046b329efff4680fa3ae957bb80bd86a96. Hauptzweig und Reviewzweig vor Veröffentlichung erneut gelesen. Die beiden bisherigen Nachträge #691/#128 Desktop sind noch nicht in main übernommen, da main unverändert ist; dieser Einzelpatch betrifft eine andere Datei als deren Produktänderungen. Die früheren zehn sind weiterhin übernommen. Kein Produktmerge.

## Konkrete Lebenszyklusfolge

- TelefonWerk.kt 425–561: gewöhnlicher Löschreview erzeugt je lokaler Entscheidung einen eigenen Decision-Umschlag (bis 256 Ziele), stellt den Journalabschluss her, entfernt den Run aus personalActorWork, speichert das Buch und legt den Abschluss in personalActorCompletions ab. Der gewöhnliche Pfad erzeugt keinen historical handoff.
- 2278–2302 und 2979–2986: explizites Schließen oder Sitzungsende entfernt den aktiven Kanal und ruft retireInvalidPersonalActors auf. Auf der Basis erfasst diese Methode nur personalActorWork und historische Handoffs. Gewöhnliche unvollständige Abschlüsse bleiben trotz endgültig verlorenen alten Kanals bis zum Reap (Journal-Lebensdauer 30 Minuten).
- 1272–1276 und 1683–1691: Abschlussautorität prüft exakt die ursprüngliche Kanal-/Pipe-/Generationsbindung; ein neuer Kanal kann die alte Autorität nicht übernehmen. Die Abschluss-Guards erfassen den ursprünglichen Kanal (533–551); ein bloß wartender Scope auf demselben Kanal ist dagegen kein Verlust.
- 4591–4600/4810–4828: der normale Sender überspringt reservierte Actor-Frames; der eigene Sender benötigt aktuelle Kanalzuordnung. TelefonDatenbank.kt 253–302 begrenzt vor diesen Guards auf 32. Die 65 noch fälligen zulässigen Decision-Frames einer solchen Fixture können daher gewöhnliche Ereignisse verdecken. Der bisherige Test PersonalSyncActorOutboxTest.kt 101–108 deckt bereits explizit gestoppte Actors ab, nicht den ausgelassenen Abschluss-Lebenszyklus.
- #301 (geschlossen) ist eine andere Desktop-ACK-Metadaten-Recovery; #508/#509 (geschlossen) betreffen Metadaten-Pumpbudget; #190/#297 sind frühere Actor-Ausbauübergaben. Kein neues Dubletten-Issue.

## Enger Kandidat

Bei einem noch nicht abgeschlossenen gewöhnlichen Completion mit endgültig anderem/fehlendem aktiven Kanal denselben vorhandenen stopPersonalActor-Aufruf wie bei verlorener historischer/aktiver Autorität verwenden. Nicht auf demselben Kanal nur wegen wartender Autorität stoppen; historische Regeln und abgeschlossene Runs unverändert. Fehler in der bestehenden Stoppoperation werden wie bisher für einen Wartungsretry gehalten. stopActorRun setzt den authentifizierten stopped-Marker und die betroffenen next_attempt_ms auf Long.MAX_VALUE, erhält die versiegelten Outbox-Zeilen. Der bestehende Stopppfad räumt ausschließlich den laufprivaten Staging-Namespace auf; das bereits gespeicherte Produktbuch wird nicht erneut geschrieben, zurückgerollt oder gelöscht. Kein Rebind, keine Freigabeänderung, keine Quittung als Erfolg ausgeben. Die endgültige Stoppoperation bei einem echten Datenbank-/Kryptofehler kann weiterhin bis zur Wiederholung scheitern.

## Wirklich ausgeführt

Kotlin/JVM 1.9.0, JRE 21.0.12: tatsächlich kompilierte, aus dem Quellblob exakt entnommene Methoden stopPersonalActor und retireInvalidPersonalActors (nur Typname PersonalActorHandle im Testdouble zu Handle ersetzt). Kontrollierte Map-, Journal-, Kanal-, Staging- und Buchdoubles bilden den beschriebenen Post-Commit-Zustand ab. **Basis 5/8, Kandidat 8/8**: Rot für Kanalverlust, Ersatzkanal und Wiederholung nach simuliertem Stoppfehler. Grün bleiben gleicher Kanal/Scope-Warten, abgeschlossener Run, historischer Kanalverlust und gleiche historische Autoritätsregel, aktiver Actor. Die Quellmethoden wurden vor Veröffentlichung exakt gegen den GitHub-Blob verglichen.

Separat tatsächliches SQLite 3.46.1 mit originalem SQL-Sortierausdruck und 32er-Limit: 65 Decision-Zeilen vor gewöhnlichem incoming_call_state.event; vor Stopp 32 Actor-Zeilen, nach gesetztem Retry-Sentinel genau das gewöhnliche Ereignis, 66 Zeilen unverändert vorhanden. Das ist ein SQL-Auswahltest, keine tatsächliche verschlüsselte TelefonQueue oder Socketzustellung. Die Post-Commit-Felder und Stoppwirkung werden im Kotlin-Harness kontrolliert vorbereitet, nicht durch echten Buchsave/Android-Runtime hergestellt. Daher ist dies ein gezielt reproduzierter Methodenbefund und ein **Host-geprüfter Kandidat**, nicht der vollständige Lifecycle-End-to-End-Nachweis.

Wiederholung: python3 repro.py base-excerpt.kt (Exit 1 erwartet), python3 repro.py fixed-excerpt.kt (Exit 0). Alternativ aus einer echten Basis-Checkout-Datei und nach Anwendung des Einzelpatches jeweils mit dem Pfad zu TelefonWerk.kt aufrufen. Die Quellhunks wurden gegen den entfernten Basisblob abgeglichen; kein vollständiger Android-Bau oder vollständiges git apply auf einem Checkout ausgeführt (kein Netzwerkzugriff im Testcontainer, Gradle/Robolectric/Android-Abhängigkeiten dort nicht verfügbar). Keine installierte APK-/Geräte-/Router-/Mobilfunk-/native Windows-Abnahme. Keine Dateien persönlicher Daten oder Schlüssel verwendet.

SHA-256 aus dem ausgeführten lokalen Test:
- Patch 1282 Bytes: 8a01b48fd51aef319e6fe9171456357eb37598c6ea34c65fce673bce2c861c1c
- repro.py: c7d5ed45abff2eb4aa97e556d729d5b700c8e8cfaa6e56e052de19bf9c1f5875
- base-excerpt.kt: 9263589f14aa84fd036423eda9c840815cb44afe73ef7ed640968ed9772dc9ee
- fixed-excerpt.kt: 5ea77f43ef01b7893b21090a9a8e098b3e57cba64eceb03d4c26212e429d9c29
- before.log: 123b02ff67dcd23bc1c79b4a7bd8b929f8e883519ae020ae4a7dba5ef3e6c483
- after.log: 2c7f827a6d68bce13e102b548f108c2553023e861ef985c8e5bd03fb7465df23

## Nächster Schritt

Vor Übernahme eine tatsächliche Robolectric-TelefonWerk-/TelefonQueue-Fixture mit regulär vorbereitetem Abschluss, 65 Decisions, Verlust der ursprünglichen Sitzung, normalen erlaubten Ereignissen und neuer Verbindung ergänzen und gegen beide Stände ausführen. Dabei tatsächliche versiegelte Outbox-Zeilen, noch ausstehende Abschlussquittungen, unveränderten Buchhash sowie erneute Stoppoperation bei einem kontrollierten SQL-Fehler prüfen. Insbesondere sicherstellen, dass bestehender privater Staging-Cleanup keine später benötigten Belege eines bereits gespeicherten Abschlusses entfernt. Der Kandidat ist bis dahin separat und nicht als vollständiger Android-Fix freigegeben. Danach auto_connection entlang realer Controller-/Capability-/Validatorpfade prüfen. Keine alten Gesamtpatches doppelt anwenden.
