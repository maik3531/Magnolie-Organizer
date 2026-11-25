# Linux #753: Fotoempfang messen

Diese ausschließlich testseitige Diagnose misst den synthetischen automatischen
WLAN-Fotoempfang mit dem Original-Worker. Sie ändert weder Produktcode noch
Freigaben, Protokollfristen, Speicherbelege oder Dauerhaftigkeitsprüfungen.
Das bisherige `ended.wait(12)` bleibt die einmalige Ereignisfrist. Ein Timeout
bleibt ein fehlgeschlagener Test; kein zusätzlicher Übertragungsversuch wird
für den Bericht gestartet.

## Ausführen

Im Repository-Hauptverzeichnis, mit den bestehenden Python-Testabhängigkeiten
(insbesondere pytest, cryptography und Pillow):

```bash
python3 -m pytest -q -p no:cacheprovider \
  --photo-receive-timing=/tmp/magnolie-753.json \
  'magnolie-organizer/pruefungen/test_media_support_draft.py::test_actual_reader_joins_only_original_wlan_after_acks_and_never_uses_outbox[wifi-phone_to_pc-images-True]'
```

Das Ausgabe-Elternverzeichnis muss existieren. Für jeden getrennten Lauf eine
eigene Datei verwenden. Den Diagnosefall isoliert und ohne parallele pytest-
Worker ausführen. Ohne `--photo-receive-timing` werden keine Methoden umhüllt und
keine Diagnose-Datei erzeugt. Die Option erfasst ausschließlich die oben
bezeichnete automatische Bildvariante; andere Parametervarianten bleiben ohne
Messung.

Der JSON-Bericht wird auch bei einer normalen Assertion-Verletzung geschrieben.
Ein Prozessabbruch wie SIGKILL kann die spätere Dateiausgabe verhindern.
Die unveränderte Vergleichsmessung erfolgt mit demselben Befehl ohne die Option.

Die Recorder- und Verdrahtungstests können getrennt ausgeführt werden:

```bash
python3 -m pytest -q -p no:cacheprovider \
  magnolie-organizer/pruefungen/test_photo_receive_timing.py
```

## Messfenster und Ereignisse

Die monotone Uhr `perf_counter_ns` ist von den Protokolluhren unabhängig.
Die Messung beginnt unmittelbar vor dem Senden der lokalen Dateifreigabe-
Kontrollnachricht im bereits vorbereiteten Fixture. Damit sind automatische
Anlaufzeit und die ersten Status-/Discovery-Schritte enthalten. Die Zeitmarke
`deadline_wait_started` bezeichnet den Beginn der weiterhin zwölf Sekunden
langen Ereigniswartephase. `wait_elapsed_ns` ist deren beobachtete Dauer bis zum
Snapshot; nach einem Timeout kann die Prozessplanung diesen Zeitpunkt geringfügig
hinter die nominelle Grenze verschieben.

Unmittelbar nach Rückkehr von `ended.wait(12)` werden Phasen, Ereigniszähler und
Zeitmarken unter demselben Recorder-Lock eingefroren, vor der Assertion und vor
dem Aufräumen des Fixtures. Spätere Saved-/End-Ereignisse und Aufräumarbeiten
verändern diesen Beleg nicht. Erst nach dem Testablauf wird JSON geschrieben.
Der Recorder ruft für den Snapshot keine produktiven Status-, Fortschritts-
oder Berechtigungsfunktionen auf und wartet auf keinen Produkt-Lock.

