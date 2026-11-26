# Zweiter vollständiger CI-Bau und Test-Kompilierbefund #805

[Actions-Lauf 45809316206](https://github.com/maik3531/Magnolie-Organizer/actions/runs/45809316206)
prüfte exakt `2dd93930ecff3752fdea22121813a1b6ee4b79a7`, Git-Baum
`e70d81ac94fbd80711ee1bab7ddeb7eeeb7c0d35`. Der zugehörige Tabletjob ist
`139872720224`, Modus `tablet-build-only-no-native-acceptance`.

## Tatsächlich erreicht

- Readiness und ursprüngliche Ressourcen-/Koordinationsgates bestanden.
- 22 Provenienztests; gemeinsame und Tabletquellen an denselben Commit gebunden.
- 194 Webchecks und 46 synthetische Import-/Anhangschecks bestanden.
- Der Setupfix aus Folgepatch 8 / #804 besteht im frischen CI-Checkout:
  88 Cross-Desktop-Fälle in 20 Sprachen.
- Die bestehenden 59 Runnerprüfungen sowie die weiteren vorgeschalteten
  Offlineprüfungen bestanden; die tatsächliche Reihenfolge ist im ausgewählten
  Ereignisprotokoll erhalten.
- Gradle kompiliert die Produkt-Kotlinquellen und verarbeitet Manifest/Ressourcen.

Die Projektion lautet
`3dcf2073c46012e193900fce971a5bab91cefd5194f433bac7169e7f98917907`.
Der erfasste Eingabesatz ist
`126c4f7c349ffeda9b7bcb212cee1ceaac14feb8143dcf368178a7b279e729fc`.

## Konkreter Abbruch

`:app:compileDebugUnitTestKotlin` scheitert an fünf `JSONObject.similar`-Aufrufen:
`DocumentRequestsTest.kt:91`, `NativeCalendarFileFixtureTest.kt:25` und
`VaultTest.kt:26,27,260`. Die Methode steht auf dem tatsächlichen
Android-Kompilierpfad nicht zur Verfügung. Die bestehende JVM-Abhängigkeit
`org.json:json:20240303` allein verhindert diesen Compilefehler nicht.
Der Gradle-Aufruf endet nach 1m56s und 24 ausgeführten Tasks mit Exit 1.

Dies ist der eigenständige Test-Kompilierbefund
[#805](https://github.com/maik3531/Magnolie-Organizer/issues/805), kein neuer
Beleg für den geschlossenen Produkt-Zahlenfehler #466. Sein genauer numerischer
Datenvertrag bleibt auch im Testvergleich erforderlich.

## Belegumfang

`run-45809316206-job-139872720224-failure.log` enthält die unveränderten
Originalzeilen 1638–1667 des Joblogs. `run-45809316206-gradle-failure.txt`
enthält die exakten 8000 Zeichen des vom ursprünglichen Gate begrenzten
Fehleroutputs nach JSON-Decodierung. Keine Nachricht wurde daraus als neuer
nativer Fehler umgedeutet.

`artifact-build-outcome.json` enthält ausgewählte tatsächliche Felder und
Ereignisse aus `artifacts/debug-build.json`; der Hash des Originaldokuments
ist angegeben. Der rohe Webcheck-Beleg wird unverändert mitgeführt. Der
Run-Receipt bindet Status, Zeitpunkte, Quellstand, Originalartefakt und Grenzen.

Das Original-ZIP `15114411668` wurde heruntergeladen und verifiziert:
41.805 Bytes, SHA256
`03f633885577f34145e9ae37400ad90adc39ba65837baa4fcbe4c461dd98a290`.
Es enthält vier JSON-Dateien und keine APK. Die Quellcapture-Datei ist Teil
dieses ursprünglichen Actions-Artefakts; ihr gebundener Commit und Eingabesatz
sind im Receipt erhalten.

Die Unit-Tests sind in diesem CI-Lauf noch nicht ausgeführt worden. APK-Bau,
abschließender APK-Quellbind und sämtliche nativen Android-Abnahmen fehlen.
Die sieben nativen Schritte wurden im ausdrücklich gewählten Build-only-Modus
korrekt übersprungen. Die lokale gezielte Korrekturprüfung zu #805 wird separat
neben diesen unveränderten Fehlerbelegen dokumentiert.
