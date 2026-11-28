# #856 – tatsächlicher Tablet-Dienst: Österreich-Kennungen

Der vollständige Produktdienst `HolidayService.kt` und die reguläre gesamte
JUnit-Klasse `HolidayServiceTest.kt` wurden mit den tatsächlichen Projektdateien
`DAV.kt` und `StandardBase64.kt` kompiliert und ausgeführt. Es wurden keine
Android-Stubs oder nachgebauten Feiertagsalgorithmen verwendet.

| Gleiche endgültige Testklasse | Bestanden | Fehlgeschlagen |
| --- | ---: | ---: |
| Unveränderte #855-Dienstquelle aus dem Index | 20 | 6 |
| Dienstquelle mit #856 | **26** | **0** |

Die sechs zusätzlichen Methoden prüfen alle neun offiziell belegten
österreichischen ISO-/OpenHolidays-Paare, beide Endpoints, UTF-8-Prozentkodierung
der bekannten Umlaute, ISO-Antwortkompatibilität, Mehrregionszeilen und Dedupe,
Ablehnung unbekannter AT-Auswahlen vor HTTP, unbekannte/gemischte/fremde und
unbekannte Kindcodes ohne Coverage, strikte Ablehnung anderer Unicodecodes,
Ferien-Opt-out, landesweiten Abruf und den unveränderten Schweizer Abrufweg.
Die 20 bestehenden Methoden enthalten die früheren #855-Regressionsfälle.

Compiler Kotlin 2.4.21, JVM-Bytecodeziel 17, tatsächliche Laufzeit
OpenJDK 21.0.13.1. Beide Builds haben dieselbe bereits vorhandene Warnung
`DAV.kt:41: expression is unused`. Kein Android-SDK-/Gradle-/Geräte- oder
Oberflächenlauf und keine installierbare Paketfreigabe.

`before-final-*` und `after-final-*` enthalten vollständige Befehle, Ergebnisse
und SHA-256-Bindungen sämtlicher Quell- und Abhängigkeitsdateien. Alle finalen
Quellbindungen wurden nach dem Lauf nochmals auf Übereinstimmung geprüft.
Der ursprüngliche #855-Ergebnisbaum ist
`f4f94a2c2cf73a064448d3208f31d471e150dbe4`.

## Wiederholung

`run-kotlin-host.py` kompiliert die angegebenen vier echten Dateien und startet
die reguläre JUnit-Klasse. Die offiziellen Maven-Abhängigkeiten und ihre Hashes
sind in `toolchain-manifest.json` gebunden. Compiler, JARs und erzeugte Binaries
werden nicht mit dieser Übergabe veröffentlicht.

```sh
python run-kotlin-host.py --repo /path/to/patched-repository \
  --compiler-cache /path/to/verified-jars --output /path/to/evidence
```

Für den Vorhervergleich nur `HolidayService.kt` durch den #855-Stand ersetzen;
die endgültige Testklasse und die übrigen Eingaben bleiben identisch.
