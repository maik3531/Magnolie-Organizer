# #128 – Atomare Runregistrierung und Outbox (Linux, 28.11.2026)

Basis `ef10322fc14664d9bb879c0d56bfafa3afe02e7c`. Acht neue Main-Commits seit 9188ac17: Tablet, Medien-/Dateipfade und Arbeitsstand. Linux magnolie_telefon.py, Baumwerk.kt, TelefonCoordinator.cs und TelefonStore.cs unverändert. TelefonWerk.kt für Medien geändert; retireInvalidPersonalActors weiterhin nur aktive Arbeit und historische Handoffs, nicht gewöhnlicher Completion-Kandidat. Die drei vorherigen Produktpatches bleiben nach Quellenvergleich ausstehend; nicht blind anwenden. Issue-Suchen queue_full, attachment staging capacity, active_auto_run ohne Treffer; #128 deckt Lauf-Deduplizierung und Wiederaufnahme ab.

## Reproduzierter Teilfehler

Die gewöhnlichen Linux-Sender _send_personal_sync und _send_personal_sync_run registrieren den Run separat VOR dem Outbox-Insert bzw. atomaren Batch-/Anhangsstaging. Bei vollem Postfach, nachträglich ungültigem Anhang oder SQL-Fehler bleibt ein dauerhaft gespeicherter auto_wifi-Run ohne Anfrage übrig. active_auto_run findet ihn auch ohne separaten Marker und nach Wiederöffnung. Der aktuelle 24h-Runablauf kann dadurch spätere Automatik blockieren, obwohl die Fehlerursache längst behoben ist. Kein Nutzergerätedefekt behauptet. Notwendiger Vorabfix für Marker 8, nicht dessen Implementierung.

Kandidat: gewöhnliche neue Requests mit explizitem remember_request-Flag in derselben SQLite-Transaktion wie Outbox-Insert speichern; bei Format2/3/14 gemeinsam mit vorhandenem Anhangs-/Batch-Staging. BEGIN IMMEDIATE schützt Lesen/Schreiben. Runidentität, Zeitgrenzen, Konfliktprüfung, separater Marker, Legacy-WLAN-Policy erhalten. Empfänger- und Actor-Pfade ohne Flag. Keine neue Freigabe, kein neuer Trigger, keine Änderung Time/Custom. Bei erfolgreichem Commit und anschließendem Crash erkennt die bisherige Fallback-Suche den Run. Kein Löschen eines bestehenden Runs auf Fehler.

## Tatsächlicher Hosttest

Fünf Originalmethoden wörtlich extrahiert; FNV-1a-64 (ASCII) vor/nach:

| Methode | vorher | nachher |
|---|---|---|
| queue | ec1c48166bb1b5d | 91027663b8cd5ef5 |
| queue_format2_run | 40cec0c6f9e9ee9f | 20cf8132504f0a21 |
| _personal_run_record | 5201f6e3cc0ab0da | 95cfef2b030d25ed |
| remember_personal_run | f20b5f24e0c05d2f | d9158175a63efc31 |
| active_auto_run | dc0309c8b718bd58 | dc0309c8b718bd58 |

Lokale Extraktion und Kandidat SHA-256 33e01b4b76a922178d4e3d4304b6323e5bee9c2e2ee8a4c234bbf111e516c5cc bzw. af6927476a4bcb18e69597fd23537a5aee410a37f9e077e8f84515c3d7dbc216. Kandidatenmethoden im Patch anhand obiger Bindung exakt identisch. Echte SQLite-Transaktionen, synthetische AES-GCM-Payloads, kontrollierte Zeit, vereinfachtes Metadaten-/Validierungsumfeld; Aufrufreihenfolge der Dienstpfade nachgebildet. Keine vollständige PhoneService-/Produktcrypto-Ausführung.

Vorher 4/9, nachher 9/9. Fünf rote Fälle vorher: Kapazität Einzelrequest, Kapazität Gruppe, nachträglich veränderter Anhang, SQL-Abbruch beim Einzelrequest und SQL-Abbruch beim zweiten Gruppeninsert nach Staging. Nachher keine Phantom-Runs; Rollback der Transfer-/Chunk-/Outbox-Zeilen; bei Kapazitätsfreigabe erfolgreicher Retry. Vier Gegenproben jeweils grün: Konfliktrun bleibt, bestehender Run bleibt bei Queuefehler, empfangene Laufzeit nicht verlängerbar, erfolgreicher Run ohne Marker nach Wiederöffnung erkennbar.

Hostlog-SHA256 vor dea404e335e098ec881ca7c600c2b6a7eaf255fbd2711ab390d4292f2fa3c4cf, nach 9fc568db99f839bf6e704abaa57e013d30ae5d9da2cb35169d982d4c7e88c88c. Im Patch zusätzlich zwei noch NICHT ausgeführte Vollmodul-pytest-Fälle mit echtem PhoneService und PhoneStore. GitHub-Hostname im Testcontainer nicht auflösbar; Connector liefert Text, kein vollständiger Checkout. Kein Vollmodul-/gesicherter Transport-/nativer Gerätetest und keine Integrationsfreigabe.

## Nächster Schritt

Einzelpatch isoliert anwenden (git apply --check) und `python -m pytest magnolie-organizer/pruefungen/test_personal_run_atomic_queue.py magnolie-organizer/pruefungen/test_personal_sync.py` ausführen. Realen Wire-/Restore-/Widerrufsschutz erhalten. Windows TelefonCoordinator.cs:947 registriert ebenfalls vor store.Enqueue; Notes TelefonWerk.kt:5287 vor Snapshot/Queue. Quellverdacht, keine Reproduktion; Notes kennt bereits rememberPersonalRunInDatabase und atomare andere Pfade. Danach vollständigen Marker-8-Vertrag mit Run-/Scope-/Settingsbindung implementieren, nicht bloß Parser öffnen. Android-Completion-Abnahme offen. Kein Produktmerge.

## Ausführbare Hostprobe (erneuter quellengebundener Lauf)

`host_probe.py` extrahiert die fünf tatsächlichen PhoneStore-Methoden per AST und prüft ihre FNV-Bindung selbst vor der Ausführung. Mit der ungepatchten Quelle:

```sh
python host_probe.py /pfad/zum/checkout/magnolie-organizer/bin/magnolie_telefon.py
```

Mit der gepatchten Quelle:

```sh
python host_probe.py /pfad/zum/checkout/magnolie-organizer/bin/magnolie_telefon.py --candidate
```

Benötigt Python und cryptography; ausschließlich temporäre Testdaten. In diesem Lauf auf den wörtlich gebundenen lokalen Extraktionen erneut tatsächlich ausgeführt: vorher Exit 1 (4/9), nachher Exit 0 (9/9). Hostprobe SHA-256 82bb70f0031d1db4363f6abeb17ffabc4665ed7be7358cf50307e575171f6ce7. Ergebnisprotokoll des Wiederholungslaufs: vorher SHA-256 0c08a1c53a76c1c1307f2608a969824ec8fa5ee2fe0a1ad5f90f123887049354; nachher 78166d4cae50c86d812a6e9527728ddcaa5ccd5a4661301daba4a64a99597343. Dies prüft bewusst nur Storemethoden und nachgebildete Dienstaufrufreihenfolge, nicht die Produktvalidierung oder Vollmodulpfade.
