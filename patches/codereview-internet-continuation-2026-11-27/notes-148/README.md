# Notes: spätere Fernziele werden bei der Verbindungsprüfung übergangen

**Zuordnung:** [#148](https://github.com/maik3531/Magnolie-Organizer/issues/148), neuer reproduzierter Teilbefund zur tatsächlichen Sync-Verfügbarkeit; Bezug zum bereits geschlossenen [#261](https://github.com/maik3531/Magnolie-Organizer/issues/261). Der vollständige Restumfang beider Oberflächen- und Transportaufgaben wird durch diesen Patch nicht als erledigt erklärt.

**Geprüfte Basis:** `f8ad956ec4c9a71cd4d857c3218177c481407c85`, 27. November 2026.

## Befund und Wirkung

Die Notes-Funktion `Baumwerk.fernAbgleichVerbindungen()` prüft erreichbare, bereits freigegebene Internet-Gegenstellen durch einen signierten FS1-Handschlag. Die Prüfung begann bisher bei jeder Aktualisierung erneut beim ersten gespeicherten Partner. Das achtsekündige Gesamtbudget und die Begrenzung auf die ersten 32 Partner führten zu zwei belegten Auslassungen:

1. Nach sechs früheren Gegenstellen mit je 1,5 Sekunden Zeitüberschreitung wurde ein siebter erreichbarer Partner bei keiner der wiederholten Aktualisierungen geprüft.
2. Bei 70 schnell antwortenden Partnern wurden auch nach drei Aktualisierungen ausschließlich die ersten 32 berücksichtigt.

Die Einzelaktion zum Fernabgleich konnte für eine bereits geteilte Notiz dadurch als nicht verfügbar erscheinen, obwohl ihre Gegenstelle erreichbar war. Das ist ein Fehler der Verfügbarkeitsprüfung. Der normale Postfachversand hat einen eigenen Ablauf; aus diesem Befund wird kein vollständiger Ausfall der Notizsynchronisierung abgeleitet.

## Korrektur

Ein kleiner, pro `Baumwerk` gehaltener Prüfreihenfolge-Kern merkt sich die Identität des zuletzt tatsächlich versuchten Partners. Die nächste Runde beginnt danach und läuft bei Bedarf zum Listenanfang zurück. Eine nur vorbereitete, vor dem ersten Versuch unterbrochene Runde verändert die Fortsetzung nicht. Entfernte, nicht mehr vertraute oder neu sortierte Partner werden anhand der aktuellen Kandidatenliste behandelt.

Die Begrenzung auf höchstens 32 Versuche je Runde und das bisherige Zeitbudget bleiben erhalten. Der Patch ändert weder die FS1-Authentisierung noch `FernAbgleichVerbindung.passt`, die Internet-/Dienstbedingungen, Freigaben, Schlüssel, Zielprüfung oder den automatischen Synchronisationsumfang. Er erweitert insbesondere keine WLAN-Freigabe auf Mobilfunk und ergänzt keinen Nextcloud-Vermittler.

## Tatsächliche Prüfung

- **Unveränderte Produktmethode und Nachweisprüfung im Kotlin-Hostharness:** vorher **10 bestanden / 2 fehlgeschlagen**, danach **12 bestanden / 0 fehlgeschlagen**. Die beiden roten Fälle sind die beschriebenen wiederholten Fernziel-Auslassungen. Die übrigen Fälle prüfen Offlinezustand, ausgeschalteten Dienst, fehlende eigene Identität, unbestätigte/nicht vertraute/nicht eingerichtete Partner, Widerruf während der Probe, Zielwechsel, Wiederherstellungsepoche, Schlüsselwechsel, abgelaufene Nachweise und Unterbrechung.
- **Neue produktnahe JUnit-Klasse:** **8/8 bestanden**, direkt gegen `FernAbgleichReihenfolge.kt` kompiliert. Enthalten sind Zeitbudget-Fortsetzung, 70 Partner, Abbruch vor einem Versuch, Umsortierung, Entzug/Entfernung, leere Listen und kleine vollständig durchlaufene Listen.
- Die betroffenen Notes-Dateien der vorherigen Internetprüfung wurden vor der Änderung mit dem aktuellen Hauptzweig verglichen: alle 13 erfassten Notes-Eingaben waren bytegleich.

`before/` und `after/` enthalten die vollständigen Compiler- und Ergebnislogs, die erzeugten Harnessquellen und die SHA-256-Bindung an die tatsächlich verwendeten Quelldateien. `run_probe_fairness.py` übernimmt die Produktmethode und den Nachweis-Gültigkeitstest unverändert aus dem jeweils angegebenen Repository. Speicher, Handshake und monotone Uhr sind kontrollierte Testgegenstellen. Der unveränderte Produktions-Schedulerkern wird im korrigierten Lauf zusätzlich direkt kompiliert.

Beispiel für den reproduzierbaren Aufruf mit bereits vorhandenen Kotlin-Compiler-/Laufzeit-JARs:

```sh
python3 run_probe_fairness.py --repo /pfad/zum/quellstand --compiler-dir /pfad/zu/kotlin-jars --output /pfad/zum/ergebnis
```

Die JUnit-Klasse liegt im normalen Notes-Testquellverzeichnis und kann in der vorhandenen Android-Bauumgebung zusätzlich im üblichen Testlauf ausgeführt werden. Im hier verwendeten Hostlauf wurden der echte Kotlin-Compiler und JUnit direkt verwendet.

## Grenzen und nächster Schritt

Keine neue Android-/Robolectric-Gesamtprüfung, keine Compose-Bedienprüfung, kein physisches Telefon, keine reale Internetverbindung und keine Router-/Mobilfunkabnahme. Der synthetische Handshake im Ablaufharness prüft keine Kryptografie. Die unveränderte FS1-Implementierung behält ihre bisherigen getrennten Nachweise.

Nach Einpflege auf einem Android-Gerät mit mehreren gespeicherten Gegenstellen prüfen: frühe Ziele offline, späteres Ziel erreichbar, wiederholte Verbindungsaktualisierung, kurzlebiger Nachweis, Widerruf und tatsächliches Versenden einer schon geteilten Notiz. #148 bleibt für seine übrigen Bedien- und Abnahmekriterien offen; #128 bleibt für den automatischen Abgleich über weitere freigegebene Transportarten offen.
