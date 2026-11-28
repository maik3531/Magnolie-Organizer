# #856 – unabhängiger Review und gezielte Gegenprüfung

**Ergebnis des geprüften Endstands: kein verbleibender Blocker im untersuchten
Änderungsumfang.** Dieser Bericht dokumentiert die tatsächlich ausgeführte
Gegenprüfung vom 28.11.2026. Beim nachträglichen Verpacken der Belege wurden
weder Produkttests wiederholt noch Produktdateien verändert.

## Im Review bestätigter und behobener Linux-Grenzfall

Der erste Linux-Kandidat mit SHA-256
`60d77f379d5de60a07752997ec131c44b0758731074cc4b8e6867f0545b1c065`
übersetzte bekannte österreichische Providerkennungen korrekt, konnte aber
Antwortcodes ohne Länderpräfix wie `WI` noch als vollständige AT-Abdeckung
bestätigen. Tatsächlich mit den Originalfunktionen reproduziert:

- AT-Abfrage ohne ausgewählte Region und Antwortscope `WI`: Coverage sowohl
  mit `nationwide=false` als auch mit `nationwide=true`.
- Ausgewähltes `AT-9` mit Scope `WI` und `nationwide=true`: Coverage für `AT-9`.
- Ausgewähltes `AT-9` mit gemischten Scopes `AT-WI` und `WI`: Coverage für `AT-9`.

Die Umwandlungsfunktion erhielt nicht mit `AT-` beginnende Werte unverändert;
die anschließende Prüfung verkürzte bei landesweiten Zeilen oder fehlender
Regionsauswahl den Vergleich zu früh. Der zuständige Implementierungsagent
ergänzte deshalb eine Prüfung jedes AT-Antwortscopes auf Länderpräfix und
explizit bekannte ISO-Zuordnung **vor** diesen verkürzten Erfolgswegen.

## Tatsächlich ausgeführte Gegenprüfung

Der korrigierte Produktstand
`5d4beae86270874cb3a4e9286b2bd8ad77203cecda45c065ba63ff29c0b96d63`
wurde unabhängig mit dem bestehenden Host der tatsächlichen Python-
Produktfunktionen gegengeprüft:

- Acht negative Scopekombinationen: `WI`, `9`, `AT`, `AT-9-UNKNOWN`,
  `AT-WI-UNKNOWN`, `AT-WI` + `WI`, `AT-WI` + `DE-SN`,
  `AT-WI` + `AT-9-UNKNOWN`.
- Jede davon mit leerer bzw. `AT-9`-Regionsauswahl und jeweils
  `nationwide=false`/`true`: **32 negative Kombinationen ohne Coverage**.
- Bekannter Scope `AT-WI` mit denselben vier Auswahl-/Nationwide-Kombinationen:
  **vier positive Kontrollen**, korrekte ISO-Antwort `AT-9` und passende Coverage.

**36/36 bestanden.** Der Prozess endete mit Exitcode 0 und gab diese Zählung sowie
die geprüften Produktquellhashes aus. `RESULT.json` hält dieses beobachtete
Ergebnis fest. `counterprobe.py` enthält genau diese Fall-/Assertionsschleifen;
für die Wiederholung sind lediglich ein CLI-Repositorypfad und eine vorangestellte
Hashprüfung ergänzt. Es ist kein zusätzlicher Algorithmusnachbau.

```sh
python counterprobe.py --repo /path/to/Magnolie-Organizer
```

Voraussetzung ist die im #856-Paket dokumentierte Quelle einschließlich #855.
Die Probe lädt den vorhandenen `test_holiday_fetch_coverage.py`-Host und führt
gezielt die Originalfunktionen aus. Sie startet keine GTK-Oberfläche und sendet
keine Netzwerkanfragen. Die vollständige Produkttestsuite läuft dabei nicht.

## Plattformübergreifender Quellenreview

Alle vier Neuner-Zuordnungstabellen wurden gegen die gespeicherte tatsächliche
OpenHolidays-Subdivisionsantwort verglichen: **identische neun ISO-/Providerpaare**.
Die unveränderte Antwortkopie liegt als `at-subdivisions.json` bei; ihr Hash ist
im Manifest festgehalten. Die Herkunfts-/HTTP-Belege stehen im Live-Teilpaket.

Beide Desktop-UI-Listen und die Setup-Normalizer behalten `AT-1` bis `AT-9`.
Die Anfrage verwendet die Providerkennung; die Antwort wird vor dem
Regionsvergleich kanonisiert. Windows/Linux lehnen unbekannte AT-Auswahlen
über ihre bestehenden Setup-Normalizer vor HTTP ab, Tablet/Mac direkt in Query.

C# prüft jeden normalisierten AT-Scope sowohl beim Antwortformat als auch beim
Anfragevergleich. Kotlin/Swift setzen bei unbekannten/fremden Scopes die
Vollständigkeit vor den landesweiten bzw. Parent-/Child-Erfolgswegen zurück.
Unbekannte Kindcodes und gemischte bekannte/unbekannte Scopes erhalten damit
keine Löschbefugnis. Die vorhandene Zeichenprüfung wird nicht allgemein gelockert.

Die vier Implementierungen müssen wegen dieses Befunds keinen generischen
Retry hinzufügen: Der Fehler wird durch die korrekte erste Anfrage behoben.

## Grenzen

Die zusätzliche 36-Fälle-Ausführung betrifft die tatsächlichen Python-
Produktfunktionen mit kontrollierten Antworten. C#/Kotlin/Swift sowie ihre
Anschlussstellen wurden in diesem unabhängigen Review anhand der tatsächlichen
Quellen beurteilt; die anderen Agenten dokumentieren ihre getrennten Compiler-,
Test- und Live-Läufe. Keine zusätzliche native Windows-/Mac-/Tablet-/GTK- oder
Paketabnahme aus diesem Review ableiten. `SOURCE-MANIFEST.json` bindet die exakt
beurteilten Quellen und die für die Probe verwendeten Hilfsdateien.
