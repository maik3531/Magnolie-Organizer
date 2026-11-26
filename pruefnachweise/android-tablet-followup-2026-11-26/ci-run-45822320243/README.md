# CI101: APK-Gate und native Provider-Prüfstufe bestanden

Dieser Nachweis gehört zum [Actions-Lauf 45822320243](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45822320243),
Workflowlauf 101, Versuch 1 vom 26. November 2026. Der
[Tabletjob 139917463400](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45822320243/job/139917463400)
und der Gesamtlauf sind erfolgreich. Das explizite Ziel war
`tablet-system-records` unter API34/`google_apis`.

Das vollständige bestehende APK-Buildgate und anschließend die tatsächliche
native Kontakt-/Kalenderprovider-Prüfstufe wurden bestanden. Der Nachweis
bleibt auf diesen geprüften Stand und diese Providerstufe begrenzt;
`nativeAcceptance=false`, `googleAcceptance=false` und
`productionRelease=false` bleiben erhalten.

## Getesteter und verifizierter Quellstand

| Bindung | Wert |
|---|---|
| Commit für Port und Desktop | `7a7d90b04796cf338b98f0fdbb87e8da1c967043` |
| Git-Tree | `06c1a8cf6f115908dc21252682c2a358246f2cb7` |
| Projektion | `dbe502cf4ad4661be79dca584c120d8623676cf8be5c3ff0d61eba840b676c09` |
| Quellinputmenge, SHA256 | `86748803313288fe7b25428e13fe3e972bb6848323ee595d57588a3afe299f55` |
| Gepacktes Projektionsmanifest, SHA256 | `80879e5ffa5943a1dcaa4051a342e835bde461d3f6619c64135bb45e0d3b551a` |
| GitHub-Artefakt-ID | `15117579862` |
| Original-ZIP | 12.393.742 Bytes |
| Original-ZIP, SHA256 | `094747195afdd58a42fc3f83ef77046fef7e579d9daeedabc537eb9d6b585b72` |

Die Quellbindung verwendet `sourceMode=current-checkout`; kanonisch erzeugte
Kataloge sind mit `generatedCatalogsVerified=true` bestätigt. Der historische
Tag `v2.0.30` bleibt eine Vergleichsreferenz. Die ausgeführten Quellen sind an
Commit `7a7d90b04796cf338b98f0fdbb87e8da1c967043` gebunden.

[source-binding-selection.json](source-binding-selection.json) enthält alle
übergeordneten Originalfelder von `sources.json`. Nur die 462 Quellfile-/Blob-
Einträge sind ausgelassen. Die Auswahl ist ausdrücklich gekennzeichnet und
enthält Originalgröße und Original-SHA256. Der Prüfer vergleicht sie mit dem
vollständigen Record im ursprünglichen ZIP.

## APKs und vollständige JUnit-Reports

| Ergebnis | Anzahl |
|---|---:|
| Vollständige JUnit-XML-Reports | 42 |
| Tests | 303 |
| Failures | 0 |
| Errors | 0 |
| Skipped | 0 |
| Gesamtgröße der XMLs | 64.453 Bytes |

Alle 42 ursprünglichen XMLs sind unter [junit](junit/) bytegenau enthalten.
[artifact-verification.json](artifact-verification.json) weist jeden Report
mit ZIP-Pfad, Paketpfad, Größe, SHA256 und Einzelzählung aus. Auch die Anzahl
der tatsächlichen `testcase`-/Failure-/Error-/Skip-Elemente wurde gegen die
Reportattribute geprüft; die vollständige Summe stimmt mit `candidate.json`
überein.

| APK | Bytes | Verifizierter SHA256 |
|---|---:|---|
| `Magnolie-Organizer-Android-Tablet-Beta-2.0.30Beta-debug.apk` | 12.106.519 | `b1af0f5ac36afacd452e090b18cafd753eaa2f401709a1806777a27dcd0a3564` |
| `Magnolie-Organizer-Android-Tablet-Beta-2.0.30Beta-instrumentation.apk` | 269.266 | `71a97afe06085813f34c0f9d69353d623b54706c344ebc5dc79fa07610bf696f` |

