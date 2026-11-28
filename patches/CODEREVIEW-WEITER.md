# Magnolie-Codereview – Fortsetzung

## Auftrag und maßgebliche Quellen

Der Nutzer Maik Walter hat die weitere Suche nach tatsächlichen Fehlern und sinnvollen Optimierungen sowie wiederkehrende Fortsetzung beauftragt. Der vereinbarte Lieferweg bleibt: reproduzierbare Befunde, geprüfte Patches und Belege in passenden bestehenden GitHub-Issues zur späteren Übernahme mit Codex. Keine eigenständige Zusammenführung in Produkt-main und keine Paketveröffentlichung aus diesen Reviewrunden.

Repository: https://github.com/maik3531/Magnolie-Organizer

Reviewzweig: work/open-issues-audit-20261127

Diese dauerhafte Fortsetzungsdatei: patches/CODEREVIEW-WEITER.md auf dem Reviewzweig.

Letzte vollständige Übergabe: patches/codereview-outbox-current-2026-11-27/README.md auf demselben Zweig.

Zentrale Issue-Übergabe: https://github.com/maik3531/Magnolie-Organizer/issues/113

Stand dieses abgeschlossenen Arbeitspakets: 27. November 2026. Es läuft aus diesem Paket kein ungesicherter Produktänderungsschritt mehr. Bei jedem neuen Lauf tatsächlichen aktuellen main und jüngste Issuekommentare lesen; diese historische Basis ist kein Ersatz für den frischen Vergleich.

## Neuester Arbeitsstand – Windows-Initialrequest (28.11.2026)

Main `66dbd86578b84f1236429d789a208f1d3e0e9675`, fünf neue Medien-/Datei-/Testregistrierungs-Commits seit df1b1106; keine Übernahme der bisherigen fünf Teilpatches erkannt. Windows-Teilbefund #128: separat gespeicherter Run bleibt bei Queuekapazitäts-/Insertfehler bestehen. SQL-Modell mit realer SQLite und Original-SQL: 3/6 → 6/6; **kein C#-Produktlauf**, keine Windows-24h-Blockade nachgewiesen. [Kandidat, Probe und Bericht](codereview-windows-auto-request-2026-11-28/README.md). Nur initialer Format-1/2-auto_wifi-Request atomar; Bridge sendet weiterhin vor Attachment-/Batch-Staging. Nächster Schritt: echte C#-Regression und vollständige Bridge-Transaktionsgrenze (spätere Fehler), danach offene Linux-/Notes-Vollmodul-/Lifecycle-Abnahme und Marker-8-Vertrag; bei fehlender Laufzeit unabhängige konkrete Quell-/Testaufgabe. Keine Markerbewerbung, kein Produktmerge.

## Neuester Arbeitsstand – Notes-Initialrequest atomar (28.11.2026)

Main `df1b1106422277049ef18c6993494f1aa78e2a0d`, ein neuer Medien-/Galeriecommit seit ef10322f. Vier frühere Kandidaten durch diese Änderung nicht übernommen. Neuer #128-Kandidat für gewöhnliche legacy auto_wifi-Starts in Notes: Snapshot vor Registrierung, Run/Request/Batches/Anhänge in einer Transaktion. Kontrollierter Kotlin-Host mit Doubles 2/7 → 7/7, **keine echte Android-SQLite-/Service-Abnahme**, neue Robolectric-Regression im Patch noch nicht ausgeführt. [Einzelpatch und Nachweis](codereview-notes-auto-atomic-2026-11-28/README.md). **Nächster konkreter Schritt:** Windows-Quellverdacht RememberRun vor Enqueue/QueueDirection, gezielt reproduzieren; bei geeigneter Umgebung zuerst Linux-Vollmodul- und Notes-Datenbank-/Lifecycle-Tests nachholen. Danach Marker 8 vollständig, kein Marker bewerben, keine Parserlockerung. Notes-Completion-Integration weiterhin offen. Keine Produkt-main-Änderung.

## Neuester Arbeitsstand – atomare Laufregistrierung (28.11.2026)

