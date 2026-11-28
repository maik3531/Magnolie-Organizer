# #128 – Linux: widersprüchliche gewöhnliche Empfangsmanifeste vor ACK ablehnen

Basis main 56efb37691b7732055e6b7e960addbe2fff7cf6d; Produktblob magnolie-organizer/bin/magnolie_telefon.py 5c3f7a3c8ff028b38b815d2b642f0cd2aceda43f, Vertrag magnolie_personal_sync.py 3843ad5c7f9e1aaf553971f465d0d7744d1d893f. Vier Main-Commits seit c7fb6b900; Linux-Telefonquelle und Vertrag unverändert, Notes-Telefonquelle enthält sechs neue Zeilen (Lifecycle). Keine erkennbaren Übernahmen der bisherigen Kandidaten im Delta; Notes vor Anwendung frisch prüfen. AGENTS und Arbeitsstand sowie letzte #113/#128/#691-Kommentare gelesen. Issue-Suche zu Anhang/Replay/Manifest/Postfach: #128 ist der passende bestehende Auftrag; #303/302 betreffen andere Lösch-/Restoresemantik.

## Befund und Kandidat
Die normale PhoneStore.stage_personal_batch-Methode persistiert Batch, Inbox und accepted-Dedupe vor der Manifestvorbereitung. Der Empfänger _prepare_format2_aggregate_locked bildet danach eine SHA-256-Map (Last wins); attachment_chunk sucht dagegen den ersten passenden Deskriptor. Widersprüchliche Größen/MIME desselben Hashs können daher die Staginggrenze passieren. validate_attachment_descriptor/validate_value prüfen einzelne Deskriptoren und ID-Dubletten, keine hashbezogene Konsistenz über den Run. Kein echter Peer-/GUI-Datenverlust nachgewiesen.

Enger Patch prüft während der bestehenden Stagingtransaktion alle bereits vorliegenden gewöhnlichen Format>=2-Records je Peer/Run/Richtung. Widerspruch wirft speziellen ValueError und rollt den neuen Batch samt Inbox/Dedupe zurück. Bestehender Empfangshandler fängt ValueError vor dem accepted-ACK als rejected/invalid_schema ab; dieser vollständige Handler wurde nur gelesen, nicht ausgeführt. Bereits früher akzeptierte unvollständige Batches bleiben erhalten. Historische widersprüchliche Gruppen werden beim Replay ausschließlich für diesen spezifischen Fehler übersprungen; andere Gruppen bleiben verfügbar. Keine fremden Daten löschen, kein erfolgreicher Commit/Report vorgeben, normale bestehende Ablaufbereinigung bleibt unverändert. Kein terminaler negativer Run-Report für Altbestände implementiert; dessen vollständiger Wire-/Sender-/ACK-Lifecycle bleibt offen. Actor-Speicherpfad ausdrücklich ausgenommen, Format1 unverändert; keine neue Autorisierung, Trigger, Marker oder Restoreänderung.

## Ausgeführte Probe
Zwei exakte Produktmethoden, aus remote Text lokal übernommen und vor Ausführung über FNV-1a (ASCII/UTF8) gebunden: stage_personal_batch fc30c9907ad58a44, ready_personal_batches 299edb75c439d139. Python mit realem temporärem SQLite und Test-AES-GCM. Peer-/Actor-Klassifizierung, Runlookup, Auswahlvalidator, Canonical/Crypto-Helfer und Clock sind kontrollierte Doubles; synthetische Note-Records in der Struktur des Vertrags, keine vollständige Wirevalidierung. Test prüft acht Varianten (Größe/MIME, zusammen/getrennt, Reihenfolge), historische bereits persistierte widersprüchliche Gruppe plus andere gültige Gruppe und vier reguläre Fälle (gleicher Hash mit verschiedenen IDs/Namen, verschiedene Hashes, unveränderter Actor-Testpfad, Format1). Vorher 4/13, nachher 13/13; Assert/Exit 0 des Vergleichs. Bei frischen Konflikten vergleicht der Test sämtliche vier Tabellen vor/nach Fehlversuch, historische Gruppe bleibt bytegleich und andere Gruppe wird geliefert. Vorher wurde die historische Gruppe im Ready-Ergebnis mitgeliefert; kein tatsächlicher Replay-Ausnahmeabbruch behauptet. Patch drei Hunks auf vollständigem Remote-Quelltext vorwärts und rückwärts bytegleich geprüft. Keine vollständigen Produkt-/Geräte-/Transporttests: Checkout-Netz DNS blockiert, .NET nicht verfügbar.

Wiederholung auf gepinnter Basis:
```sh
gzip -dc patches/codereview-linux-receive-manifest-2026-11-28/probe.py.gz > /tmp/magnolie-receive-probe.py
python /tmp/magnolie-receive-probe.py magnolie-organizer/bin/magnolie_telefon.py
```
Probe führt beide Varianten im Speicher aus. Nicht auf bereits gepatchter Quelle starten.

Prüfsummen (SHA256, Gitblob):
- receiver.patch 56d66ec8f798bd380b8c8489d103ffc97cd833cbdab5739ef617f5ce363c7395 / d2388891ffa9055ef6fc4ffadfe8b81cc2578e0c
- probe.py.gz 35280bc5726e72ae0db7fb282e9bba41ec9665dc12328963bfb0fc95e3702ed4 / 30a9327d5dc073eb0ac47b1e4986b4ebdf31e22b
- entpackte Probe a3430546c9626e11470636acc6eeb231e876946a167d6bef87a3c07c5571295d / 8efa5b4596d5a629a5f83dc0b18f38762393915e
- results.log af113ae0b769b6dd5c1f70733ccfc448628642ddfa67e4a303b16553852b8758 / d16bd7939906f5b6be2fd20a0cc83063e681f6f9

## Offene Abnahme
Echter PhoneStore und Wire-Handler mit zulässigen vollständigen Records, negativer ACK inkl. Senderfortschritt, out-of-order/Reply/Peer-Isolation, historische Gruppe mit vorhandenen Transferzeilen, normale Bereinigung und terminaler negativer Abschluss. Gewöhnlicher Einzelbatch-Sender, Windows-/Notes-Gegenstücke, vollständige Windows-Bridge-Transaktion, Marker-8-Vertrag offen. Keine produktive Übernahme. Der neu beauftragte internationale Feiertags-/Ferien-/Wasserzeichen-Prüfbereich wird separat, ohne Verlust dieses Sync-Aufsetzpunkts, als nächstes zeitnahes Paket begonnen. Dabei #432/#718/#434/#113 und passende Feiertagsissues frisch abgleichen; echte Regionen/Provider/Datumsregeln und vorhandene Motive ermitteln, reproduzieren, isolierte Kandidaten; keine Standortfreigabe, keine geratenen Daten.
