# #128 – Marker-8 Automatik: Wire-Vertrag und Integrationsgrenzen

Geprüfte Basis: 886da45683e6b7fcd7d1006371b9d048b192c490. Frischer Vergleich bis 9188ac17d893e59b6da9b9b0e82abfa5b094472e: drei neue Commits seit 7c9f9395, Medien-/Datei- und Kontakt-UI-Pfade. Keine Änderung an Baumwerk.kt, TelefonWerk.kt, TelefonCoordinator.cs, TelefonStore.cs oder magnolie_telefon.py; drei bisherige Produktpatches (#691, Desktop #128, Notes-Completion #128) noch nicht übernommen. ARBEITSSTAND.md und Windows tests/Program.cs wurden verändert: alte Gesamtpatches nicht blind anwenden. Keine Produktänderung in diesem Lauf.

## Vorheriger Completion-Kandidat

TelefonWerk.kt Blob 5985df6ff77e8f852cb4cfe8779a14d0b47c6774, TelefonDatenbank.kt 96c22633689dce456b72b6b22a49d629be2471c7 und Journal 54a7d4046b329efff4680fa3ae957bb80bd86a96 unverändert. Kein erneuter identischer Hosttest. Java/Kotlin vorhanden, kein Gradle/Android-SDK/Robolectric im Testcontainer; GitHub-Host dort nicht auflösbar. Vollständige Lifecycle-Abnahme offen.

Vorhandene echte verschlüsselte Queue-/Buch-/TCP-Fixture: PersonalSyncActorTransportTest.kt (3a71465ac126125fe9e600ff124fc11a92160ce7), synthetische v12-Quelle und Python-/Windows-Host. Sie prüft Datenreport/Attachments, nicht gewöhnlichen Löschabschluss nach Kanalverlust. TelefonWerk 425–561 erzeugt Decision-Zeilen, speichert Buch und hält Completion. stopPersonalActor 376–387 ruft Journal.retire und stopActorRunAndPrivateStaging 417–420; nur privater storagePeer(run) wird gepurgt. Journal.retire entfernt den In-Memory-Guard und setzt stopped; Completion-Wire-Metadaten werden erst in reapInactive explizit gelöscht. Das beweist noch nicht Erhaltung sämtlicher benötigter Belege bei Stopp/Rollback.

Echte nächste Abnahme: 65 gültige lokale Entscheidungen, Buch regulär speichern, Abschlussframes absichtlich nicht zustellen, ursprünglichen Kanal schließen. Native Buch-/Wiederöffnungs-Hashes, versiegelte Outbox-Zeilen, privates Staging und Completion-Belege vor/nach vergleichen; gewöhnliche Nachricht danach erreichbar. Gleicher Kanal mit Scope-Warten, abgeschlossener Run und kontrollierter SQL-Fehler als Gegenproben. Bestehende echte Fixture erweitern; keine realen Daten/Schlüssel.

## Konkreter unabhängiger Vertragsnachweis

Mit synthetisch beidseitig vorhandenem Marker 8 wählen die Produkt-Helfer auf WLAN und Bluetooth auto_connection. Produktive Validatorzweige verwerfen diesen Trigger in request UND report. Ausgeführt: python3 probe.py excerpt.py, Exit 1 erwartet, 14/18 bestanden. Vier rote Fälle: Request/Report je WLAN/Bluetooth; Legacy, unbekannter Trigger und fehlende Aushandlung grün. Kein beobachteter installierter Paketfehler, sondern Integrationsblocker bei künftiger Aktivierung.

Quelle magnolie_personal_sync.py, Blob 3843ad5c7f9e1aaf553971f465d0d7744d1d893f. Drei Helfer wörtlich übernommen; validate_body enthält unveränderte Request-/Report-Zweige mit gemeinsamem Eingang und Original-Return, andere Zweige für Hostlauf ausgelassen. FNV-1a-64 (ASCII) gegen entfernte Quelle geprüft: Helfer 988 Zeichen cc5692506d2b9246; Validator 4688 Zeichen d632f63f1976766a. SHA-256 der lokal ausgeführten Dateien: excerpt.py 289eaefdf28b542b0ba7e7e942b3d88be7167384da7faf0b2df2ec1e94e19eae; probe.py c238a889ecdacbb8d413fee626e4cedfb1dd0aefdc804daa53c6567473e8051e. Vollständiger Modul-Repro im Checkout: python3 patches/codereview-auto-connection-2026-11-27/probe.py magnolie-organizer/bin/magnolie_personal_sync.py. Vollmodullauf hier nicht ausgeführt. Absichtlich rote Diagnose, kein fertiger Fix/Freigabe-Gate.

## Verdrahtungsstellen

- Notes: PersonalAutoSync.kt Marker8/Triggerwahl; SharedSyncSettings.kt 18–28 akzeptiert connection. TelefonWerk.kt 971–1024 nur wifi; 5171–5200 nur manual/auto_wifi und alte Auto-Run-Deduplizierung. TelefonDatenbank.kt 135–139,1041–1054,1463 alte Trigger. PersonalSyncProtokoll.kt 146/325 alte Request-/Report-Trigger. Custom 76 und Time separat.
- Linux: magnolie_shared_sync.py 22 akzeptiert connection; magnolie_telefon.py 5503/7970 nur wifi-Projektion, 1871/8115/10164 alte Trigger trotz gespeicherten neuen Triggers in 295; magnolie_personal_sync.py 638/674 lehnt neuen Wire-Trigger ab.
- Windows: SharedSyncSettings.cs 40 akzeptiert connection; TelefonCoordinator.Shared.cs 49/105 und TelefonCoordinator.cs 1132 nur wifi-Projektion; PersonalSyncContract.cs 64–79 Marker-Helfer, 406/468 alte Request-/Report-Trigger. Custom 250 separat. Keine .NET-Ausführung.
- Bestehendes #128 umfasst genau diesen Vertrag; Issue-Suche nach auto_connection ergibt #128, keine Dublette.

Nicht nur Validatorlisten erweitern oder Marker 8 vorzeitig bewerben. Vollständige autorisierte Kette: aktuelle Sitzung und beidseitiger Marker, Eigentümer/Freigaben/Richtungen, Scope-/Settingsrevision, Triggerwahl, authentifizierter Runindex mit Transportpolicy, Laufdeduplizierung, Versand-/Empfangsprüfung, Report/ACK/Restore/Widerruf. Legacy auto_wifi bleibt wifi_only; fehlender Marker erlaubt keinen neuen Bluetooth-Autolauf; Einzelübertragung bleibt manual. Zeit/Custom/Medien getrennt. Kein NAT-/Relay-Versprechen.

Nächster Schritt: zusammenhängende Linux-Notes-/Tasks-Request-/Report-Implementierung samt Runpersistenz und Autorisierung, Vollmodulprobe plus gesicherter Transporttest. Marker erst nach gleichwertigem Notes-/Windows-Nachweis bewerben. Kein isolierter permissiver Parser-Patch. Android-Lifecycle-Abnahme bleibt eigener Blocker bis geeignete Gradle-Umgebung verfügbar.
