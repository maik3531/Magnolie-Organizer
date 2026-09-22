# Thunderbird-Anbindung

Die Windows-Ausgabe kann die in Thunderbird eingerichteten, beschreibbaren
CalDAV-Kalender und CardDAV-Adressbücher als Synchronisationsquellen verwenden.
Thunderbird übernimmt deren Authentisierung. Magnolie erhält weder Kennwörter
noch OAuth-Tokens. Eine eigene Google-OAuth-Registrierung für Magnolie ist für
diesen Weg nicht erforderlich.

## Einrichtung

1. Thunderbird **140 oder neuer** installieren und das gewünschte Google-Konto
   beziehungsweise den DAV-Kalender und das CardDAV-Adressbuch dort einrichten.
   Die Anmeldung und der Abgleich müssen in Thunderbird funktionieren.
2. In Magnolie **Einstellungen → Synchronisation → Thunderbird-Verbindung
   einrichten** wählen. Der Explorer markiert `Magnolie-Thunderbird.xpi`.
3. In Thunderbird unter **Add-ons und Themes** im Zahnradmenü **Add-on aus Datei
   installieren** wählen und diese Datei installieren.
4. Thunderbird geöffnet lassen. In Magnolie die Quellen aktualisieren und die
   gewünschten Kalender bzw. das Adressbuch mit Anbieter **Thunderbird** wählen.
   Den bisherigen direkten Google-DAV-Kennwortzugang deaktivieren; der
   ausgewählte Thunderbird-Zugang ersetzt diesen Versuch.

Magnolie erzeugt die Erweiterung aus den mitgelieferten Quellen. Die
Native-Messaging-Registrierung gilt nur für den aktuellen Windows-Benutzer.
Die portable Ausgabe muss am gleichen Ort bleiben; nach einem Umzug wird die
Registrierung durch erneutes Einrichten aktualisiert.

## Grenzen

- Die Erweiterung benötigt ein geöffnetes Thunderbird-Profil. Ein Profilwechsel
  führt nicht dazu, dass fehlende Quellen als leere Bestände behandelt werden.
- Die Anbindung verwendet Thunderbird-interne DAV-Anbieterschnittstellen. Bei
  größeren Thunderbird-Änderungen muss die Kompatibilität geprüft werden.
- Es werden nur eingerichtete HTTPS-DAV-Quellen angeboten. Eine Outlook-Mail-
  Anmeldung allein stellt keinen CalDAV-/CardDAV-Zugang bereit. Für echte
  Microsoft-Kontakte und Kalender wird in Issue #29 ein Zugang ohne eigene
  App-Registrierung untersucht.
- Eine bestätigte lokale Übertragung ersetzt keine Google-Kontoprüfung. Der
  reale Google-Abgleich bleibt in Issue #17 bis zu dessen Bestätigung offen.

## Entwicklung

`tests/thunderbird-bridge.js` prüft Quellenbindung, vollständige CardDAV-
Momentaufnahmen, bedingte Schreibzugriffe und die Begrenzung der Schnittstelle.
Die CoreTests-Gruppe `Thunderbird bridge` prüft Nachrichtenrahmen und
anbieterabhängige Kontaktkennungen. Der explizite Prüfbefehl `--thunderbird-live`
verwendet ein isoliertes `magnolie-test-*`-Konto und eigens angelegte
`MagnolieProbe`-Kalender/-Adressbücher; er ist kein automatischer Zugriff auf
persönliche Konten.
