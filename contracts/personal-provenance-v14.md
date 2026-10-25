# Personal-Sync: ursprüngliche Anwendung (Datensatzformat 14)

Issue: #230.

## Verhandlung und Kompatibilität

`personal_notes_sync` und `personal_tasks_sync` bieten zusätzlich Version 14 an.
Nur die gemeinsamen **Datensatzformate** 1, 2, 3 und 14 sind für Request, Batch
und Report zulässig; die übrigen Capability-Versionen bezeichnen eigenständige
Erweiterungen und dürfen nicht als Datensatzformat ausgehandelt werden.
Die Auswahl berücksichtigt alle Module des Requests. Ein nur einseitig
angebotenes Format 14 führt zum bisherigen gemeinsamen Format zurück.

Format 14 erweitert Format 3. Notizanhänge, Aufgaben-UID, Eltern-UID und manuelle
Reihenfolge bleiben erhalten. Im `value` jeder Notiz und Aufgabe kommt genau ein
Pflichtfeld hinzu:

```json
{"origin_app":"notes"}
```

Erlaubt sind ausschließlich die Zeichenketten `"notes"`, `"organizer"` und `""`.
Die leere Zeichenkette bedeutet unbekannte historische Herkunft. Notizbücher
erhalten dieses Feld nicht. Formate 1–3 enthalten es ebenfalls nicht.

## Bedeutung und Persistenz

Neu erzeugte persönliche Einträge erhalten die erzeugende App. Bestehende Daten
werden nicht rückwirkend nach dem aktuellen Gerät oder letzten Absender markiert.
Eine bekannte ursprüngliche App bleibt bei späteren Bearbeitungen und beim
Abgleich erhalten. Ein bislang unbekannter Ursprung kann aus dem ausdrücklich
übertragenen Feld übernommen werden. Ein älterer Peer ohne Herkunftsfeld löscht
die lokal bekannte Herkunft nicht. Importquelle, Magnolienbaum-Quelle und letzter
Transportabsender bleiben unabhängige Angaben.

`origin_app` ist Bestandteil des vorhandenen kanonischen Projektionshashes und
damit der bestehenden Vektoruhr-/Konflikt-/Revisionslogik. Es gibt keinen
ungehashten Metadaten-Nebenkanal. Speichern und erneutes Laden erhalten den Wert.

## Geschützte Transportwege

Requests, Batches und Abschlussreports eines Laufs verwenden dasselbe exakt
gebundene Datensatzformat. Das gilt auch für Einzelversand, Phone-Content-Scope
und den privaten MCP-Notes-Actor. Die bestehenden Scope-/Actor-Umschläge behalten
ihre eigenen Versionsnummern. Anhangnachrichten bleiben Format 2, Löschvorschläge
Format 1. Freigaben, gekoppelte Schlüssel, Verbindungsfrische, Scope-Mitgliedschaft,
Eigentümerbindung, Ablauf, Abbruch und dauerhafte Speicherbestätigung bleiben die
Voraussetzungen für Datenübernahme und Erfolgsmeldungen.