Die tatsächlichen APK-Bytes wurden gegen das ursprüngliche
[candidate.json](candidate.json) und die Quellbindung geprüft. Außerdem
wurde der SHA256 des Kandidatenmanifests verglichen. Aus der echten App-APK
wurde `assets/projection.json` gelesen: Manifest-Digest und SourceHash stimmen
mit Quellbindung, Webproof und nativer Stage überein.

Die APKs sind Debug-Prüfkandidaten; Binärdateien und ZIP sind außerhalb dieses
kompakten Pakets gesichert. Das ursprüngliche Kandidatenmanifest wurde vor der
Providerstufe erzeugt und bleibt unverändert. Der tatsächliche native Erfolg
steht separat in den nachfolgenden Originalreceipts.

## Native Providerergebnisse und Serienausnahme #807

[system-records-receipt.json](system-records-receipt.json) und
[system-records.json](system-records.json) sind vollständige Originale aus dem
GitHub-Artefakt; beide enthalten `passed=true`. Die native Stage meldete
`INSTRUMENTATION_CODE: -1`.

**11 Prüfgruppen wurden bestanden: zehn fachliche Gruppen plus Cleanup.**

1. Der Produktionsread verweigert Zugriff bei fehlenden READ-Rechten.
2. Discovery findet die lokale Kontaktquelle und beide eigenen Fixturekalender.
3. Echte Kontakt-Data-Zeilen liefern Namen, Telefontyp und Geburtstag.
4. Gleiche SOURCE_ID bleibt über eine tatsächlich andere RawContacts-Zeile stabil; die Row-Bindung ändert sich.
5. Eine geänderte SOURCE_ID in derselben Zeile erzeugt eine andere Record-ID bei unveränderter Row-Bindung.
6. Der ausgewählte Kalender bleibt isoliert; zeitgebundene halboffene und ganztägige UTC-Datumsgrenzen werden eingehalten.
7. Das westliche Instantfenster erhält den letzten ausgewählten ganztägigen Termin.
8. Das Verschieben eines echten Einzeltermins erhält dessen Identität.
9. Echte RRULE-Expansion und verschobene Ausnahme erhalten die ursprüngliche Instanzidentität.
10. Bereits gesetzte Android-CancellationSignals verhindern beide Reads vor dem Query.
11. Eigene Fixture-IDs werden entfernt; WRITE-Rechte bleiben danach abwesend.