| Feld | Bedeutung |
| --- | --- |
| `checkpoint_reached` | Die ursprüngliche Ereigniswartephase wurde ausgewertet. Bei früherem Abbruch: `false`. |
| `deadline_event` | Stets `activity_ended`: die beobachtete Ereignisfrist gilt für das Ende der Aktivitätsanzeige. |
| `deadline_met` | Rückgabewert der ursprünglichen Warteprüfung; bei früherem Abbruch `null`. Kein allgemeiner Empfangs-Erfolgsstatus. |
| `automatic_mode` | Automatischer Modus war am Anfang der Warteprüfung gesetzt. |
| `chunk_requests`, `saved_messages` | Vom synthetischen Telefon vor dem Snapshot erfasste Chunk-Anforderungen und Saved-Nachrichten. |
| `peer_errors` | Vor dem Snapshot im synthetischen Gegenpart erfasste Fehler, ohne Fehlertext. |
| `activity_started`, `activity_ended` | Bis zum Snapshot erfasste Aktivitätsereignisse. |
| `status_requests`, `discover_requests` | Bis zum Snapshot erfasste Metadatenanforderungen. |
| `timing.marks_ns` | Erster erfasster Zeitpunkt jeder konstant benannten Marke relativ zum Messstart. |
| `timing.active_spans` | Beim Snapshot noch laufende gemessene Aufrufe, mit anonymer Threadspur und Schachtelungstiefe. |

`deadline_met: true` kann auch bei einem gehaltenen oder fehlgeschlagenen Auftrag
auftreten. Erst die weiterhin vorhandenen Testassertionen belegen `complete`,
die Originalbytes, genau eine Übertragung/einen Saved und den Schutz der lokalen
Bearbeitung beim anschließenden Wiederholungslauf. Den pytest-Ausgang deshalb
immer zusammen mit dem Bericht aufbewahren.

## Phasen lesen

Der Bericht trennt Annahme und Review, Chunk-Anforderung/-Verarbeitung,
Veröffentlichung, Speicherbeleg, Mapping-Commit und Empfangsabschluss. Dazu
kommen wiederholte Bindungs-, Präferenz-, Mapping- und Katalogprüfungen sowie
die Warte-/Aufrufschleife des Workers und Lesen/Senden/Warten des synthetischen
Telefons. `preferences.sync` und `mappings.sync` messen die originalen `_sync`-
Aufrufe getrennt; der globale `os.fsync`-Aufruf wird nicht ersetzt.

Pro Phase stehen `started`, `completed`, `errors`, `active`, `inclusive_ns`,
`exclusive_ns` und `max_ns` zur Verfügung. Die Zeitwerte enthalten abgeschlossene
Aufrufe sowie die bis zum Snapshot abgeschnittenen Anteile aktiver Aufrufe.
`completed` zählt dagegen nur tatsächlich zurückgekehrte Aufrufe, einschließlich
der mit Exception beendeten. `errors` zählt Exceptions ohne Typ oder Inhalt.

**Inklusive Zeiten nicht addieren:** Eine Präferenzlesung kann innerhalb einer
Bindungsprüfung und diese innerhalb der Veröffentlichung liegen. Exklusive Zeit
zieht direkt verschachtelte gemessene Aufrufe desselben Threads ab. Sie enthält
weiterhin ungemessene Arbeit, Wartezeit und Messaufwand. Auch exklusive Zeiten
paralleler Threads dürfen nicht als Gesamt-Wandzeit addiert werden.
`worker.wait_and_call` umfasst ausdrücklich auch seine Predicate-Aufrufe, nicht
nur passives Warten. Ein aktives `peer.wait_readable` nach erfolgreichem Abschluss
ist das normale Warten des synthetischen Telefons auf weitere Nachrichten.

Für die Untersuchung eines roten Laufs zuerst `deadline_met`, Ereigniszähler und
`active_spans` betrachten, dann häufige und langsame Unterphasen vergleichen.
Die Messung hat eigenen Aufwand und liefert keine automatische Ursachenanalyse.
Ein grüner Lauf auf einem anderen Dateisystem widerlegt eine frühere
Fristüberschreitung nicht. Dieser synthetische Test ist keine native Geräteabnahme.

Es werden nur konstante Labels, Zähler, monotone Dauern und die genannten
booleschen Prüfergebnisse gespeichert. Pfade, Gerätekennungen, Foto-Inhalte,
Schlüssel, Argumente, Rückgabewerte und vollständige Fehlermeldungen bleiben
außerhalb des Berichts.
