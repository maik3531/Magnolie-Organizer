# #855-Nachprüfung und #856 – österreichische Providerregionen

## Tatsächlicher Befund

Die noch offene Live-Nachprüfung von #855 wurde am 28.11.2026 ausgeführt. Die
unveränderten echten Linux-Produktfunktionen einschließlich `_url_holen`,
`antwort_begrenzt_lesen`, Decoder, Parser und `feiertage_abrufen` wurden in einem
isolierten Python-Host ausgeführt. Ein reiner Aufzeichnungswrapper um
`urllib.request.urlopen` protokolliert die realen HTTPS-Antworten; TLS-Prüfung,
Request, Größenbegrenzung und Parser bleiben die Produktimplementierung.
Der Host stellt nur Laufzeit-/Gettext-Kontext bereit. Es ist keine native
GTK-/WebView- oder Paketabnahme.

Die ersten acht archivierten Requests betrafen DE/SN 2026 und 2027, AT/Wien
2026 sowie CH/Zürich 2026, jeweils öffentliche Feiertage und Schulferien.
Alle antworteten mit HTTP 200 und syntaktisch gültigen Kalenderdaten. Die
anfänglichen Transport-/Formprüfungen erkannten den späteren fachlichen
AT-Fehler noch nicht. **HTTP 200 und eine bestätigte Cacheabdeckung sind allein
kein Nachweis regional vollständiger Daten.**

Die offizielle `Subdivisions`-Antwort unterscheidet `code` und `isoCode`:

| Interne ISO-Identität | OpenHolidays-Code |
| --- | --- |
| AT-1 | AT-BL |
| AT-2 | AT-KÄ |
| AT-3 | AT-NÖ |
| AT-4 | AT-OÖ |
| AT-5 | AT-SB |
| AT-6 | AT-SM |
| AT-7 | AT-TI |
| AT-8 | AT-VA |
| AT-9 | AT-WI |

Die tatsächliche Wiener Produktanfrage sendete `subdivisionCode=AT-9` und bekam
sechs landesweite Ferienperioden. Eine Kontrollanfrage mit dem offiziellen
Code `AT-WI` gab acht zurück: zusätzlich Semesterferien 02.–07.02.2026 und
Sommerferien 04.07.–06.09.2026. In beiden vollständigen Desktopoberflächen
fehlten diese beiden Perioden nach dem wirklichen Anfrage-/Antwortweg. Eine
explizit gesetzte kanonische Wiener Altcachefixture mit dem realen Semester-
Zeitraum wurde durch die falsch bestätigte AT-9-Abdeckung gelöscht. Das ist
eine kontrollierte Altbestand-Reproduktion, kein behaupteter beobachteter
Datenverlust auf einem Nutzergerät.

Weitere reale Kontrollantworten: Niederösterreich `AT-NÖ` acht Ferienperioden;
Kärnten `AT-KÄ` neun, einschließlich Semesterferien 09.–14.02.2026, Josefstag
19.03.2026 und Sommerferien 11.07.–13.09.2026. Die Rohantworten enthalten auch
Unicode-Regionscodes, die der ursprüngliche #855-Kandidat vor seiner
ASCII-Prüfung noch nicht normalisierte.

## Linux-Quellkorrektur für #856

Der neue gemeinsame Helper bildet ausschließlich die neun belegten Paare ab.
Anfragen übersetzen interne ISO-Identitäten in die Providercodes; Antworten
werden vor der vorhandenen strikten Regionsprüfung wieder zu ISO normalisiert.
Die bestehenden gespeicherten Codes und die bestätigten `abrufbereiche` bleiben
ISO. Bekannte ISO-Antworten sind weiterhin gültig. Unicode-Normalisierung
behandelt bekannte zusammengesetzte und zerlegte Schreibweisen gleich.

