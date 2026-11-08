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
der MIME-Angaben ist beim expliziten Windows-Sender inzwischen an die tatsächlich
authentifizierten verschlüsselten Cachebytes gebunden: höchstens 1 MiB Präfix,
PNG/JPEG beziehungsweise MP4/QuickTime-Containererkennung, nie Dateiendungen.
Unbekanntes wird vor jedem Angebot und vor dem Anlegen des Versandjournals
abgewiesen; Cache, Original und alte Empfangshistorie bleiben erhalten.
Das ist eine Containeridentifikation, keine vollständige Inhalts-/Pixelprüfung:
diese bleibt beim nativen Empfänger vor der Veröffentlichung erforderlich.

Der Windows-Sender sendet den neuen Umschlag mit exakt geschütztem aktuellem
Acht-Felder-Snapshot und Originalreferenzen. Seine vorhandenen Annahme-, Chunk-,
Saved-, Ablauf-, Abbruch- und Journalbindungen verwenden weiterhin dieselbe
Angebots-ID und dasselbe Manifest. Fünf native Windows-Versandgruppen prüfen
diesen Weg, darunter eine echte umbenannte PNG mit zwei verschlüsselten Chunks
und unbekannter Inhalt trotz `.jpg`-Name ohne Ausgabe. Das ist noch kein
Produktionsdispatcher-/Android-Ende-zu-Ende-Nachweis. Android reserviert den
Umschlag inzwischen im normalen authentifizierten Nachrichtenverteiler und
übergibt ihn ausschließlich an die bereits vorhandene identische native
Verbindung. Chunkantworten erreichen direkt den auf sie wartenden nativen
Empfangsworker, ohne hinter dessen Warteoperation eingereiht zu werden. Ein
Angebot kann weder eine Verbindung noch eine aktuelle Medienabsicht oder
Empfangszustimmung herstellen. Der gewöhnliche source-only/Legacy-Zweig bleibt
empfangsgeschlossen. Der gemeinsame Factory-Zweig verbindet ab Android 30 die
bereits vorhandenen nativen Empfangshandler ausschließlich mit einem tatsächlich
aktuellen gemeinsam bestätigten eingehenden Absichtsbesitzer. Seine gespeicherte
Empfangszustimmung bleibt unabhängig und zunächst geschlossen; erst der echte
lokale positive native Dialog kann sie ändern. Native Verbindungsweiterleitung mit echter PNG-
Veröffentlichung/Saved sowie Ablehnung fremder Verbindung, normaler Dateiangebote
und fehlender Empfängerfactory sind geprüft; im echten Werk-Verteiler sind
reservierte Ablehnung ohne Bootstrap und vorhandene Kontrollaktivierung geprüft.
Ein zusätzlicher Test prüft inzwischen auch die tatsächliche Werk-Factory,
gemeinsame Absichtsabstimmung, native Kontrollabstimmung, positiven nativen
Zustimmungsdialog und den normalen Werk-Verteiler bis zur PNG-Veröffentlichung
und verschlüsselten Saved-Ausgabe. Nur dieser Test stellt die ansonsten gesperrte
gemeinsame Capability bereit. Dies ist kein physischer Telefon-/Desktop-
Ende-zu-Ende-Nachweis und keine Produktfreigabe dieser Capability. Die lokale
Bedienungsanbindung des Empfangsdialogs und die vollständigen folgenden
Abschluss-/Wiederaufnahmewege bleiben offen.

Die gemeinsame native Zusammensetzung und vollständigen Abschluss-/
Wiederaufnahmewege bleiben offen; Remote-Saved ist kein lokales Saved/END und
keine Berechtigung, den Ausgangscache zu entfernen.
