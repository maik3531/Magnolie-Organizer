# CI99: APK-Build erfolgreich, native Serienausnahme offen

Belegpaket zum [Actions-Lauf 45817099578](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45817099578)
vom 26. November 2026. Beide Versuche liefen auf demselben Quellstand. Die
Wiederholung erfolgte einmalig wegen des externen HTTP429-Fehlers; sie war kein
neuer Workflowdispatch. Der Workflow zielte auf `tablet-system-records`,
also ausschließlich die Provider-Prüfstufe unter API34/`google_apis` nach dem
vollständigen bestehenden APK-Buildgate.

| Versuch | Job | Ergebnis | Artefakt |
|---|---|---|---|
| 1 | [139899561178](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45817099578/job/139899561178) | Schritt 6 fehlgeschlagen: Maven Central antwortete während der Gradle-Konfiguration mit HTTP429. Keine APK und keine Provider-Ausführung. | `15115733348` |
| 2 | [139902186688](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45817099578/job/139902186688) | APK-Buildgate erfolgreich; native Providerstufe 13 an der Serienausnahmen-Assertion fehlgeschlagen. Befund unter [#807](https://github.com/maik3531/Magnolie-Organizer/issues/807). | `15115844508` |

Das Gesamtresultat beider Versuche ist `failure`. Versuch 2 liefert dennoch
einen gültigen Build- und Unit-Test-Nachweis. Die Provider-Suite insgesamt,
eine vollständige native Tablet-Abnahme und eine Releasefreigabe sind damit
nicht bestanden.

## Verbindlicher Quellstand

| Beleg | Wert |
|---|---|
| Commit für Port und Desktop | `92e2c645cf0a8075325874f335087412e7f79c79` |
| Git-Tree | `d7b912c6aba697da48ccf1919591a162a4a4a452` |
| Projektion | `6c0e5542020d04ffaf556ee1334bbe32c91fcfd0da81ff90749b64ca33a6fe8a` |
| Quellinputmenge, SHA256 | `90ac565f4dc17d780d5d7c2a755e23e9f7b1706cf08478abf50f2bee9d65c2c8` |
| Manifest der gepackten Projektion, SHA256 | `87c0b1fd409efcb1b1eff23c61bf960771fc74036957f19022798e651729f8e9` |

Die Quellbindung weist `sourceMode=current-checkout` aus. Port und Desktop
verwenden denselben Commit. Der historische Tag `v2.0.30` bleibt lediglich die
Referenz für bestehende Vergleichsprüfungen. Die kanonisch erzeugten Kataloge
sind in Versuch 2 mit `generatedCatalogsVerified=true` nachgewiesen.

[Quellbindungsauswahl von Versuch 2](attempt-2/source-binding-selection.json)
und [Checkout-Auswahl von Versuch 1](attempt-1/source-checkout-selection.json)
enthalten alle übergeordneten Originalfelder. Nur die jeweils 462 Einträge der
Quellfile-/Blobliste sind ausgelassen. Beide Auswahlen nennen ausdrücklich die
Größe und SHA256 des vollständigen Originalrecords; der Prüfer vergleicht sie
gegen die vollständigen Records in den Original-ZIPs.

## Versuch 1: HTTP429 vor der Kompilierung

Gradle 9.6.0 wurde geladen und gestartet. Die Auflösung von
`org.jetbrains.kotlin:kotlin-gradle-plugin:2.4.21` scheiterte an der Antwort
`429 Too Many Requests` von Maven Central; Gradle meldete weitere 61 Fehler
mit derselben Ursache. Das Resultat war `BUILD FAILED in 25s`.

Dies belegt keinen weiteren Quellcompilerfehler. Zu diesem Versuch gibt es
keine ausgeführten Gradle-Unit-Tests, keine APK und keine native Providerprüfung.
Die vorbereitenden 24 Provenienztests, 194 Webchecks, 46 synthetischen
Copy-/Attachment-Integrationschecks und 88 Setupfälle für 20 Sprachen waren
bereits bestanden; der [Webproof](attempt-1/web-test-proof.json) bindet seine
194 Checks an die oben genannte Projektion.

Der [unveränderte Joblogauszug](attempt-1/job-failure.log) enthält die
ursächliche Fehlermeldung. [gradle-failure.txt](attempt-1/gradle-failure.txt)
ist das unveränderte, JSON-decodierte `output`-Feld aus dem ursprünglichen
Fehlerereignis; seine Bytes wurden zusätzlich gegen `debug-build.json` im
Originalartefakt geprüft.

## Versuch 2: vollständiger Build- und JUnit-Nachweis

Alle **42 JUnit-XML-Reports** sind unter [attempt-2/junit](attempt-2/junit/)
vollständig und bytegenau enthalten. Sie umfassen zusammen **64.448 Bytes**.
Die Zählung aus allen Reports ergibt:

| Tests | Failures | Errors | Skipped |
|---:|---:|---:|---:|
| 303 | 0 | 0 | 0 |

[artifact-verification.json](artifact-verification.json) führt jeden Report
mit ursprünglichem ZIP-Pfad, Repo-Pfad, Größe, SHA256 und Einzelzählung auf.
Der Prüfer vergleicht die XML-Kopien mit den Original-ZIP-Mitgliedern, prüft
auch die Anzahl der tatsächlichen `testcase`-/Fehler-/Skip-Elemente und gleicht
die Gesamtsumme mit `candidate.json` ab. Es handelt sich um die komplette
Reportmenge dieses Gradle-Laufs.

Beide tatsächlich erzeugten APKs wurden unabhängig gehasht:

| APK | Bytes | SHA256 |
|---|---:|---|
| `Magnolie-Organizer-Android-Tablet-Beta-2.0.30Beta-debug.apk` | 12.106.519 | `c45915e1fb06eff2dbda216c42d6bc0289218e25e49be52b1a0eaa4bb9135d6f` |
| `Magnolie-Organizer-Android-Tablet-Beta-2.0.30Beta-instrumentation.apk` | 266.014 | `47dcc1f9b388734fda858f78d66bbf564ebb0c5948b8ecc09ce75d9933b9ebd6` |

Die Hashes stimmen jeweils mit dem unveränderten
[candidate.json](attempt-2/candidate.json) und der Quellbindung überein.
Zusätzlich wurde der Kandidatenmanifest-Digest geprüft. Aus der echten App-APK
wurde `assets/projection.json` gelesen: Dessen Manifest-Digest und SourceHash
stimmen mit Quellbindung, Webproof und nativer Stage überein. Die beiden APKs
sind Debug-Prüfkandidaten; ihre Binärdateien sind nicht Bestandteil dieses
kompakten Repo-Belegpakets.

## Nativer Befund #807 und tatsächlich bestandene Teilprüfungen

Der Emulator erreichte den Produktionspfad für Android-Kontakte und Kalender.
Der Fehler ist eine Smoke-Assertion nach erfolgreichem Start, kein
Emulator-Boot- oder Lifecyclefehler:

```text
NativeSystemProviderSmoke.kt:185
IllegalStateException:
Provider must replace the original recurring slot, not duplicate it
```

Die Assertion prüft `seriesAfter.size == 2` nach Anlage einer verschobenen
Serienausnahme. **Die tatsächliche Ist-Anzahl und die gelesenen Rohzeilen
wurden in diesem Stand nicht protokolliert.** Der Meldungstext allein beweist
deshalb kein Duplikat und trennt eine Fixtureursache noch nicht von einer
Produktursache. Die weitere Ursachenklärung beziehungsweise Korrektur gehört
zu #807 und ist nicht rückwirkend Teil dieses CI-Nachweises.

Die Originale [system-records-receipt.json](attempt-2/system-records-receipt.json)
und [system-records.json](attempt-2/system-records.json) enthalten `passed=false`.
Der [ursächliche Logauszug](attempt-2/native-failure.log) und der
[unveränderte Fehlerstack](attempt-2/native-error.txt) sind ebenfalls enthalten.

Vor dem Fehler wurden acht fachliche Prüfgruppen erfolgreich protokolliert:

1. Der Produktionsread verweigert den Zugriff bei fehlenden READ-Rechten.
2. Discovery findet die lokale Kontaktquelle und beide eigenen Fixturekalender.
3. Echte Kontakt-Data-Zeilen liefern Namen, Telefontyp und Geburtstag.
4. Gleiche SOURCE_ID überlebt eine tatsächlich andere RawContacts-Zeile; die Row-Bindung ändert sich.
5. Geänderte SOURCE_ID in derselben Zeile ändert die Record-ID bei gleicher Row-Bindung.
6. Der ausgewählte Kalender bleibt isoliert; zeitgebundene halboffene und ganztägige UTC-Datumsgrenzen werden eingehalten.
7. Das westliche Instantfenster erhält den letzten ausgewählten ganztägigen Termin.
8. Das Verschieben eines echten Einzeltermins erhält dessen Identität.

Der Cleanup bildet die neunte bestandene Prüfgruppe: zwei eigene RawContacts
und zwei eigene Kalender wurden entfernt, jeweils null eigene IDs blieben
übrig. Die Shellidentität war abgelegt, WRITE-Rechte waren abwesend. Alle
16 protokollierten `product()`-Aufrufe einschließlich Vorbedingungs- und
Readbackprüfungen erfolgten ohne Fixture-WRITE-Rechte.

Die nach der fehlgeschlagenen Serienprüfung liegenden Cancellationprüfungen
wurden **nicht ausgeführt**. Ebenfalls nicht belegt sind Berechtigungsdialoge,
Live-Widerruf, In-flight-Cancellation, UI-Save-ACK oder vollständige
Synchronisierung. `contactsSourceIsolationTested=false` bleibt ausdrücklich
gesetzt, weil nur eine lokale Kontaktquelle geprüft wurde;
`calendarSourceIsolationTested=true` bezeichnet die tatsächlich geprüfte
Kalenderabgrenzung.

## Originale, Auswahlen und Kopiernachweis

[evidence-index.json](evidence-index.json) ordnet alle 53 bytegenau übernommenen
Originaldateien ihren ursprünglichen ZIP-Mitgliedern, gespeicherten
Monitorreceipts oder Logauszügen zu und nennt Größe sowie SHA256. Jede Kopie
wurde bei Erstellung mit den Quellbytes verglichen; der ausgeführte Prüfer
verifiziert alle Kopierhashes erneut. Bei ZIP-Mitgliedern erfolgt zusätzlich
ein direkter Bytevergleich mit dem Originalarchiv.

Die beiden `monitor-receipt.json` sind unverändert übernommene Auswertungsreceipts
der CI-Beobachtung; sie sind keine zusätzlich vom Android-Gerät erzeugten
Ergebnisse. Die jeweils als `run-record-selection.json` bezeichneten Dateien
sind ausdrücklich **Auswahlen** aus den ursprünglich gespeicherten
GitHub-API-Records. Sie enthalten Run-/Versuchs-/Jobstatus und Artefaktbezug
sowie Größe und SHA256 des vollständigen Ausgangsrecords. Ausgelassen sind
überflüssige Repository-/Owner-Payloads und fremde Versuchseinträge.

Das komplette Joblog von Versuch 2 wird aus Umfangsgründen nicht mitgeführt:

| Original | Wert |
|---|---|
| Job | `139902186688` |
| Größe | 307.233 Bytes |
| SHA256 | `08d9b30d4dffdeb2712336ee18c5d2341758784d6e744abb8dcac4efb2790139` |
| Enthaltener unveränderter Auszug | Zeilen 2927–2969 in `attempt-2/native-failure.log` |

Beim dokumentierten Prüflauf wurde auch das vollständige externe Originallog
anhand dieses Hashes geprüft und der enthaltene Auszug als unveränderter
Teilstring bestätigt.

## Reproduzierbare Artefaktprüfung

Die Original-ZIPs stammen aus den oben genannten GitHub-Artefakt-IDs. Ihre
Downloads wurden anhand der vom GitHub-Artefaktrecord gelieferten Digests
geprüft:

| Versuch | ZIP-Bytes | SHA256 |
|---|---:|---|
| 1 | 41.044 | `91bb767247dce6d279c5c50250de82d020a81522bbfec21c83fd991c5f1bb08b` |
| 2 | 12.387.207 | `e1274e177b578bafd4ff4a10a37bf5a6f7e1cd8e1a78569c0f9c83e074cf0759` |

[verify-artifacts.py](verify-artifacts.py) benötigt nur Python 3 und seine
Standardbibliothek. Der folgende Aufruf wurde mit den tatsächlichen
Original-ZIPs und dem vollständigen Originaljoblog erfolgreich ausgeführt;
das Ergebnis ist [artifact-verification.json](artifact-verification.json).
Dateipfade sind als Argumente austauschbar:

```sh
python3 -B verify-artifacts.py \
  --attempt-1-zip /pfad/run-45817099578-attempt-1.zip \
  --attempt-2-zip /pfad/run-45817099578-attempt-2.zip \
  --attempt-2-job-log /pfad/run-45817099578-attempt-2-job-139902186688.log \
  --output /pfad/artifact-verification.json
```

Ohne `--attempt-2-job-log` bleiben ZIP-, Kopier-, JUnit-, APK- und
Quellbindungsprüfung vollständig aktiv; lediglich die erneute Prüfung des
ausgelassenen Gesamtlogs wird im Ergebnis als nicht ausgeführt gekennzeichnet.
Der Prüfer führt keine Builds, Emulatoren, Providerzugriffe, Downloads oder
Remoteänderungen aus. Seine eigene SHA256 ist im Ergebnisrecord gebunden.

## Unveränderte Originalleerzeichen

Die drei ursprünglichen Textbelege `attempt-1/gradle-failure.txt`,
`attempt-1/job-failure.log` und `attempt-2/native-failure.log` enthalten zusammen
vier Zeilenendleerzeichen. Sie bleiben für den exakten Byte-/Hashvergleich mit
den Originalen erhalten. Der Diff aller übrigen Änderungen ist ohne
Whitespacebefund; diese Originalprotokolle werden nicht nachträglich bereinigt.
