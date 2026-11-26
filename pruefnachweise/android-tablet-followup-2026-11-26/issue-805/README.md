# Enger Test-Kompilierfix #805

Der echte CI-Fehler steht im benachbarten Ordner `ci-run-45809316206`.
Die lokale Vorherprobe reproduziert exakt seine fünf `JSONObject.similar`-
Compilerfehler. Beim Compile steht das echte Android-37.2-API-JAR vor dem
JVM-JSON-JAR; die fehlende Methode wird nicht durch Classpath-Tausch verdeckt.

Nur drei bestehende Testdateien ändern ihre fünf Vergleichsaufrufe. Der neue
Testhelfer `JsonValueComparison.kt` traversiert vollständige Objekte und Arrays
über öffentliche JSON-APIs. Objekt-Schlüsselreihenfolge ist unerheblich;
Schlüsselmenge, Typen, Arrayreihenfolge und sämtliche Werte bleiben relevant.
JSON-Null und ein fehlender Schlüssel sind verschieden. Zahlen werden unabhängig
vom Produktserializer exakt verglichen: große Ganz-/Dezimalzahlen bleiben genau,
Float/Double werden über ihren tatsächlichen binären Zahlenwert in BigDecimal
überführt. Keine doppelte Stringify- oder Double-Rundung dient als Orakel.

## Tatsächlich ausgeführt

- Vorher: dieselben fünf Compilerfehler, Exit 1.
- Nachher: Android-API-Kompilierung Exit 0, Kotlin 2.4.21/JDK21, JVM-Ziel17.
- 42/42 JUnit-Tests bestanden: DocumentRequests6, NativeCalendarFixture1,
  Vault17, VaultJson6 und neuer Vergleichshelfer12.
- Alle 38 zuvor kompilierten Produktquellen sind per Hash unverändert; ihre
  vorhandenen Klassen wurden nur nach dieser Prüfung wiederverwendet.
- Die gemeinsamen Alarmvektoren stammen aus dem echten CI98-Artefakt und passen
  exakt zur gebundenen Projektion3dcf2073c46012e193900fce971a5bab91cefd5194f433bac7169e7f98917907.
  Golden-recording war aus; Erwartungsdaten wurden nicht passend umgeschrieben.

Die zwölf Helferregressionen prüfen positive und negative Vergleiche in beiden
Richtungen, darunter 2^63 gegenüber Long.MAX_VALUE, benachbarte große Ganzzahlen,
Arbitrary-Precision-Dezimalwerte, exakte Float-/Doublewerte, nichtendliche Zahlen,
verschachtelte Strukturen, zusätzliche/fehlende Schlüssel und Arrayreihenfolge.
Der bestehende Produkt-Zahlenfix #466 bleibt unverändert.

## Transparente Zwischenprobe

Der erste direkte Host-JVM-Aufruf bestand41/42 Fälle; die Kalenderfixture
meldete `missing-timezone-database`, weil der lokale Prüfclasspath die im echten
Gradle-Prepare-Schritt bereitgestellte Ressource noch nicht enthielt. Diese
Zwischenprobe bleibt vollständig unter `after-missing-timezone-resource` erhalten.
Für den abschließenden Aufruf wurde ausschließlich die unveränderte normative
Ressource mit dem bereits im Gradle-Bau festgelegten Hash
`2e6b1c9da8c9b2a98d8b9c9c6addb4b93b6de37a19e76120361eff245cc87e9c`
aufgenommen. Keine Repository-Bauänderung und kein übersprungener Test.

## Reproduktion und Grenzen

Die exakten ausgeführten Runnerstände, Befehle, Classpaths, Quellen-/Klassen-/
Abhängigkeitshashes und Rohlogs liegen in `before` und `after`; `summary.json`
fasst ausschließlich diese Ausführung zusammen. Die Runner enthalten die
ursprünglichen Arbeitsverzeichnisse. Für einen anderen Arbeitsplatz müssen diese
Pfade auf die entsprechenden, anhand der Receipts zu prüfenden Artefakte zeigen.
Die eigentlichen Testquellen und der normale Gradle-Prüfweg liegen im Repository.

Dies ist ein gezielter Host-JVM-/API-Compile-Nachweis mit der echten JVM-JSON-
Implementierung20240303. Kein kompletter Gradle-/APK-Bau, keine neue Android-
JSON-/Keystore-/Providerlaufzeitabnahme. Der volle unveränderte APK-Gate muss auf
dem veröffentlichten Korrekturstand noch erfolgreich abgeschlossen werden.
