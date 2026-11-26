# Prüfbericht und Patch: Periodenvorhersage im Magnolie Organizer

**Issue:** [maik3531/Magnolie-Organizer#803](https://github.com/maik3531/Magnolie-Organizer/issues/803)  
**Stand:** 26. November 2026  
**Basis:** `d4da48a5eadd0bda22422b924bef4ee3b4324040` (`main`, vor Erstellung und vor Bereitstellung geprüft)  
**Quellcommit im Patch:** `0bd930674794707c49e707ab405810ad5b78f379`  
**Lieferung:** Quellpatch zur späteren Einpflege. Keine Änderung von `main`, keine veröffentlichten Produktpakete.

## Ergebnis

Der Patch verbessert die bereits mit #79 eingeführte Periodenberechnung. Die
beiden Desktop-Oberflächen, die Linux-Berechnung in Python und die
Windows-Berechnung in C# verwenden denselben überprüften Vertrag. Dazu kommen
die Handbuchergänzungen und die Sprachkataloge für sämtliche 20 Produktsprachen.

Die zugehörige Datei ist [period-forecast-improvements.patch](period-forecast-improvements.patch).
Dateigröße und SHA-256 stehen in [SHA256SUMS](SHA256SUMS). Screenshots und
Prüfprotokolle stammen ausschließlich aus synthetischen Testbüchern.

### Verhalten im Kalender

| Anzeige oder Aktion | Bedeutung und Wirkung |
| --- | --- |
| Optional zuschaltbare Vorhersage | Zeigt den geschätzten nächsten Beginn, ein Zeitfenster und die verwendete Datengrundlage. Die Anzeige ist bei alten Büchern zunächst aus. Bereits gespeicherte Erinnerungsoptionen bleiben erhalten. |
| Blasser Tropfen mit `≈` | Möglicher **Beginn** innerhalb des Schätzfensters. Keine erfundene Blutungsdauer und kein gespeicherter Blutungseintrag. |
| Bestätigung eines blassen Tropfens | Für heute oder einen vergangenen Tag im noch aktiven Fenster: tatsächliche Blutungsstärke auswählen und genau diesen Tag bestätigen. Zukunftstage sind nicht bestätigbar. |
| Abgelaufenes Fenster | Alle aktiven Vorhersagetropfen verschwinden. Ohne Bestätigung wird kein Tag als tatsächliche Blutung übernommen und keine folgende Periode erfunden. |
| Blasser, gestrichelter Tropfen mit `!` | Optionaler Hinweis auf fehlenden neuen Eintrag, veränderten Abstand, breite Streuung oder bestimmte auffällige Aufzeichnungen. Tooltip und zugänglicher Name erklären den konkreten Grund. |
| Gestrichelten Hinweis anklicken | Öffnet die Eingabe eines selbst angegebenen Grundes beziehungsweise einer Planungspause. Ein fehlender Eintrag wird nicht als medizinisch bewiesenes Ausbleiben bezeichnet. |
| Bestätigung abbrechen | Verändert keine Blutungseinträge. Ein Hinweis allein ist niemals eine Beobachtung. |

Anzeige, Vorhersage-Erinnerung und Abweichungshinweise bleiben getrennt
schaltbar. Die Anzeige allein schaltet keine Benachrichtigungen ein. Nach
Bestätigung, Korrektur oder Löschung einer tatsächlichen Markierung wird die
Berechnung erneuert. Schätzungen werden weder als normale Termine noch als
Gesundheitsfakten in die Daten geschrieben.

### Bekannte Gründe und Pausen

Es stehen **Schwangerschaft**, **Stillzeit**, **Medikamente oder hormonelle
Behandlung**, **Wechseljahre/Menopause** und **anderer bekannter Grund** zur
Auswahl. Der Organizer leitet keinen dieser Gründe selbst aus dem Verlauf ab.

Bei Schwangerschaft schlägt die Oberfläche neun Kalendermonate ab Erfassung
vor. Das Enddatum lässt sich ändern; die Vorschlagsdauer ist ausdrücklich kein
errechneter Geburtstermin. Die Monatsaddition begrenzt beispielsweise den
31. Mai auf den letzten gültigen Februartag. Die anderen Gründe beginnen ohne
festes Enddatum. Jeder Grund erlaubt sowohl ein eigenes Datum als auch eine
unbefristete Pause.

Eine Pause gilt bis einschließlich ihres Enddatums. Währenddessen entstehen
keine Periodenvorhersagen, Hinweise wegen fehlender Periodenanfänge oder
Zykluserinnerungen. Die eingeschaltete Kalenderanzeige zeigt stattdessen einen
neutralen Pausenstatus mit Grund und Ende. Vorhandene Einträge und die
persönlichen Anzeige-/Erinnerungsoptionen bleiben erhalten.

Eine während der Pause neu erfasste tatsächliche Blutung wird zunächst normal
gespeichert. Eine **separate Rückfrage** bietet „Neue Periode bestätigen“ und
„Pause beibehalten“ an. Erst die ausdrückliche Bestätigung als neue Periode
beendet die Pause früher. Beibehalten oder Abbrechen erhält sowohl den
Blutungseintrag als auch die Pause. Ebenso wenig beenden eine zukünftige
Markierung, eine Umbenennung, ein Wechsel der Blutungsstärke oder ein erneutes
Laden die Pause. Alternativ kann sie direkt beendet werden; dabei wird kein
Blutungstag erzeugt.

Die Wiederaufnahme der Planung behauptet kein Ende einer Schwangerschaft oder
Menopause. Das Handbuch und die Rückfrage erklären, dass Blutungen während
einer Schwangerschaft und nach der Menopause ärztlich abgeklärt werden sollen.
Die medizinische Formulierung wurde mit den unten verlinkten NHS-Quellen
abgeglichen. Der Organizer gibt keine Empfehlung, Medikamente zu verändern.

Nach einer Pause gilt eine neue Datengrenze: Es zählen die Tage ab der
ausdrücklichen Wiederaufnahme beziehungsweise nach dem geplanten Enddatum.
Intervalle vor oder über die Pause hinweg werden nicht wiederverwendet. Für
eine neue Schätzung sind drei neue dokumentierte Periodenanfänge nötig. Ohne
neue Einträge gibt es somit keine wieder aufgewärmte Überfälligkeitswarnung
aus dem Verlauf vor der Pause.

## Berechnung und Grenzen

Nur ausdrücklich typisierte tatsächliche Blutungsmarkierungen zählen.
Umbenennungen, Symbole, andere Markerarten, doppelte Datumszeilen oder
Zukunftseinträge liefern keine zusätzlichen Perioden. Benachbarte Einträge mit
höchstens drei Tagen Abstand bilden eine Episode; unmarkierte Tage werden
dadurch nicht als beobachtete Blutung ausgegeben.

Die Schätzung verwendet den Median von höchstens zwölf unmittelbar
aufeinanderfolgenden Intervallen zwischen 14 und 60 Tagen. Ein Intervall
außerhalb dieser technischen Spanne unterbricht die Berechnungsbasis; ältere
Intervalle auf der anderen Seite werden nicht still wiederverwendet. Zwei
verwendbare Intervalle, also mindestens drei Anfänge, sind erforderlich. Es
gibt keinen ersatzweise angenommenen 28-Tage-Zyklus.

Das Fenster reicht vom kürzesten bis zum längsten verwendeten Intervall mit
jeweils zwei Tagen Rand. Die Fensterbreite ist ein transparenter Planungswert,
kein statistisch validiertes Konfidenzintervall. Die Grenzen 14–60, die
Gruppierung und die zwei zusätzlichen Tage sind Software-Heuristiken, keine
klinischen Definitionen von „normal“ oder „abnormal“.

Fehlende Bestätigungen werden nicht durch Hochrechnen weiterer Zyklen ersetzt.
Überlappende tatsächliche Blutungseinträge, zu alte Verläufe, ungültige Daten,
Jahresgrenzen und längere Aufzeichnungslücken haben gesonderte Ergebnisse.
Für einen Vergleich des letzten Intervalls wird die Basis **ohne dieses
Intervall** berechnet, damit es seine eigene Abweichung nicht verdeckt.

Alle drei Implementierungen verwenden für „heute“ die gebundene normative
Zeitzonenquelle des Produkts. Ein während der Prüfung reproduzierter Unterschied
zwischen `America/Winnipeg` in der Produkt-Zeitzonendatei und der Host-Datenbank
wurde behoben. Fehlende oder beschädigte gebundene Regeln werden nicht durch
eine still abweichende Host-Berechnung ersetzt.

Der vollständige Daten- und Verhaltensvertrag ist Bestandteil des Patches:
`contracts/cycle-calendar.md`. Darin sind auch die optionalen Pausenfelder,
inklusive Endgrenzen, Wiederaufnahme und die Einschränkungen beschrieben.

### Nachvollziehbares synthetisches Beispiel

| Situation | Erwartetes Ergebnis |
| --- | --- |
| Tatsächliche Anfänge 01.01., 29.01. und 26.02.2026 | Median 28 Tage, geschätzter Beginn 26.03., Fenster 24.–28.03.2026. |
| Am 29.03. noch kein neuer Anfang erfasst | Keine aktiven Vorhersagetropfen mehr. Optional gestrichelter Hinweis am früher geschätzten 26.03. mit Erklärung. |
| Am 29.03. Grund Schwangerschaft ausgewählt | Änderbarer Pausenvorschlag bis einschließlich 29.12.2026. Keine Zyklusprojektionen während der Pause. |
| Am 30.03. Blutung erfasst und „Pause beibehalten“ gewählt | Blutung bleibt im Buch, Pause bleibt aktiv, kein neuer Berechnungsanfang. |
| Am 30.03. ausdrücklich als neue Periode bestätigt | Pause endet, neue Basis beginnt am 30.03. Noch keine Vorhersage aus der alten Historie. |
| Weitere tatsächliche Anfänge am 27.04. und 25.05.2026 | Frische Basis von drei Anfängen, nächste Schätzung 22.06.2026. |

## MorphHealth-Quellenvergleich

Geprüft wurde das öffentliche Repository
[TheMorpheus407/morphhealth-benchmark](https://github.com/TheMorpheus407/morphhealth-benchmark/tree/a91ffffbe160a4542f8e2f79401406052ec5845f)
am festen Commit `a91ffffbe160a4542f8e2f79401406052ec5845f`. Es enthält mehrere
Modellimplementierungen eines Benchmarks; es ist keine einzelne klinisch
validierte Berechnung.

Die [Astra-Implementierung](https://github.com/TheMorpheus407/morphhealth-benchmark/blob/a91ffffbe160a4542f8e2f79401406052ec5845f/GPT-6-Astra/app/lib/core/cycle.dart)
lieferte passende Vergleichspunkte: drei tatsächliche Anfänge als Mindestbasis,
Median, sichtbares Fenster, Ausschluss von Zukunftsdaten und kein Weiterrollen
ausgebliebener Bestätigungen. Diese Konzepte wurden eigenständig in Magnolies
bestehendes Markierungsmodell übertragen.

Bewusst anders behandelt Magnolie unter anderem die standardmäßig ausgeschaltete
Anzeige, die zusammenhängende Historie nach einer Unterbrechung, veraltete
Schätzungen und den Verzicht auf eine stille Ausreißerentfernung, die das
sichtbare Fenster künstlich verengen könnte. Der Patch benötigt keinen fremden
Dienst und übernimmt keinen Dart-Laufzeitcode. Die MorphHealth-Referenz steht
unter [MIT-Lizenz](https://github.com/TheMorpheus407/morphhealth-benchmark/blob/a91ffffbe160a4542f8e2f79401406052ec5845f/LICENSE),
Copyright 2026 Cedric Mössner. Quellenvergleich bedeutet keine medizinische
Validierung oder Empfehlung durch MorphHealth.

## Durchgeführte Prüfungen

| Bereich | Tatsächlich erzieltes Ergebnis |
| --- | --- |
| Gemeinsame unabhängige Sollfälle | **60** Datums-, Verlauf-, Datenfehler- und Pausenfälle; die erwarteten Werte wurden gezielt aus dem Vertrag festgelegt. |
| JavaScript, beide vollständigen Desktop-Frontends | **9.260 Prüfaussagen bestanden**, einschließlich je **1.000** deterministisch erzeugter Verläufe und sämtlicher 60 Sollfälle. |
| JavaScript ↔ Python | Vollständiger Vergleich aller ausgegebenen Statistikfelder für **1.060** Verläufe, zusätzlich vollständige Gleichheit der beiden JS-Frontends. |
| Python | **16 Testgruppen bestanden**; darin 250 generierte Verläufe, die gemeinsamen Sollfälle, alle 597 gebundenen Zeitzonenkennungen und der tatsächliche Linux-Erinnerungsprojektionspfad mit isoliertem Testprofil. |
| C# | **1.114 Prüfaussagen bestanden**, einschließlich 250 generierter Verläufe und aller gemeinsamen Sollfälle. Der portable Testhost kompiliert die tatsächlichen Produktdateien für Berechnung und normative Zeitzonen. |
| Python ↔ C# | **60/60 vollständige Statistiken identisch**, einschließlich sämtlicher sechs Pausenkontextfelder. |
| Vorhandene Desktop-Regressionen | **113 Fälle bestanden**: 57 Windows- und 56 Linux-Frontendfälle. |
| Vorhandener Zyklus-UI-Test | Bestanden; historische Beispieldaten verwenden jetzt einen festen Prüftag. |
| MCP-UI | Beide vollständigen Frontends bestanden; neue Anzeigeoption, Revisionen und bestehende CRUD-/Schreib-/Dialogschranken geprüft. |
| Reales Chromium | **10 Szenarien bestanden**, je fünf pro Frontend: Vorhersage/Bestätigung/Abbruch/Ablauf, Schwangerschaftspause und bewusste Wiederaufnahme, unbefristete Medikament-/Menopausepause sowie Tagesansicht bei 1280×800 und 1024×768. Keine JavaScript-Seitenfehler. |
| Lokalisierung | **54 UI-Meldungen in 20 Sprachen**; beide Desktop-Katalogsätze mit echtem GNU gettext und den vorhandenen Generatoren geprüft. |
| Handbuch | Alle **20 Sprachabschnitte**, beide Handbuchkopien, HTML-/Ladestruktur und **19/19 Übersetzungskataloge** mit dem vorhandenen Originalprüfer geprüft. |
| Unabhängige Bedienungsprüfung | Pausen, echte Schnellmarkierungen, beide Datumseingabearten, Dialogablauf, abgebrochene/veraltete Aktionen, Kontextwechsel und sichtbare Layouts geprüft. Alle konkreten Befunde behoben und erneut nachgewiesen. |
| Patch-/Git-Prüfung | Anwendung auf sauberer Basis, identischer resultierender Quellbaum, rückwärts anwendbarer Patch, Whitespace-Prüfung und bestehende Git-Speicherschranke; siehe gesondertes Anwendungsprotokoll. |

Die Anzahl der Prüfaussagen beschreibt die Softwareprüfung. Sie ist keine
Stichprobengröße realer Personen und kein Nachweis medizinischer Trefferquoten.

### Wichtige geprüfte Randfälle

- Keine Daten, nur ein oder zwei Anfänge; exakt 14/60 Tage und Unterbrechungen
  bei 13/61 Tagen; Erholung nach zwei neuen verwendbaren Intervallen.
- Doppelte und umsortierte Daten, unbekannte IDs, umbenannte Marker,
  falsche Container, ungültige ISO-Daten und Zukunftseinträge.
- Schaltjahr 2028, Jahrhundert 2100, Jahre 0001/9999, positive Halbwerte bei
  der Medianrundung, Ende des Schätzfensters und kein erfundener Folgezyklus.
- Normative Zeitzonen, insbesondere der konkret abweichende Winnipeg-Fall;
  beschädigte, fehlende und paketiert geladene Ressourcen.
- Sämtliche fünf Pausengründe, befristet/unbefristet, einschließlich Endtag,
  zukünftiger Beginn, ungültiges Ende, zukünftige Wiederaufnahme und frische
  Historie nach Ende oder ausdrücklicher Wiederaufnahme.
- Abbrechen, Escape, doppelte/veraltete Buttonaufrufe, gelöschte Blutung,
  zwischenzeitlich geänderte Pause, Buchwechsel, Sperren und Wiederherstellen.
- Abschalten trotz ungültigem Entwurf eines anderen Zahlenfeldes, Löschung
  einer Markerdefinition, unmittelbar korrekter Pausenstatus in offenen
  Einstellungen und Erhalt anderer Markierungen beim Bestätigen eines Tages.

Bei der unabhängigen Prüfung wurden veraltete Zwischenergebnisse nach
Definitionslöschung, blockierte Checkbox-Änderungen bei ungültigem Zahlenentwurf,
Platzprobleme der Tagesansicht und eine veraltete Pausenstatuszeile gefunden.
Diese Fehler sind korrigiert und durch gezielte Regressionen abgesichert.

## Wiederholen der Prüfungen

Verwendet wurden Node **24.22.3**, jsdom **26.1.0**, Python **3.12.14**, .NET SDK
**8.0.428** und Chromium **156.0.8078.108**. Die Browserprüfung benötigt das
Python-Paket Playwright sowie einen passenden installierten Chromium-Browser.
Die gettext-Werkzeuge `msgfmt` und `msgattrib` müssen erreichbar sein.

Zuerst den Patch in einer sauberen separaten Arbeitskopie auf der genannten
Basis prüfen und anwenden:

```sh
git switch --detach d4da48a5eadd0bda22422b924bef4ee3b4324040
git apply --check /pfad/period-forecast-improvements.patch
git apply /pfad/period-forecast-improvements.patch
git diff --check
```

Die normale Quellvorbereitung erzeugt die gebundenen Browser-Zeitzonendateien
und den Linux-Laufzeitkatalog. Windows-Laufzeitkataloge sind bereits vollständig
im Patch enthalten. Zur kompakten Darstellung enthält der Patch dafür normale
Git-Binär-Differenzen; die reviewbaren PO-Quellen liegen ebenfalls bei.

```sh
python3 magnolie-organizer/werkzeuge/zeitzonen_erzeugen.py
python3 magnolie-organizer/werkzeuge/zeitzonen_erzeugen.py --output magnolie-organizer-windows/app/web
python3 tools/appointment_occurrence_locales.py --apply --messages tools/cycle_forecast_locales.json --comment 'Optional period forecast improvements (Refs #803).'
npm install --ignore-scripts --prefix magnolie-organizer-windows

node magnolie-organizer-windows/tests/cycle-forecast.js
node magnolie-organizer-windows/tests/cycle-calendar.js
node magnolie-organizer-windows/tests/desktop-state-regressions.js
node magnolie-organizer-windows/tests/mcp-ui.js
python3 -m unittest discover -s magnolie-organizer/pruefungen -p test_cycle_forecast_stdlib.py -v
dotnet run --project magnolie-organizer-windows/tests/cycle-forecast/CycleForecastProbe.csproj
python3 magnolie-organizer-windows/tests/cycle-forecast-browser.py --browser /pfad/zu/chromium --output /tmp/cycle-proof
```

Der portable C#-Host benötigt keine zusätzlichen NuGet-Pakete. Die
Browserprüfung lädt die tatsächlichen lokalen Produktdateien über eine
Testbrücke; die Content-Security-Policy bleibt aktiv. Alle fachlichen
Testbücher sind synthetisch. Die Berechnungs- und UI-Tests sind Teil des
Patches; die beiden Zyklustests sind außerdem in den vorhandenen
Windows-JavaScript-Teststarter aufgenommen.

## Grenzen und nächste Abnahme

Die Funktionen wurden im Quellstand, in den tatsächlichen JS-Oberflächen im
Browser und in den tatsächlichen nativen Berechnungskomponenten geprüft.
**Nicht durchgeführt** wurden eine Abnahme installierter Windows-/Linux-Pakete,
ein nativer GUI-Durchlauf oder die Zustellung echter Betriebssystem-
Benachrichtigungen. Der portable C#-Host ersetzt diese Abnahmen nicht. Die
vollständige Python-pytest-Suite wurde nicht ausgeführt, weil pytest in dieser
Umgebung fehlt; die zusätzliche echte stdlib-Suite ist vollständig gelaufen.
Ebenso ist kein vollständiger NuGet-abhängiger Windows-CoreTests-Lauf behauptet.

Für eine spätere Einpflege sind die normale Integrationsprüfung und die
native Paket-/Benachrichtigungsabnahme noch erforderlich. Dieses Issue bleibt
deshalb offen. Weder das Abschließen einer Planungspause noch eine fehlende
Warnung ist ein medizinischer Befund. Es wurden keine persönlichen
Gesundheitsdaten verwendet und keine medizinische Vorhersagegenauigkeit
validiert. Die Übersetzungen wurden technisch vollständig geprüft, jedoch
nicht durch Muttersprachler aller 20 Sprachen abgenommen.

## Medizinische Primärquellen

Geprüft am 26. November 2026; sie begründen die vorsichtige Formulierung der
Hinweise, nicht die numerischen Software-Heuristiken:

- [NHS: Irregular periods](https://www.nhs.uk/symptoms/irregular-periods/)
- [NHS: Missed or late periods](https://www.nhs.uk/symptoms/missed-or-late-periods/)
- [NHS: Vaginal bleeding in pregnancy](https://www.nhs.uk/pregnancy/common-symptoms/vaginal-bleeding/)
- [NHS: Postmenopausal bleeding](https://www.nhs.uk/symptoms/post-menopausal-bleeding/)

## Prüfnachweise

Die Rohprotokolle stehen unter [test-results](test-results/), die tatsächlichen
Browserbilder unter [screenshots](screenshots/). `browser-results.json`
enthält zusätzlich die Szenarien, den deutschen Tooltiptext und die gemessenen
Tagesansichtsgrößen. Die Checksummen beziehen sich auf die unveränderten
bereitgestellten Dateien.
