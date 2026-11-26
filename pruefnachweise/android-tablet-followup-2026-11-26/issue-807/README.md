# Folgepatch 11: native Serienfixture und gebundene Originalbelege

[review-evidence.md](review-evidence.md) beschreibt den bestätigten nativen
Fehler aus Lauf 99/Versuch 2, den engen AOSP-Quellabgleich und die Fixturekorrektur.
Die alte Ist-Anzahl bleibt unbekannt. Unsyncte lokale Serienausnahmen werden
nicht als abgenommen dargestellt.

`compile-receipt.json`, der ausgeführte Runner und dessen vollständiges
`compile-z848q17d/instrumentation-kotlin.log` gehören zum finalen Quellhash
`d8b598923ef3f1d092ed3ffb83268571e748a6cb3ac035c8fb69ca0e1826fba3`.
Alle 16 Instrumentierungs-Kotlin-Dateien wurden tatsächlich gegen Android 37.2
kompiliert. Die unveränderten 38 Produktdateien, zwei Java-Testdateien und die
R-Klasse wurden nach Hashprüfung wiederverwendet. Die absoluten Hostpfade
sind historische Herkunftsbelege; die Prüfung ersetzt keinen Gradle-/APK-Gate.

`projection-comparison.json` bindet den neuen Quellstand und bestätigt alle 83
bytegleichen Runtimeausgaben gegenüber dem bereits tatsächlich gebauten APK-
Stand aus Lauf 99. Die nächste native Ausführung muss dennoch ihren eigenen
Quell-/APK-Bind nachweisen.

Die großen AOSP-Quelldateien werden nicht dupliziert; feste offizielle URLs,
Commit und SHA256 stehen in `aosp-source-manifest.json`. Alle hier vorhandenen
Dateien sind im übergeordneten `checksums.json` gebunden.
