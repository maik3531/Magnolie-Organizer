# Notes #691: wartendes LAN darf andere freigegebene Wege nicht blockieren

**Basis:** `9de81cc10d72ca7b176b5c501ff20689cdd53c31`.

**Endgültiger Produktkandidat:** `e9f4a41c87c2ef708e0c357fa76e64b339c5e313`.
Der vorläufige, nicht veröffentlichte Kandidat `e6c4293` ist verworfen und soll nicht angewendet werden.

**Bestehendes Issue:** [#691 – Target-37-Migration](https://github.com/maik3531/Magnolie-Organizer/issues/691). Der neue Befund konkretisiert dessen Bedingung, dass fehlende LAN-Freigabe keine Postfachversuche verbraucht und Bluetooth nicht blockiert. Der umfangreichere automatische Gesamtabgleich aus [#128](https://github.com/maik3531/Magnolie-Organizer/issues/128) wird durch diesen Teilfix nicht als fertig bezeichnet.

## Reproduzierter Fehler

`Baumwerk.postfachAbarbeiten()` erhöht den Zähler `versucht` bisher vor der Prüfung, ob ein bekannter LAN-Weg überhaupt benutzt werden darf. Bei fehlender LAN-Freigabe bleibt eine solche Nachricht zwar ohne Fehlversuch und ohne Löschung im Postfach, verbraucht aber einen der höchstens 64 Versuche des gesamten Wartungslaufs.

Stehen mindestens 64 derart wartende Nachrichten vorne, werden spätere erlaubte Fernziel- oder Bluetooth-Nachrichten in keiner Wartungsrunde erreicht. Der Hintergrunddienst beginnt alle 30 Sekunden erneut mit denselben wartenden Einträgen. Auch die mehrmalige manuelle Postfachverarbeitung löst diese Reihenfolge nicht auf.

**Konkreter Defaultfall:** 70 wegen fehlender LAN-Freigabe wartende, bereits vorbereitete FS1-Nachrichten vor einer erlaubten öffentlichen Fernziel-Nachricht. In drei Wartungsrunden mit dem unveränderten Standardwert von 64 bleibt die Fernziel-Nachricht vor dem Fix ungesendet. Nach dem Fix wird sie genau einmal erfolgreich verarbeitet; alle 70 bereits vorbereiteten FS1-Fixtures bleiben mit unveränderten Feldern vorhanden.

## Korrektur

Der Produktfix lässt `versucht++` an seiner bisherigen Stelle und erstattet ausschließlich im Zweig für bekannte, auf LAN-Freigabe wartende Wege diesen einen Versuch mit `versucht--`. Eine solche Nachricht belegt dadurch keinen Zustellversuch. Alle anderen Arbeitsgrenzen bleiben erhalten, einschließlich leerer oder fehlgeschlagener Sendungsvorbereitung und eines danach fehlenden Partners. Echte zustellbare Versuche und Fehler wie ein unbekannter Weg behalten ihr vorhandenes Limit und ihre Fehlerbehandlung.

Der Patch verändert weder Berechtigungen noch Paarungen oder Transportauswahl. Er aktiviert keinen neuen Mobilfunk- oder Bluetooth-Abgleich. Er ermöglicht nur, dass der vorhandene Abgleich bereits erlaubte Wege hinter blockierten LAN-Wegen erreicht. Die Sieben-Tage-Behandlung alter Sendungen, Legacy-Unklarheiten, Rücksetzepochen und Widerrufslogik werden nicht erweitert.

Der LAN-Wartefall selbst löscht keine Nachricht und verändert Retry-Zähler oder Backoff nicht. Die im Test belegte Gleichheit sämtlicher Felder gilt für die bereits vorbereiteten FS1-Fixtures. Bei echten Legacy-Sendungen kann `sendungVorbereiten` schon vor der LAN-Prüfung einen Umschlag, `receiptProtocol` und Partnerzähler reservieren. Dieser bestehende Vorbereitungsschritt bleibt unverändert und ist im Ablaufharness eine kontrollierte Abhängigkeit.

## Welche Builds betroffen sind

Die Produktionsquelle verwendet regulär `targetSdk = 35`. Das neue lokale Android-Netzrecht wird im vorliegenden Code erst bei Android/API 37 und Target 37 erforderlich. Der konkrete fehlende-LAN-Freigabe-Zustand gehört damit zum ausdrücklich gebauten Target-37-Kandidaten aus #691. Aus der Host-Reproduktion wird **kein Fehlernachweis für ein installiertes reguläres Notes-Paket** abgeleitet.

## Ausgeführte Prüfung

Das identische Harness liefert auf der unveränderten Basis **15 bestandene / 5 fehlgeschlagene Fälle**, auf dem korrigierten Stand **20 bestandene / 0 fehlgeschlagene Fälle**.

Die fünf roten Fälle betreffen:

1. Erlaubte öffentliche Fernziel-Notiz hinter wartenden LAN-Einträgen.
2. Erlaubte Bluetooth-Notiz hinter wartenden LAN-Einträgen.
3. Den regulären Standardwert 64 mit 70 davor wartenden LAN-Einträgen.
4. Ein tatsächlich auf zwei Sendungen begrenztes Kontingent mit späterem Fortsetzen der dritten Sendung.
5. Widerruf des LAN-Rechts nach einer Sendung, während ein separat erlaubter öffentlicher Weg weiterarbeiten können muss.

Die übrigen Fälle prüfen unveränderte IDs, Nutzlasten, Epochen und Wiederholungszähler bereits vorbereiteter wartender FS1-Fixtures, ein Nullkontingent, das 30-Sekunden-Budget, spätere Wiederholungstermine, aufgegebene Nachrichten, ungeklärte Legacy-Zustellung samt Reihenfolge pro Partner, ausgeschaltetes Bluetooth, Wiederherstellung und Dienstgeneration vor Transportzulassung, Wiederherstellung während einer Zustellung, unbekannte Wege, beschädigte Nutzlasten, fehlende eigene Identität und Unterbrechung. Drei zusätzliche Grenzfälle prüfen ausdrücklich, dass eine `null`-Rückgabe der Vorbereitung, deren `IllegalArgumentException` sowie ein danach fehlender Partner weiterhin das ursprüngliche Kontingent verbrauchen und nicht beliebig viele vorbereitende Arbeiten vor einem späteren erlaubten Frame ausführen.

Ein unabhängiger Review hatte diese drei zusätzlichen Arbeitsgrenzen am ersten Kandidaten beanstandet. Das erweiterte unveränderte Harness bestätigt den Befund: auf `e6c4293` bestehen 17 Fälle, genau die drei neuen Grenzfälle scheitern. `superseded-e6c4293/` erhält diesen Nachweis. Der endgültige Kandidat erstattet deshalb ausschließlich den LAN-Wartefall und besteht alle 20 Fälle.

### Tatsächlich ausgeführte Produktquellen

`run_queue_fairness.py` übernimmt unverändert aus dem jeweils angegebenen Quellstand:

- `postfachAbarbeiten`, `fehlversuch` und `aufgeben` aus `Baumwerk.kt`;
- die tatsächliche Klasse `Sendung` einschließlich der Bedingung `brauchtPruefung`;
- die Methode `WlanTransport.wartetAufLan`;
- die vollständige reine Java-Klasse `LanRegel`.

Der echte Kotlin-Compiler 2.4.21 und die vorhandene OpenJDK-21-Laufzeit führen diese Quellen aus. Java wurde über das vorhandene `jdk.compiler`-Modul mit Quell-/Bytecodeziel 17 kompiliert; das ist keine vollständige `--release 17`-API-Abnahme.

Speicher, Android-Berechtigungszustand, Nutzlastparser und Zustellung sind kontrollierte Gegenstellen. Die synthetische monotone Uhr macht das bestehende Zeitbudget deterministisch überprüfbar. `LanRegel` klassifiziert die lokalen/öffentlichen numerischen Fixtureadressen tatsächlich; die Tests stellen keine Netzwerkverbindung zu diesen Adressen her.

### Wiederholung

Mit vorhandenen Kotlin-Compiler-/Laufzeit-JARs:

```sh
python3 run_queue_fairness.py --repo /pfad/zum/quellstand --compiler-dir /pfad/zu/kotlin-jars --output /pfad/zum/ergebnis
```

`before/` und `after/` enthalten die erzeugten Kotlin-Fixtures, vollständige Compiler- und Ergebnislogs sowie SHA-256-Manifeste der tatsächlich ausgeführten Quellteile. Die Produktmethode wird nicht im Prüfer nachprogrammiert.

## Grenzen

Keine vollständige Android-/Gradle-/Robolectric-Abnahme, keine reale Android-Routenprüfung, keine signierte FS1-Ende-zu-Ende-Übertragung, keine echte Mobilfunk-/Routerverbindung und kein physisches Telefon. Die Transport- und Speicherschichten des Harness sind kontrollierte Abhängigkeiten; seine erfolgreichen Fälle dürfen nicht als native Geräteprüfung ausgegeben werden.

Die weiterhin nötige native Kandidatenprüfung umfasst Target 37 mit bewusst verweigerter LAN-Freigabe, vorher eingerichteter erlaubter Bluetooth- oder öffentlicher Gegenstelle, einem belegten Postfach von mehr als 64 wartenden LAN-Sendungen sowie einen anschließenden Widerrufs- und Wiederanlauffall. #691 bleibt für diese Abnahme und seine übrigen Migrationskriterien offen.