Jeder österreichische Antwortscope muss eine bekannte ISO-Identität sein.
Unbekannte `AT-*`-Antwortcodes, einschließlich vermeintlicher Kinder wie
`AT-9-UNKNOWN`, sowie unqualifizierte Kürzel wie `WI`, `9` oder `AT` können
keine vollständige Abdeckung bestätigen, auch bei landesweiten Zeilen,
landesweiter Abfrage oder gemischten bekannten/unbekannten Codes. Der bestehende
tolerante Lesepfad für verwertbare Daten bleibt erhalten. Unbekannte angefragte
österreichische Regionen scheitern vor dem HTTP-Aufruf. Die übrigen Länder
behalten ihre bisherige Verarbeitung.

Die ursprüngliche Setup-Testassertion erwartete fälschlich die API-URL mit
`AT-9`. Nur diese AT-Erwartung wurde fachlich auf `AT-WI` korrigiert; außerdem
bindet der ursprüngliche AST-Testhost den neuen echten Helper ein. Keine
übrigen Setup-Assertions wurden entfernt oder gelockert.

## Ergebnisse

| Prüfung | Unveränderter #855-Kandidat | #855 plus #856-Linuxfix |
| --- | ---: | ---: |
| Echte Python-Produktfunktionen, gleiche 35 Testmethoden | 27/35 | 35/35 |
| Beide vollständigen Desktopskripte mit aufgenommenen nativen Liveantworten | 6/12 | 12/12 |
| Drei ursprüngliche Setup-Providerfälle | ursprüngliche AT-Erwartung falsch | 3/3 |
| Frischer nativer Wien-Abruf | 13 Feiertage + 6 Ferien | 13 Feiertage + 8 Ferien |
| Frischer nativer Kärnten-Abruf nach Fix | – | 13 Feiertage + 9 Ferien |

Die acht roten Python-Methoden enthielten 41 fehlgeschlagene Assertions
einschließlich Unterfällen. Es handelt sich nicht um 41 unabhängige Fehler.
Die Matrix prüft alle neun Abbildungen, Mehrregionsantworten, bekannte ISO-
Antworten, Unicode, unbekannte AT-Codes, Länder-/Regionsabdeckung, Ferienopt-out
und den unveränderten #855-Erhaltungsvertrag. Alle bestehenden 26 Methoden
bleiben enthalten.

Der endgültige Nachfix-Liveabruf verwendete vier neue echte Produktrequests für Wien und
Kärnten. Im Ergebnis sind alle Regionsfelder und bestätigten Bereiche kanonisch
ISO; beide Providerarten sind erfolgreich und vollständig erkannt. Die
Frontend-Nachprüfung übernimmt diese echten neuen nativen Antworten; die
Desktop-Produktdateien selbst wurden durch #856 nicht verändert. Deutsche
und Schweizer Kontrollbestände stammen weiterhin aus den ersten echten
Aufzeichnungen.

Die erste zusätzliche Frontendprüfung verlangte irrtümlich die identische
Array-Reihenfolge und unveränderte Regionsbeschriftung nach erneuter
Zusammenführung. Die bestehende Implementierung darf diese normalisieren.
Die Prüfung wurde auf genau eine semantische Kalenderzeile mit unverändertem
Zeitraum, Art, Land, ursprünglichem Namen mit zulässiger Regionsbeschriftung
und exakter Regionsmenge gebunden. Die ursprünglichen Erwartungsfehler bleiben
in `frontend-initial-expectation.*` erhalten; keine Produktänderung erfolgte
zur Anpassung dieses Tests.

Eine unabhängige Quellgegenprüfung fand nach dem ersten 34-Methoden-Lauf noch
eine zu weite Ersetzungsbefugnis bei unqualifizierten AT-Antwortcodes. Der
damalige Kandidat wurde verworfen. Die endgültige neue Methode prüft 20
Kombinationen aus unbekannten, fremden und gemischten Codes, ausgewählter bzw.
landesweiter Abfrage und `nationwide`. Der 35-Methoden-Lauf, die vier finalen
Liveabrufe und der abschließende 12-Fälle-Frontendlauf sind an die endgültige
Quelle gebunden. `after-capture` und `intermediate` sind historische
Zwischenstände; **maßgeblich ist `final-capture`**.

