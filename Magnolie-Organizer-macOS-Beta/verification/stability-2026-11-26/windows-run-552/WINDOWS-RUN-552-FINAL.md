# Windows #552: abgeschlossener getrennter CI-Befund

Statusabfrage: **26. November 2026, 14:35:26.923–14:35:27.458 Uhr Europe/Berlin**. Vollständiges Joblog und Artefaktliste gelesen: **14:35:39.318–14:35:40.649 Uhr Europe/Berlin**. Die strukturierten API-Belege und ursprünglichen Logzeilen behalten UTC.

## Ergebnis und Quellenbindung

[Lauf #552 / 45820275770](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45820275770) ist **completed/failure**, Attempt 1. Er wurde durch den vorhandenen Push automatisch ausgelöst; diese Nachprüfung hat keinen neuen Lauf gestartet.

| Merkmal | Tatsächlicher Wert |
| --- | --- |
| Workflow | Windows x64, `.github/workflows/windows.yml` |
| Zweig | `work/macos-issue-fixes-20261126` |
| Quellcommit | `8c860a14f7e10904c1b3a159ae84619c2c24ba82` |
| Tree | `a47beb73ccbdaeb277359b04aacaf31d9fceea9c` |
| Job | [build / 139910440584](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45820275770/job/139910440584) |
| Laufstart Europe/Berlin | 26.11.2026, 13:30:27 Uhr |
| API `updated_at`, Europe/Berlin | 26.11.2026, 14:19:03 Uhr |
| Tatsächliche Abschlussausgabe, Europe/Berlin | 14:18:55.9927935 Uhr: CoreTests 551/552; Prozess Exit 1 um 14:18:59.0966425 Uhr |
| Erreichter fehlerhafter Schritt | 9 — Standalone-Quellarchiv bauen und aus dem Archiv testen |
| CoreTests | **551 von 552 Gruppen bestanden; genau eine Gruppe fehlgeschlagen** |
| Laufartefakte | **0** in der API-Liste; Uploadschritt übersprungen |

`updated_at` ist ein Metadaten-Zeitpunkt. Der Job-Wrapper liefert keinen genauen `completed_at`; dieser wird nicht erfunden. Die vollständige Logfolge reicht von 2026-11-26T12:30:31.0111903Z bis 2026-11-26T13:19:00.9237983Z.

## Tatsächlicher Fehler und Einordnung zu #794

Der Fehler trat um **13:33:53 Uhr Europe/Berlin (12:33:53 UTC)** auf. Alle übrigen Gruppen liefen anschließend bis zur Gesamtausgabe weiter.

```text
2026-11-26T12:33:53.4295060Z   FEHLER Media support draft / original Windows WLAN reader and withdrawal (0.66 s)
2026-11-26T12:33:53.4295883Z          System.IO.IOException: The process cannot access the file 'phone.db' because it is being used by another process.
2026-11-26T12:33:53.4296700Z    at System.IO.FileSystem.RemoveDirectoryRecursive(String fullPath, WIN32_FIND_DATA& findData, Boolean topLevel)
2026-11-26T12:33:53.4297369Z    at System.IO.FileSystem.RemoveDirectory(String fullPath, Boolean recursive)
2026-11-26T12:33:53.4298649Z    at MagnolieOrganizer.Windows.Tests.PhoneCameraParentTests.Fixture.Dispose() in C:\Users\runneradmin\AppData\Local\Temp\magnolie-source-d3d29a088cac4031a9ad95098884084b\standalone\Magnolie-Organizer-Windows-2.0.30\tests\PhoneCameraParentTests.cs:line 93
2026-11-26T12:33:53.4300689Z    at MagnolieOrganizer.Windows.Tests.SharedSyncTransportTests.NativeMediaSupportAsync() in C:\Users\runneradmin\AppData\Local\Temp\magnolie-source-d3d29a088cac4031a9ad95098884084b\standalone\Magnolie-Organizer-Windows-2.0.30\tests\SharedSyncTransportTests.cs:line 201
2026-11-26T12:33:53.4302572Z    at MagnolieOrganizer.Windows.Tests.TestRunner.RunAsync(String filter) in C:\Users\runneradmin\AppData\Local\Temp\magnolie-source-d3d29a088cac4031a9ad95098884084b\standalone\Magnolie-Organizer-Windows-2.0.30\tests\TestRunner.cs:line 23
```

Dies reproduziert die bereits in [#794](https://github.com/maik3531/Magnolie-Organizer/issues/794) dokumentierte Cleanup-Ausnahme mit derselben Gruppe, `phone.db` und denselben beiden Quellstellen. Der frühere Befund war an [Lauf 45788221321](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45788221321) auf `689266570cda17f463132a182c02d78ea732dfbd` gebunden; dieser neue Nachweis gehört ausschließlich zu #552 auf `8c860a14`.

Die Verantwortlichkeit eines zusätzlichen SQLite-ReadWrite-Pools ist weiterhin eine konkrete, zuvor dokumentierte Hypothese. Dieser Logabgleich beweist weder diese Ursache noch einen Fix. Kein Windows-Quellcode wurde geändert; kein Issue wurde kommentiert oder geschlossen.

## Bestandene Teilprüfungen und Grenzen

Vor dem CoreTests-Abschluss bestanden die bytegebundene Zeitzonen-Checkoutprobe (1 Test), die Quellkontext-/Wiederherstellungsfälle, die Standalone-Asset- und Cold-Timezone-Rezeptfixtures, eine im Log mit **3 passed** ausgewiesene pytest-Gruppe sowie die Windows-Quell-/Privatpfad-/Provenienz-/Prüfsummenfixtures aus #787. Die Identität des Installerkandidaten wurde geprüft; eine Installation fand dabei ausdrücklich nicht statt.

Der erwartete `Reviewed timezone input differs`-Traceback gehört zur anschließend als bestanden ausgewiesenen Tamper-Ablehnungsprobe; er wird nicht als weiterer fehlgeschlagener CoreTests-Fall gezählt. Die **2 positiven und 52 negativen Release-Audit-Fixtures** sind ein verschachtelter Teilumfang der CoreTests. Diese Zahlen werden nicht zu einer erfundenen Gesamtzahl eindeutiger Tests addiert.

Der Standalone-Archivschritt insgesamt ist **fehlgeschlagen**. Unsigned ZIP, NSIS, Signierzertifikat, offizielles ZIP/Installerpaket, Artefaktisolation und Upload wurden übersprungen. Es gibt deshalb keinen erfolgreichen Windows-Paket-/Installations-/Release-Nachweis dieses Laufs.

Die Ausführung verwendete Microsoft Windows Server 2022 Datacenter (10.0.20348), Runner 2.338.2, das installierte .NET SDK 8.0.408, Bun 1.4.4 und JSDOM 26.1.0. Die Angaben stammen aus dem tatsächlichen Joblog.

## Vollständigkeit und Belegdateien

- [Strukturierter vollständiger Nachweis](windows-run-552-final.json): enthält Ergebnisse, Schritte, Quellenanker und den **vollständigen normalisierten Logtext**.
- [Vollständiges Originaljoblog](job-139910440584.log): UTF-8-Repräsentation der unveränderten, vom Connector dekodierten Zeichenfolge; BOM und CRLF erhalten. Keine Behauptung über unbekannte Bytes eines ZIP-/HTTP-Downloads.
- [Vollständiges normalisiertes Joblog](job-139910440584.normalized.log): nur führendes BOM, CRLF und ANSI-Farbcodes normalisiert. Öffentliche Hosted-Runnerpfade bleiben erhalten.
- [GitHub-Abschlussdaten](github-final-capture.json): gelesene Run-, Jobschritt- und leere Artefaktdaten; der nicht unterstützte zusätzliche Jobdetail-Endpunkt ist ausdrücklich als fehlgeschlagene Zusatzabfrage vermerkt.

| Logfassung | Bytes | SHA-256 |
| --- | ---: | --- |
| Original | 127333 | `d2c4887b4495c502b905e19969f9995b3280386d542f5153873ec1bb6d440c27` |
| Normalisiert, vollständig im JSON eingebettet | 125732 | `93d24adb009fa049bad4105bef734b022413176e220c1790f122ee5f1f84bd91` |

Die 1164 Logzeilen enthalten öffentliche CI-Angaben und synthetische Testkontexte. Bereits von GitHub maskierte Werte bleiben maskiert; es wurden keine tokenisierten Download-URLs oder unmaskierten GitHub-Tokenmuster gefunden. In den eingebetteten Logtext wurden keine lokalen Scratch-Pfade eingefügt.

Die früheren Zwischenstandsdateien wurden unverändert erhalten. Dieser Abschlussbeleg wurde ausschließlich lesend aus dem bereits beendeten Windows-Lauf erstellt. Keine neue Prüfung, kein Fix, kein Main-Merge und keine Veröffentlichung. Der getrennte Mac-Kandidat bleibt #104 / `3f3ec069895dec254c53660d14e6851cb23077cd`; dessen Ergebnis wird hier weder abgefragt noch bewertet.

## Übernahme in den dauerhaften Nachweis

Die vier Daten-/Logdateien wurden bytegleich aus dem eingefrorenen Abschlusscapture übernommen. Die Lesefassung verwendet Europe/Berlin als Anzeigezeit; originale Logzitate und sämtliche JSON-/Logbytes bleiben unverändert. SHA-256 der ursprünglichen Lesefassung: `da3e2b793b6592fc679b600b9f524c3c8732aeb7c39db9afb01ec28b3968655a`. Dies fügt keine Testausführung oder native Freigabe hinzu.
