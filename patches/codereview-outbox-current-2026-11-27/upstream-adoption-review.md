# Übernahmeprüfung der früheren Patchserie

**Ergebnis:** Auf `da81f594a2709d2c0ba78696b3af4775f38313f8` können die fünf unten aufgeführten alten Einzelpatches aus der Restserie entfallen. Ihr gelieferter Umfang ist vollständig beziehungsweise funktional gleichwertig übernommen. Das ist keine Aussage über den vollständigen Abschluss aller übergeordneten Issue-Kriterien.

## Vergleichsgrundlage

- Ausgangsbasis: `9de81cc10d72ca7b176b5c501ff20689cdd53c31`.
- Geprüfter neuer `main`: `da81f594a2709d2c0ba78696b3af4775f38313f8`.
- Früherer Integrationsstand: `/workspace/scratch/69a9d769e56f/outbox-integration-current` — Basis `9de81cc` mit angewendeter/indexierter neunteiliger Serie sowie Notes #148 und #691; kein behaupteter Produkt-`main`.
- Originalpatches: `/workspace/scratch/7203da5bd564/open-audit/final-patches`; deren ursprüngliche Serienbasis war `7a490dd87e94eec08d7f09cb95a04b34bf4621c2`.
- Methode: gezielter vollständiger Datei- und Testdiff gegen die Git-Objekte des neuen `main`, ergänzt um maschinelle Gleichheitsprüfungen. **Keine Tests erneut ausgeführt.**

## Aus der Restserie entfernen

| Issue | Alter Einzelpatch | Übernahmecommit | Ergebnis |
|---|---|---|---|
| #566 | `01-566-preserve-csv-contact-fields.patch` | `4660ba780d87c04e428506b609dc1b004bd44336` | Vollständig übernommen. |
| #790 | `03-790-correct-current-source-test.patch` | `da81f594a2709d2c0ba78696b3af4775f38313f8` | Vollständig übernommen, zusätzliche Tablet-Assertion erhalten. |
| #844 | `07-844-calendar-color-followup.patch` | `2bdb026fb130e66e5547007fc18aa7843e81c38d` zusammen mit vorhandenem #846-Fix `f8ad956` | Fachumfang übernommen; Sonderfall des alten JS-Guards siehe unten. |
| #845 | `08-845-nextcloud-birthday-followup.patch` | `2f2f9f120df4d8dfd1b2d6067c3b410c688bcea1` | Funktional vollständig übernommen. |
| #845 | `09-845-exported-birthday-exception-guard.patch` | `2f2f9f120df4d8dfd1b2d6067c3b410c688bcea1` | Funktional vollständig übernommen. |

## Konkrete Gleichheits- und Äquivalenzbelege

**#566:** `contracts/lotus-csv-contact-fields.json`, `magnolie-organizer/pruefungen/test_lotus_csv_contact_fields.py` und `magnolie-organizer-windows/tests/LotusCsvContactFieldTests.cs` sind bytegleich zur früheren Integration. Der CSV-Erhalt generischer/privater/geschäftlicher Anschriften und Telefonrollen einschließlich VCF-Rundlauf ist übernommen.

**Gemeinsamer Produktnachweis für #566/#844/#845:** Die komplette Datei `magnolie-organizer/bin/magnolie-organizer` ist bytegleich zur früheren Integration. Die komplette Windows-Datei `magnolie-organizer-windows/ExchangeCodec.cs` ist nach ausschließlich zwei neutralen Textänderungen identisch: `allowProviderBirthday` heißt jetzt `allowAnniversary`; eine durch die äußere Bedingung garantierte zweite Abfrage dieses Flags wurde entfernt. Der neue Name und die bereinigte Bedingung bleiben erhalten.

**#790:** `Magnolie-Organizer-macOS-Beta/tests/test_candidate_sources.py` ist vollständig bytegleich. In `Magnolie-Organizer-Android-Tablet-Beta/tests/test_source_proof.py` ergänzt Upstream darüber hinaus die Erwartung `"absolute-notifications": ["absolute-notifications"]`.