Der ursprüngliche CI99-Befund wird unter
[#807](https://github.com/maik3531/Magnolie-Organizer/issues/807) verfolgt.
CI101 protokolliert jetzt die tatsächlichen Werte:

| Serienprüfung | Vorher | Nachher |
|---|---|---|
| Anzahl Instanzen | 2 | 2 |
| Instanz am 2030-04-01 | 09:00–10:00 | 12:00–13:00 |
| Record-ID der verschobenen Instanz | unverändert über den Vorgang | identisch zur ursprünglichen Instanz |
| Instanz am 2030-04-02 | 09:00–10:00 | 09:00–10:00, vollständig unverändert |

Die Originalreceipt enthält beide Record-IDs, die Vorher-/Nachherdaten und
die begrenzten tatsächlichen Parent-/Exception-Providerzeilen. Der Prüfer
kontrolliert zusätzlich `original_id`, `original_sync_id` und
`originalInstanceTime` gegen die Parentzeile.

Die Fixture verwendet bewusst synthetische Sync-Metadaten:
`recurrenceFixtureUsesSyncMetadata=true` und
`linkage=synthetic-sync-adapter`. **Ungesyncte lokale Serienausnahmen wurden
nicht abgenommen** (`unsyncedLocalRecurrenceExceptionsTested=false`).

## Cancellation, Berechtigungen und Cleanup

`cancelled-contacts` und `cancelled-events` wurden beide tatsächlich erreicht.
Zum jeweiligen Aufruf waren READ_CONTACTS und READ_CALENDAR erteilt. Die
Prüfung belegt bereits gesetzte CancellationSignals vor dem Providerquery;
eine laufende Query-Unterbrechung wurde nicht getestet.

Alle **19 protokollierten `product()`-Aufrufe**, einschließlich Vorbedingungs-
und Readbackprüfungen, erfolgten nach abgeschlossenem
`dropShellPermissionIdentity`, ohne aktive Fixtureidentität und ohne
WRITE_CONTACTS/WRITE_CALENDAR. Produktive Provider-Schreibzugriffe fanden
nicht statt. Die Schreibrechte dienten ausschließlich der Anlage, Mutation
und Bereinigung eigener synthetischer Fixturezeilen.

Der Cleanup entfernte zwei eigene RawContacts und zwei eigene Kalender.
Jeweils null eigene IDs blieben übrig; Shellidentität abgelegt und
WRITE-Rechte abwesend sind ausdrücklich in der Receipt bestätigt.

Die weiteren unveränderten Scopegrenzen lauten:

- `contactsSourceIsolationTested=false`: geprüft wurde eine lokale Kontaktquelle.
- `calendarSourceIsolationTested=true`: zwei eigene Kalender erlauben die tatsächliche Quellenabgrenzung.
- Berechtigungsdialoge, Live-Widerruf, In-flight-Cancellation und UI-Save-ACK wurden nicht abgenommen.
- Der Providerlauf belegt keine vollständige UI-/Touch-/WebView-/Tablet- oder Releaseabnahme und keine wechselseitige Synchronisierung.

## Originalbelege, Auswahlen und Kopierprüfung

[evidence-index.json](evidence-index.json) nennt die Herkunft, Größe und
SHA256 aller **48 bytegenau übernommenen Dateien**. Bei Original-ZIP-Mitgliedern
prüft das Skript zusätzlich die vollständige Bytegleichheit. Die beiden
Logauszüge [provider-progress.log](provider-progress.log) und
[instrumentation-success.log](instrumentation-success.log) sind unveränderte
zusammenhängende Ausschnitte aus dem vollständigen Joblog.

[run-record-selection.json](run-record-selection.json) ist eine ausdrücklich
gekennzeichnete Auswahl der ursprünglichen GitHub-Run-/Job-/Artefaktrecords.
Originalgröße und Original-SHA256 bleiben erhalten; überflüssige Repository-,
Owner- und Macjob-Payloads sind ausgelassen.

Das vollständige Joblog wird außerhalb des kompakten Pakets gehalten:

| Original | Wert |
|---|---|
| Job | `139917463400` |
| Größe | 321.828 Bytes |
| SHA256 | `950096cabf887e0c221da1bbad961d92ed9fd1fdbdc0eade9ae542aa4da934a3` |

## Tatsächlich ausgeführter reproduzierbarer Prüfer

[verify-artifact.py](verify-artifact.py) benötigt ausschließlich Python 3 und
seine Standardbibliothek. Er wurde mit dem echten Original-ZIP und dem
vollständigen Originaljoblog erfolgreich ausgeführt:

```sh
python3 -B verify-artifact.py \
  --artifact-zip ../attempt-1.zip \
  --job-log ../job-139917463400.log \
  --output artifact-verification.json
```

Die externen Eingabepfade können beliebig angepasst werden. Der erzeugte
[Verifikationsbericht](artifact-verification.json) enthält die SHA256 des
Prüfers selbst, vollständige JUnit-Dateihashes/-Zählungen, Kopierbelege,
APK-/Manifest-/Quellbindung und die geprüften nativen Teilresultate. Sein
SHA256 nach dem dokumentierten Lauf ist:

```text
08a7bddc52ed4a9e14417c33867c8528c759331ec7449169aa0b163e668395d2
```

Ohne `--job-log` bleiben alle ZIP-, Kopier-, JUnit-, APK-, Source- und
Providerprüfungen aktiv; nur die erneute Verifikation des ausgelassenen
Gesamtlogs wird dann als nicht ausgeführt ausgewiesen. Der Prüfer startet
keinen Build, Emulator, Providerzugriff, Download oder Remotevorgang.