Main `ef10322fc14664d9bb879c0d56bfafa3afe02e7c`, acht neue Medien-/Tablet-/Arbeitsstand-Commits seit 9188ac17; drei vorherige Produktpatches weiterhin ausstehend (Notes TelefonWerk inzwischen Medienänderungen, alten Patch nicht blind anwenden). Neuer #128-Teilbefund: gewöhnliche Linux-Autoläufe vor Outbox-/Batch-Staging separat gespeichert; nach Queuefehler blockiert dauerhafter Phantom-Run weitere Automatik. Host mit exakten Storemethoden, realer SQLite, Test-AES-GCM: 4/9 → 9/9. [Einzelpatch und Prüfnachweis](codereview-auto-run-atomic-2026-11-28/README.md). **Nächster konkreter Schritt:** Vollmodul-/Service-Regression (zwei neue pytest-Fälle im Patch), Windows-/Notes-Quellverdachtsfälle (RememberRun vor Queue), dann durchgehender Marker-8-Vertrag. Kein Marker bewerben, keine Parserlockerung. Kein Vollmodul-/native Abnahme; Android-Completion offen. Historische Marker-8-Übergabe unten bleibt maßgeblich für den Vertragsrest.

## Neuester Arbeitsstand – Marker-8 (27.11.2026)