Der ursprüngliche Setup-Host scheiterte zunächst am fehlenden pytest. Nach
isolierter Bereitstellung von pytest 9.2.0 liefen alle drei ausgewählten
Originalfälle. Die vorinstallierte AnyIO-Erweiterung meldet eine
Pytest-10-Abkündigungswarnung; keine Testfehler. Der vollständige Sprachlauf
wird von einer getrennten Prüfung bearbeitet.

## Quellen, Dateien und Grenzen

`python-handoff.json` bindet die drei bearbeiteten Produkt-/Testdateien an
ihre Vorher-/Nachher-Hashes. Die Vorherquelle ist exakt der gestagte #855-Blob
auf Basis `1749c92eb42801c38eaba31b272d8c0e27be9164`, Kandidatenbaum
`f4f94a2c2cf73a064448d3208f31d471e150dbe4`. Dieser Teilauftrag hat nichts gestagt,
committet, veröffentlicht oder auf main übernommen.

Die vollständigen Quellen, Testlogs, Rohantworten und Aufrufbelege liegen im
Prüfpaket. Offizielle Dokumentation:

- https://www.openholidaysapi.org/en/ (Subdivisions, Gruppen und Abrufparameter)
- https://www.openholidaysapi.org/en/faq/ (Datenlizenz)
- https://www.openholidaysapi.org/en/sources-europe/ (öffentliche Ursprungsquellen)
- https://github.com/openpotato/openholidaysapi/blob/bd07111f622e80e95ef6cfd9bde3fe6e058d5336/src/webservice/Controllers/HolidaysController.cs

Attribution und Datenlizenz: `ATTRIBUTION.md` und
`OPENHOLIDAYS-DATA-LICENSE.txt`. Quellen-/Lizenzbehauptungen beziehen sich
auf die tatsächlich gelesenen offiziellen Dokumente, nicht auf eine
angenommene Softwarelizenz.

Die vorhandenen Produktpfade verwenden OpenHolidays; es wurde kein Nager-
Backend erfunden oder als geprüft ausgegeben. Keine native Windows-, Mac-,
Tablet- oder GTK-Abnahme, keine installierten Pakete, keine Gesamtfreigabe
aller Feiertagsdaten. Liveinhalte sind zeitgebundene Beobachtungen. #854-
Erweiterungen auf neue Länder/Regionsmodelle bleiben ein eigener Auftrag.

## Wiederholung

Python-Regression auf dem Produktstand:

```sh
python magnolie-organizer/pruefungen/test_holiday_fetch_coverage.py
python -m pytest magnolie-organizer/pruefungen/test_setup_holidays.py::test_actual_provider_url_and_empty_availability -q
```

`MAGNOLIE_HOLIDAY_SOURCE` kann für die identische 35-Methoden-Prüfung die
unveränderte #855-Produktdatei benennen. Ein frischer Liveabruf mit den
tatsächlichen Produktfunktionen ist über `live_probe.py --root REPO --output
NEUES_VERZEICHNIS --scene at-9-2026 --scene at-2-2026` möglich. Dabei werden
neue HTTP-Anfragen gestellt und eigene Zeitstempel/Hashes erzeugt.

`frontend_live.js REPO EVIDENCE_DIR` verwendet die archivierten Vorherantworten;
mit dem vierten Argument `final` die endgültigen Nachfixantworten. `after`
bezeichnet den verworfenen Zwischenstand. Es benötigt die reguläre
JSDOM-Abhängigkeit und den neuen Originaltest `holiday-cache.js`. Dieser
Wiederholungsschritt ist ausdrücklich ein Replay aufgenommener Daten und
stellt keine neue Liveverbindung her.
