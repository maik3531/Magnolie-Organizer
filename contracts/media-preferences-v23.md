# Gemeinsame Medien-Einstellungen (Refs #393, #394)

Die native `device_status`-Erweiterung **23** kennzeichnet die vollständig
angeschlossene gemeinsame Medienbedienung. Sie ersetzt weder die bestehenden
Foto-/Video-Erweiterungen 21/22 noch Datei-, Betriebssystem- oder Ordnerrechte.
Eine implementierte Quelle allein bestätigt keine synchronisierten Einstellungen.

`file_transfer.shared_settings` verwendet die gewöhnliche authentifizierte
Nachrichtenhülle und exakt `{"format":1,"settings":{...}}`. Unterstützte Felder:

| Feld | Werte | Sichere Voreinstellung |
| --- | --- | --- |
| `enabled` | boolesch, gemeinsamer Hauptschalter | `false` |
| `photos_enabled` | boolesch, Auswahl innerhalb des ausgeschalteten Moduls | `true` |
| `videos_enabled` | boolesch | `false` |
| `collection_mode` | `phone_inventory`, `entire_collection` | `phone_inventory` |
| `auto_mode` | `manual`, `wifi` | `manual` |
| `skip_deletions` | boolesch | `false` für neue Einstellungen, wie ausdrücklich beauftragt |
| `direction` | `phone_to_pc`, `two_way` | `phone_to_pc` ohne vorhandene andere Wahl |

Jedes Feld besitzt ein Register mit höchstens zwei Einträgen der tatsächlich
gekoppelten UUIDv4-Geräte. Ein Eintrag enthält exakt `counter` und `value`.
Zähler sind Ganzzahlen zwischen 0 und 9007199254740991. Nur eine ausdrückliche
Änderung erhöht den betreffenden Feldzähler. Empfang und Echo erhöhen nichts.
Ein behaupteter unbekannter/höherer eigener Eintrag, gleiche Zähler mit
abweichenden Werten, fremde Akteure sowie unbekannte Felder/Werte werden abgewiesen.

Es gelten dieselben geprüften Register-/Echo-Regeln wie bei persönlichen
Einstellungen, aber ein **getrennter Speicher und Nachrichtenraum**. Format 9 der
persönlichen Einstellungen wird nicht erweitert oder umgedeutet. Bei gleichzeitigen
Medienänderungen gilt pro Feld: Aus vor Ein, manuell vor automatisch und
Löschungen auslassen vor Löschungen berücksichtigen. Ein Feld darf keine
unabhängige Änderung eines anderen Feldes überschreiben.

Beide Geräte speichern eine überprüfte zusammengeführte Sicht, bevor sie diese
bestätigen oder für die Oberfläche veröffentlichen. Unbestätigte Änderungen
werden nicht als gemeinsame abgeschlossene Einstellung dargestellt. Die
geschützte Bindung umfasst das aktuelle Gerätepaar und seine native
Kopplungsgeneration; alte Einstellungen werden nach Neu-Kopplung nicht allein
durch einen behaupteten lokalen Eintrag angenommen.

Gemeinsame Einstellungen sind **Absicht, keine Datenberechtigung**. Lokale
Empfangserlaubnis am PC, aktuelle gespeicherte/unversperrte Buchautorität,
native Zielordner-Handles und Androids tatsächliche Vordergrund-/Medienrechte
bleiben unabhängige Bedingungen. Eine entfernte Einstellungsänderung erteilt
keine lokale PC-Schreibberechtigung, startet keinen Lauf und öffnet keinen
Betriebssystemdialog. Einträge für Zielpfade, Schlüssel, Berechtigungsbelege,
Löschbeweise oder Saved-Quittungen gehören nicht in diese Nachricht.

Der Hauptschalter „Foto- und Video-Synchronisation aktivieren“ steht über den
Zugriffsrechten und ist bei neuen Einstellungen ausgeschaltet. Solange er aus
ist, ist unabhängig von den gemerkten Unteroptionen keine Medien-Synchronisation
aktiv. Einschalten allein startet keinen manuellen Lauf; vorhandene eigene
Zugriffsrechte und die gewählte Betriebsart bleiben separate Bedingungen.

Die Oberfläche zeigt Zugriffsrechte, gemeinsame Synchronisationseinstellungen
und anschließend den manuellen Start. Standardziele werden ausschließlich auf
dem empfangenden PC aus seinen nativen Bilder-/Videoordnern bestimmt. Ein anderer
Ordner wird ausschließlich über dessen vorhandenen nativen Auswahldialog gewählt.
Kamera und Bildschirmspiegelung sind nicht Bestandteil dieser Erweiterung.

Innerhalb der Einstellungen stehen Bestandsumfang, manueller/automatischer Modus,
„Löschungen auslassen“, Übertragungsrichtung und anschließend die Ordnerauswahl.
Ein neuer nicht angehakter Auslass-Schalter ist keine Löschquittung und erlaubt
keine Löschableitung aus unvollständigen Inventaren. Vorhandene Richtungs- und
Löschentscheidungen werden durch die neue Oberfläche nicht auf Voreinstellungen
zurückgesetzt. Sicherungsordner gehören niemals zum synchronisierten Bestand;
das gilt rekursiv auch für ein optionales alternatives Sicherungsziel und für
weiterhin aufbewahrte frühere Sicherungsorte.

Diese Spezifikation dokumentiert den beauftragten Rest. Die Erweiterung darf
erst nach tatsächlichem Anschluss beider Geräte als verfügbar gemeldet werden.