Geprüfter main 886da45683e6b7fcd7d1006371b9d048b192c490; anschließend frischer Vergleich bis 9188ac17d893e59b6da9b9b0e82abfa5b094472e mit ausschließlich Kontakt-UI-/Arbeitsstandänderungen. Frühere zehn Patches übernommen, drei neuere Produktpatches (#691, Desktop #128, Notes-Completion #128) noch nicht. ARBEITSSTAND.md und Windows tests/Program.cs geändert: alte Gesamtpatches nicht blind einpflegen. Notes-Completion-Basis unverändert; echte Android-Lifecycle-Abnahme mangels Gradle/SDK/Robolectric blockiert. Vorhandene Integrationstestfixture und Abnahmekriterien im neuen Bericht. Kein erneuter identischer Hosttest.

Unabhängiger Marker-8-Wire-Nachweis: Python-Originalzweige 14/18, vier Request-/Report-Fälle WLAN/Bluetooth rot trotz synthetischer Marker-Aushandlung. Legacy und unbekannte Trigger grün. [Bericht, Probe, Quellenbindung](codereview-auto-connection-2026-11-27/README.md). Kein fertiger Produktfix. **Nächster konkreter Schritt:** Linux-Notes-/Tasks-Request-/Report-Vertrag samt Runpersistenz und Autorisierung zusammenhängend implementieren, Vollmodul und gesicherten Transport prüfen; Marker erst nach gleichwertigem Notes-/Windows-Nachweis bewerben. Legacy-/Widerruf-/Restore-/Revisionsfälle erhalten. Keine bloße Parserlockerung, Zeit/Custom getrennt. Sobald geeignete Android-Testumgebung verfügbar, vorherigen Completion-Kandidaten vollständig abnehmen. Historischer Rest dieses Dokuments bleibt Quellenhistorie.

## Zuletzt geprüfter Stand

Die aktuelle Restserie wurde auf main 7c9f9395ac7fcac03b0ce229f9707643be4b06fa geprüft. Ihr Ergebnisbaum ist f4f9817658165bd84d434d34c7ddcce3f32486f4. Einzelserie und Gesamtpatch stellen rückwärts exakt die Basis wieder her.

Die ursprünglich gelieferten zehn Einzelpatches sind inzwischen vollständig beziehungsweise fachlich gleichwertig auf main übernommen: #566, #790, #844, #845 (zwei Patches), #395, #330 (zwei Patches), #192 und #148. Beide aufeinanderfolgenden Übernahmeprüfungen liegen in der letzten Übergabe. Zusätzliche Upstream-Verbesserungen bleiben erhalten, insbesondere lokalisierter ICS-Fehlertest, Tablet-Assertion, getrennte Geburtstags-Testgruppen, vollständige MCP-Toolnamen und Fokus im Web-Smoke-Test.

Die aktuelle Restserie enthält ausschließlich:

1. #691 – nur LAN-Warten erstattet einen Postfach-Budgetplatz.
2. #128 – begrenzte Desktop-Pumpfenster hinter nicht aktuell zugelassenen Actor-Daten.

Der gemeinsame Patch remaining-review-after-7c9f9395.patch hat 45.797 Bytes und SHA-256 7baaf9ede4c21fbaff3688e44ef3a82b689c53b93713abff316f91410a809945. Entweder diesen Gesamtpatch auf seine unveränderte Basis oder nur die jeweils noch fehlenden Einzelpatches anwenden, niemals doppelt. Auch diese Liste kann durch zwischenzeitliche Übernahme kleiner werden. Erst Code und Issues vergleichen, dann tatsächlich fehlende Schritte bearbeiten. Ältere Zehner-, Elfer- oder Siebener-Gesamtstände sind historische Prüfstände und dürfen neuere Upstream-Arbeit nicht zurückdrehen.

## Neue abgeschlossene Teilbefunde und Grenzen

#691: 70 wartende LAN-Einträge vor erlaubtem Fernziel bei regulärem Kontingent 64 reproduziert; ursprüngliche Basis 15/5, endgültiger Patch 20/0. Der breitere Erstkandidat wurde verworfen. Betroffen ist der vorbereitete Target-37-LAN-Pfad; normaler Notes-Quellbau bleibt Target35. Keine installierte APK-Regression behaupten. Vorhandene Legacy-Vorbereitung bleibt unverändert. Die Belege liegen zusätzlich im unveränderlichen Artefaktcommit 00bda7cb9451e6d167f0be6a9654b68f881b91e9 unter patches/codereview-notes-quota-2026-11-27, Issuekommentar7228161134 in #691.

#128-Teilpatch: 65 fällige geschützte Actor-Umschläge verdecken gewöhnlichen Statusauftrag. Kontrollierte Linux-/C#-Produktproben: vorher 0/0/0, nachher 0/0/1 Sendungen beziehungsweise0/0/430 verschlüsselte Bytes. Alle Actor-Umschläge unverändert, null Actor-Versuche. 12 neue und 10 bestehende Python-Fälle, eine neue C#-Gruppe mit 11 Szenarien und fünf bestehende C#-Gruppen bestanden. Der erste Python-Cursor-Kandidat wurde nach drei negativen Reihenfolgefällen verworfen; endgültig vor Auswahl bei aktuellem Owner zum Kopf, von fortgesetzter Seite niemals Actor senden, Owner vor Cursorübernahme erneut prüfen. Windows-Quellhost lief unter Linux, nicht als native Windows-Abnahme.

Die drei neu zusammengesetzten UI-Prüfprogramme bestehen: Organisator10/10, Farbvektoren 24/24 über beide Oberflächen sowie beide Legacy-Importprüfungen mit dem aktuellen Python-Codec. Keine unveränderten früheren Gesamtsuiten als neu ausgeführt ausgeben.

## Nächster konkreter Schritt

**Aktualisierung 27.11.2026:** Der Hauptzweig ist weiterhin `7c9f9395ac7fcac03b0ce229f9707643be4b06fa`; die beiden Restpatches sind noch nicht übernommen. Neuer #128-Teilbefund für Notes im Ordner `patches/codereview-notes-completion-2026-11-27` (README, Einzelpatch, Repro und Logs). Der gewöhnliche unvollständige Actor-Abschluss wird nach dem Speichern aus personalActorWork entfernt; der bisherige Verlust-Cleanup sieht nur aktive Runs und historische Handoffs. Kotlin-Methodenharness 5/8 → 8/8, separate echte SQLite-32er-Auswahl 65→1 gewöhnliches Ereignis nach simuliertem Stopp, 66 Zeilen erhalten. **Host-geprüfter Kandidat, kein vollständiger Telefon-Lifecycle-Nachweis**. Als nächstes den in dessen README genannten echten Robolectric-Integrationstest vorbereiten/ausführen, insbesondere privates Staging und gespeicherte Abschlussbelege erhalten; falls Abhängigkeiten fehlen, transparent kennzeichnen und den unabhängigen auto_connection-Vertrag untersuchen. Keine erneute identische Hostprobe ohne neue Eingaben. Danach gelten die folgenden weiteren Schritte.


1. Frischen main, AGENTS.md, ARBEITSSTAND.md, diese Datei und die jüngsten Kommentare von #113/#128/#148/#691 lesen. Bereits übernommene Patches erkennen; betroffene fremde Änderungen erhalten.
2. Den noch offenen Notes-Telefon-Fall im Rahmen #128 gezielt prüfen: TelefonQueue.due begrenzt vor den späteren Actor-Sendeguards auf 32. Regulär gestoppte Actors werden bereits mittels next_attempt_ms=Long.MAX_VALUE ausgeschlossen; dafür existiert ein Test mit 33 Frames. Ein anderer noch fälliger Bestand ohne aktuelle Kanal-/Owner-Zulassung ist bislang nur ein Quellverdacht. Erst eine tatsächlich mögliche Lebenszyklusfolge reproduzieren; nicht aus dem Desktop-Test eine Android-Regressionsbehauptung ableiten.
3. Danach im selben bestehenden #128 die durchgehende ausgehandelte Automatik prüfen. V9-Shared-Preferences kennen manual/wifi/connection, Marker8-/auto_connection-Hilfsbausteine existieren, aber die tatsächlichen Controller/Capabilities/Validatoren sind noch nicht durchgehend verdrahtet. Alte auto_wifi/wifi_only-Gegenstellen erhalten. Keine automatische Sendung heimlich als manual ausgeben und keine Rechte aus Einstellungswerten erfinden.
4. Die Magnolienbaum-Fernendpunkte bleiben vom Telefon-PersonalSync getrennt. Schon geteilte Notizänderungen können nach Speichern das vorhandene Postfach starten; periodischer Vollabgleich bleibt WLAN-gebunden. Beidseitiger Internetabgleich braucht echte Rückwegerreichbarkeit. Kein allgemeiner Relay-/NAT-/CGNAT-Weg ist durch einen Host-/Porteintrag hergestellt.
5. Weitere Reviewbereiche bei Bedarf aus den bestehenden offenen Issues auswählen: Zuverlässigkeit/Tempo, Import-/Export-Typen und Serienausnahmen, CalDAV/Nextcloud, Medien, Übersetzungen und Handbuch. Die ursprünglichen 106 Issues wurden bereits quellengebunden auditiert; nicht ohne neuen Anlass dieselbe abgeschlossene Prüfung wiederholen.

## Arbeitsweise für Folgeläufe

Pro Lauf ein konkretes überschaubares Arbeitspaket abschließen. Bestehende und geschlossene Issues samt dokumentierter Ablehnungen prüfen. Vor Änderungen ein passendes Issue zuordnen. Quellverdacht, tatsächlich reproduzierten Fehler, Konfigurationsfall und offene native Abnahme auseinanderhalten.

Alle Änderungen isoliert vorbereiten. Originale, fremde Änderungen, Pairings, Freigaben, Revisionen, Wiederherstellungsepochen, Richtung und Löschbehandlung erhalten. Keine zusätzlichen Bestätigungsdialoge oder neue Komfortfunktionen ohne Auftrag. Nach einmal bewusster Einrichtung soll die bestehende erlaubte Automatik kontrolliert weiterarbeiten.

Nur aussagekräftige betroffene Tests ausführen. Bei neuen konkreten Reviewbefunden gezielt ergänzen. Privaten/native Kandidatenumfang nicht als veröffentlichte Produktfreigabe ausgeben. Keine Installation, Signierung, Storeeinreichung, Release oder Änderung realer Nutzerdaten aus diesem Reviewauftrag ableiten.

Quellstand, getestete Bytes/Prüfsummen, Ergebnis, offene Grenzen und nächsten konkreten Schritt dauerhaft sichern. Patches und Belege auf einem passenden Reviewzweig sichern, aus GitHub erneut prüfen und im passenden Issue verlinken. Bestehenden Reviewzweig nur mit erwarteter Elternrevision fortschreiben; konkurrierende Änderungen frisch lesen und erhalten.

Vor Ende jedes Arbeitspakets diese Fortsetzungsdatei aktualisieren. Falls ein Kontext-/Lauflimit droht, zuerst den tatsächlichen Zwischenstand mit genauem Wiederaufsetzpunkt sichern. Nicht behaupten, ohne Laufereignis weiterzuarbeiten oder eigenständig ein Chatlimit beseitigen zu können. Ein neuer Lauf soll auf diesen überprüfbaren Dateien aufbauen und keine Wiederholung allein wegen fehlender Gesprächserinnerung beginnen.

Wenn bereits sichtbar dieselbe Prüfung aktiv läuft, keinen parallelen Schreib-/Testlauf beginnen. Zugriffs- oder Freigabesperren nicht umgehen; den betroffenen Schritt samt Grund dokumentieren und verfügbare sinnvolle unabhängige Arbeit fortsetzen. Berichte in Deutsch über tatsächlichen Fortschritt oder einen konkreten Blocker; keine unveränderten stündlichen Erfolgsmeldungen erfinden.
