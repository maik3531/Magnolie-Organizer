# Medienangebot mit ursprünglicher Telefonreferenz (Refs #429)

`file_transfer.media_offer` ergänzt ausschließlich die Metadaten für ein
Desktop→Telefon-Medienangebot. Der gewöhnliche `file_transfer.offer` bleibt
unverändert und nimmt diesen neuen Nachrichtentyp nicht als gewöhnliche Datei an.
Der sichere, authentifizierte Umschlag bleibt gleich; maximal 262144 kanonische
UTF-8-Bytes und höchstens 60000 ms Gültigkeit, beim Empfang noch nicht abgelaufen.

Der Körper enthält exakt:

- `format: 1`
- `offer`: den vollständigen unveränderten Körper eines gewöhnlichen Angebots
- `settings`: den vollständigen aktuellen Acht-Felder-Mediensnapshot
- `media_type`: `images` oder `video`
- `mime_types`: genau eine passende Bild-/Video-MIME-Angabe pro Manifest-Datei-ID
- `originals`: ursprüngliche Telefonreferenzen, jeweils unter der neuen Datei-ID

Eine Referenz enthält exakt `source_epoch`, `photo_id`, `media_type`,
`manifest_sha256`, `file_id`, `original_size`, `original_sha256`, `receipt_sha256`.
Fremde IDs, doppelte Referenzen, falsche Typen und unvollständige Einstellungen
werden abgewiesen. Im Handybestandsumfang braucht jedes Mitglied eine Referenz;
der gesamte Bestand erlaubt auch neue Mitglieder ohne erfundene Telefonherkunft.
Reiner Import und eine reine Telefon→PC-Richtung erlauben kein solches Angebot.

Die Rekonstruktion des gewöhnlichen Angebots erhält Nachrichten-ID, Zeitgrenzen
und Manifest unverändert. Damit bleiben die vorhandenen Annahme-/Chunk-/Saved-
Bindungen erhalten. Die Metadaten erteilen keine Rechte und beweisen weder
Dateiinhalte noch ursprüngliche Telefonzuordnungen. Der native Empfang muss
den Snapshot gegen den tatsächlich bestätigten aktuellen Absichtsbesitzer
prüfen, dessen Identität bis zur Workeraufnahme erhalten und alle bestehenden
Buch-, Empfangs-, Originalreferenz-, Inhalts- und Veröffentlichungsprüfungen
unverändert durchführen.

Python, C# und Kotlin prüfen denselben kanonischen Testvektor in
`media-offer-v1-vectors.json`. Der explizite Android-Laufzeitanschluss ist mit
wirklich verschlüsselter Eingabe, nativer PNG-Veröffentlichung und Saved geprüft;
fehlende aktuelle Absicht, Inventarreferenz oder native Empfangszustimmung
bewirken keine Provideränderung. Das ist noch keine Freigabe des normalen
Produktionsdispatchers oder der gemeinsamen Betriebsbereitschaft. Die Ableitung
der MIME-Angaben aus tatsächlichen Ausgangsbytes, die Sender-/Dispatcher-
Zusammensetzung und die vollständigen Abschluss-/Wiederaufnahmewege bleiben offen.