**#844:** `contracts/calendar-color-remainders.json` sowie die Windows-Testdateien `CalendarColourRemainderTests.cs`, `birthday-display.js`, `calendar-colour-remainders.js` und `legacy-android-instance-ui.js` sind bytegleich. `magnolie-organizer/pruefungen/test_calendar_color_remainders.py` enthält alle bisherigen Tests und zusätzlich `test_incomplete_calendar_uses_localized_validation_error`. Die vollständigen Unterschiede beider `anwendung.js` zur früheren Integration beschränken sich auf den getrennten #395-Organisatorvorschlag und den nachfolgend erläuterten alten Zusatzguard; kein weiterer #844-Fachrest wurde festgestellt.

**#845:** `magnolie-organizer/pruefungen/test_nextcloud_ics_birthdays.py` ist bytegleich. In `magnolie-organizer-windows/tests/NextcloudIcsBirthdayTests.cs` bleiben die Prüfungen beider Nachträge erhalten. Die zuvor privat aus `RunAsync` aufgerufenen Hilfsfälle wurden zu `EditedLeapBirthdaysAsync` und `ExportedBirthdayKeepsDetachedOverrideAsync` mit `Task`-Rückgabe. `magnolie-organizer-windows/tests/Program.cs` unterscheidet sich exakt durch ihre zwei zusätzlichen Registrierungen:

- `Nextcloud ICS birthdays / edited last-February recurrence`
- `Nextcloud ICS birthdays / reimport with detached override`

## Sonderfall: alter JavaScript-Guard und #846

Der alte #844-Patch ergänzte beim Legacy-UID-Alias-Merge beider Desktop-Oberflächen `&& t[feld] !== undefined`. Diese zusätzliche Bedingung steht nicht im neuen `main`.

Der vorhandene Fix `f8ad956` zu #846 verhindert den nachgewiesenen problematischen Zustand bereits bei der Normalisierung: Ein fehlender beziehungsweise nicht als String vorliegender Terminwert `icsCalendarColor` wird entfernt und nicht als eigene `undefined`-Eigenschaft weitergereicht. Bei Aufgaben wird die Eigenschaft ebenfalls nur für einen String aufgenommen. Die fehlende Farbangabe kann damit die Aliasübernahme nicht über diesen Fehler abbrechen oder eine vorhandene Herkunftsfarbe löschen; ein ausdrücklich leerer String bleibt ein absichtlicher Wert.

Der passende Regressionstest für fehlende gegenüber ausdrücklich leerer Kalenderfarbe in `legacy-android-instance-ui.js` ist identisch zur alten Serie und mit `2bdb026` übernommen. **Für den demonstrierten Fall ist der alte Zusatzguard durch die Quellkorrektur ersetzt. Ein verbleibender #844-Fachfix wurde nicht belegt.** Diese Feststellung beruht auf Quell-/Testdiff, nicht auf einer erneuten Laufzeitausführung.

## Zusätzliche Upstream-Verbesserungen erhalten

- Den neuen Python-Test für die übersetzte Fehlermeldung bei unvollständiger ICS-Datei erhalten.
- Die Tablet-Assertion für `absolute-notifications` erhalten.
- Die beiden separat registrierten #845-C#-Testgruppen erhalten.
- Die `allowAnniversary`-Benennung und die bereinigte Bedingung erhalten.
- Die aktuellen `ARBEITSSTAND.md`-Einträge aller vier Übernahmen samt ihren Grenzen erhalten.

Die Restserie muss vom neuen `main` ausgehen. Den alten Gesamtpatch beziehungsweise alte vollständige Dateien darüberzulegen würde diese zusätzlichen Änderungen gefährden.

## Grenzen

Keine gezielte oder vollständige Testsuite wurde für diese Übernahmeprüfung erneut ausgeführt. Es wurden keine Produktdateien und keine externen Ressourcen verändert. Der Vergleich begründet keine neue native oder installierte Paketabnahme.

Der gelieferte Patchumfang ist vom umfassenderen Issue-Ziel zu unterscheiden: #566 lässt laut aktuellem `ARBEITSSTAND.md` die gemeldete Sammelentscheidung im installierten Windows-Organizer offen; die vollständige DAV-Jahrestagsintegration bleibt bei #845 ausdrücklich in #441.

Der maschinenlesbare Begleitnachweis ist `upstream-adoption-review.json` im selben Verzeichnis.
