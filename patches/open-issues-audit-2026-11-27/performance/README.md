# Dauerbetrieb, Speicher und große Bestände

**Aktualisierung nach dem Abschlussabruf:** #843 ist inzwischen unabhängig
upstream in `66b50c44482f279d7c3566fe2959f66ebcc20cd5` behoben. Der Folgestand
`1f1f3225ab50fe38902bc8e790454fd944f8b693` besteht die unveränderte unabhängige
Ownershipprobe (3/3 einschließlich data: und synchronem Ersatzworker) sowie
beide tatsächlichen Zeitzonenprojektoradapter. Der bisherige Alternativpatch
`9c003363` ist **nicht erneut anzuwenden**. Ursprüngliche Messungen behalten ihre
unten genannten Quellstände; der 77-Dateien-Stand davor ist unverändert
archiviert. Siehe [Übernahmenachtrag](843/upstream-adoption.json).

Die Anforderung bleibt als übergreifende Abnahme in
[#395](https://github.com/maik3531/Magnolie-Organizer/issues/395): Der Organizer
soll nach 30 Tagen im Tray ohne technische Pflege weiterhin zuverlässig arbeiten
und mehrere Zehntausend Einträge flüssig suchen, öffnen und bearbeiten können.
Der ursprüngliche N100-/Mint-Cinnamon-Bericht ist dadurch nicht als insgesamt
aufgeklärt dargestellt. Root hat die konkreten Nutzerkriterien in #395 ergänzt
und die Abnahmepflicht in #113 verlinkt; beide Änderungen wurden von Root remote
zurückgelesen.

**Ergebnis dieses begrenzten Zusatzes:** 50.000 Einträge insgesamt bestehen die
vorhandene Volumensuite. Bei 250.000 insgesamt überschreiten zwei Abschnitte ihre
bisherigen Grenzen. Zwei enge Quellpatches beseitigen bestätigte unnötige
Ressourcenbindung bzw. DOM-Arbeit. Eine langsame Suche mit Ziffern und der teure
Import-/Zeichenblock bleiben als konkrete Leistungsreste offen. Ein nativer
30-Tage-Lauf wurde nicht durchgeführt.

Die strukturierte Bewertung mit Quellen, Grenzen und Abnahmekriterien steht in
[assessment.json](assessment.json). Alle Daten waren synthetisch.

## 1. Unveränderte Volumensuite: echte Größen klar getrennt

Die vorhandene `magnolie-organizer/pruefungen/last_test.js` erzeugt die angegebene
Zahl **je Bereich**: Termine, Kontakte, Aufgaben, Notizen und Jahrestage. Ein
Parameter von 50.000 bedeutet deshalb zunächst 250.000 Einträge insgesamt.
Später importiert die Suite weitere 5.000 Termine. Die vorhandenen Zeitgrenzen
wurden unverändert übernommen.

| Messung | 10.000 je Bereich = 50.000 insgesamt | 50.000 je Bereich = 250.000 insgesamt |
|---|---:|---:|
| Gesamtergebnis | PASS, Exit 0 | Zwei Zeitgrenzen verletzt, Exit 1 |
| Gesamtlauf | 15,585 s | 54,191 s |
| App.init | 475 ms | 1.375 ms |
| Übrige Bereiche importieren und zeichnen, Grenze 20.000 ms | 7.680 ms | **22.100 ms** |
| Terminblatt fünfmal öffnen/entfernen, Grenze 4.000 ms | 824 ms | **4.588 ms** |
| Zehn Monate weiterblättern, Grenze 4.000 ms | 717 ms | 3.400 ms |
| JSON erzeugen / wieder parsen | 134 / 111 ms | 697 / 1.192 ms |
| 5.000 neue Termine zusammenführen | 403 ms | 3.791 ms |
| Dieselben 5.000 erneut, ohne Doppelanlage | 134 ms | 108 ms |
| Maximaler RSS des Hostprozesses | 800.320 KiB ≈ 781,56 MiB | 2.559.920 KiB ≈ 2.499,92 MiB |
| Vom Test am Ende gemeldeter JS-Heap | 592 MiB | 1.724 MiB |

Die Objektzahlen, geprüfte Mehrfachtelefonnummern/-anschriften und
Doppelimportbedingungen bestanden auch im größeren Fall. Protokolle und
Messmanifeste liegen unter [logs/](logs/), insbesondere
[ui-10000-linux.log](logs/ui-10000-linux.log) und
[ui-50000-linux.log](logs/ui-50000-linux.log).

**Diese Speicherwerte sind keine native RAM-Abnahme und kein Leaknachweis.**
Der Node-/JSDOM-Prozess hält gleichzeitig Testfixtures, normalisierte Buchdaten,
DOM-Knoten, Drucktexte und JSON-Strings. Gemessen wurde ein kurzer Lauf mit
Spitzen-RSS, nicht der ruhende Speicherboden nach gleichen Tagesabläufen.
Der Runner erzwingt keine Garbage Collection.

Auch einzelne Namen des vorhandenen Tests sind enger zu verstehen: „Speichern“
misst hier `JSON.stringify`, anschließend wird JSON geparst. Es handelt sich
nicht um verschlüsselte native Disk-Speicherung mit anschließendem Reopen. Der
neue Termin wird direkt über Testdaten eingefügt. Der Terminblattabschnitt
entfernt den Dialog mit DOM `.remove()` statt dem regulären Schließweg; daraus
verbleibende Harnesszustände dürfen nicht als Produktleck bezeichnet werden.
Einige Zeitmessungen warten zudem keinen echten Renderframe ab. Alte
Druckbeschriftungen nennen noch 30.000, obwohl Parameter und Assertions die oben
genannten tatsächlichen Größen benutzen. Der optionale Adresssuchabschnitt
lieferte keine Messzeile und wird hier nicht als geprüfte Suche beansprucht.

## 2. Tatsächlicher Suchpfad: Ziffern verursachen zusätzliche Arbeit

Eine enge Probe verwendet denselben bestehenden Desktop-Boot-Harness und ruft
die wirkliche `OrganizerTest.suchTrefferFuer`-Funktion auf beiden Desktopquellen
auf. Je Fall wurden drei Werte erhoben. Erwartete Trefferzahlen stimmten; es
wurde keine neue Zeitgrenze erfunden.

| Suchfall bei 50.000 Terminen plus 50.000 verknüpften Kontakten | Windows-Quell-JS | Linux-Quell-JS |
|---|---:|---:|
| Letzter eindeutiger Titel | 122–184 ms | 96–117 ms |
| Fehlender Text ohne Ziffern | 107–119 ms | 93–94 ms |
| Fehlender Text `nomatchingtitle2026` | **2.294–2.441 ms** | **2.302–2.372 ms** |
| Datum, erste 101 Treffer | 13–16 ms | 12–19 ms |

Das sind **100.000 Datensätze insgesamt**, kein weiterer 50.000-Gesamtbestand.
Bei 10.000 Terminen plus 10.000 Kontakten lag die erfolglose Ziffernsuche bei
449–507 ms. Vollständige Einzelwerte und Befehle stehen in
[core-search-results.json](core-search-results.json) und
[core-search.manifest.json](logs/core-search.manifest.json).

Der Quellpfad erklärt den Unterschied: `suchKontext` baut die aktuellen
Kontakt-/Personenindizes pro Suche. `kalenderSuchTreffer` überspringt einen
fehlenden Rohtexttreffer früh, außer wenn ein Suchbegriff Ziffern enthält.
Dann werden für jeden Termin zusätzlich Datum und Zeit formatiert und der
erweiterte Suchtext gebaut. Dieser Ablauf ist synchron. Die sichtbare
Ergebnisbegrenzung und die Verzögerung im Suchdialog beseitigen diese Arbeit
nicht. Ein Zahlen-/Datumsbegriff darf bei einer späteren Optimierung aber auch
nicht seine richtige Bedeutung verlieren. Deshalb wird der gemessene Kostenpfad
in #395 festgehalten, ohne hier einen breiten Suchumbau anzufangen.

## 3. Zwei bestätigte enge Patchlieferungen

### #843: Worker-URL und Listener gehören zu ihrer Workerinstanz

Dieser Befund ist durch die oben genannte aktuelle Upstreamlösung erledigt.
Die folgenden Vorher-/Nachherdaten beschreiben den historischen Alternativpatch
und werden für die Nachvollziehbarkeit erhalten, nicht als neuer Patchauftrag.

Vorher blieben URLs gescheiterter oder verworfener Kalender-Worker bis zum
Dokumentende registriert. Wiederholte Anfragen konnten weitere Quellen und
`unload`-Listener ansammeln. Der separate Patch
`9c00336342f736f541cf14e006de1248b22b8850` beseitigt diesen Besitzfehler auf beiden
Desktopquellen. Fehler geben die eigene Quelle frei; späte alte Callbacks
beeinträchtigen einen Ersatzworker nicht. Ein erfolgreicher Worker behält seine
benötigte Quelle bis zur Freigabe.

32 kontrollierte Fehlstarts hielten vorher **32 echte registrierte Blob-URLs,
15.647.552 Blob-Bytes und 32 Listener**, danach jeweils null. Wiederholte
Workerfehler oder Providerverwerfungen hielten vorher 64 Listener, danach null.
Die normale erfolgreiche Nutzung hält weiterhin genau eine Quelle. Die
erweiterte vorhandene Worker-Suite, beide wirklichen Zeitzonenprojektoradapter
und ein unabhängiger Review mit drei Protokoll-/Besitzfällen bestanden.

Die Blob-Zahlen beziehen sich auf den tatsächlichen Produkt-Blobzweig im
Hostharness. Das native Linux-Custom-Scheme verwendet `data:`; dessen
Protokollwahl, Listenerbesitz und idempotente Freigabe wurden separat geprüft.
Die Probe führt keinen nativen WebKit-`data:`-Worker aus und misst keinen
Browserheap. Einzelheiten, Formatpatch, Quellhashes und Grenzen stehen in
[843/README.md](843/README.md) und [843/delivery.json](843/delivery.json).

### #395: Verborgene Kontakt-Namensoptionen erst bei Benutzung erzeugen

Die unabhängige Quellenanalyse fand beim Terminblatt eine sofortige Erstellung
aller Organisator-Namensoptionen, obwohl das Zusatzfeld noch verborgen war.
2.003 synthetische Kontakte erzeugten bei jedem von fünf regulären
Öffnen-/Schließen-Zyklen 2.002 unbenutzte `<option>`-Knoten auf beiden Quellen.
Der Teilpatch `38edd46ef18259e232c786bf2e8e88903f96b655` erzeugt sie erst bei
Benutzung und begrenzt die Liste auf das vorhandene Häppchen von 250 Vorschlägen.
Späte exakte Namen, zusammengeführte E-Mail-Adressen gleicher Namen, Firmen sowie
freie und gespeicherte Werte bleiben erhalten. Zehn enge Fälle und die
bestehende strukturierte Terminprüfung bestanden.

Die komplette 250.000-Suite wurde für diese lokale Änderung nicht wiederholt.
Es wird daher weder deren Importgrenze noch die ganze Terminblatt-Zeitgrenze
als nun bestanden ausgegeben. Nachweise und Patch stehen in
[395-suggestions/README.md](395-suggestions/README.md).

Der Import-/Zeichenblock enthält unter anderem sichere Kopien, kanonische
Revisionsprüfungen, eine bereits auf 25 Fälle begrenzte Kontaktvorschau und
mehrere Bereichsmerges. Ohne getrennte Phasenmessung ist kein einzelner unnötiger
Anteil an den 22,10 Sekunden belegt. Schutzprüfungen und Zeitbudgets bleiben
erhalten; siehe [review-395-source-analysis.json](review-395-source-analysis.json).

## 4. Bestehende Schutzmechanismen und frühere Befunde

Die Quellen haben bereits begrenzte Listenhäppchen, einen Formatierercache von
128 Einträgen, Grenzen für Serienerweiterung und Workeraufträge sowie
Aufräumpfade für native Timer, Fenster und Trayressourcen. „Alle anzeigen“ kann
die anfängliche Listenbegrenzung allerdings bewusst aufheben. Eine Grenze für
einen einzelnen Cache belegt keine Speichergrenze des gesamten Prozesses.

Die fünf vollständigen #395-Kommentare wurden gelesen. Die frühere
Zeitzonenformatierer-Korrektur und die behobene Notizsortierung werden nicht
erneut als offene Fehler ausgegeben. Der historische 600,55-Sekunden-Traylauf
belegt keine Stunden- oder Monatsstabilität. Der frühere Aufschub breiter
Optimierung wird durch den neuen gezielten Nutzerauftrag ersetzt. Die
gesonderten Prüfhelfer-Speicherprobleme #593/#832 und der WebKit-Absturzbericht
#53 werden nicht ohne Beleg zur Ursache des Organizer-RAMverhaltens erklärt.
Quellen und damalige Grenzen sind in [issue-context.json](issue-context.json)
und [assessment.json](assessment.json) festgehalten.

## 5. Messbare native Abnahme für #395 und #113

Die folgende Matrix ist ein Vorschlag für die verbleibende Abnahme. Sie erfindet
keine neuen Millisekunden- oder RAMgrenzen. Hardware, Releasekandidat und etwaige
konkrete Latenzbudgets müssen vor der Vergleichsmessung feststehen. Bereits
vorhandene Regressiongrenzen werden nicht nachträglich angehoben.

| Bereich | Ablauf | Nachweis / Bestehensbedingung |
|---|---|---|
| 10.000 und 50.000 **Gesamteinträge** | Gemischtes Buch kalt/warm öffnen; erste, mittlere, letzte und fehlende Einträge suchen; echte Änderungen speichern und erneut öffnen | Alle Objektzahlen, Felder und Referenzen erhalten; sichtbare Bedienung und native SaveACK-/Reopenfolge dokumentiert |
| Separater größerer Stresstest | 50.000 **je Bereich**, insgesamt 250.000, mit denselben vorhandenen Fixtures | Eigene Größenangabe; Phasen des teuren Imports getrennt messen; keine falsche Gleichsetzung mit 50.000 insgesamt |
| Suche und Editor | Text, Ziffern, lokales/ISO-Datum, Unicode; Einmal- und Serieneinträge; öffnen, ändern, abbrechen und speichern | Richtige erreichbare Treffer und Feldwerte; tatsächliche sichtbare Antwortzeiten vor/nach Langzeitbetrieb auf gleichem Bestand vergleichen |
| 30 Tage im Tray | Ohne Appneustart, technische Reinigung oder erzwungene GC; reguläre tägliche gleiche Nutzung und Ruhephasen | Gesamter Prozessbaum: RSS/PSS bzw. privater Working Set, CPU, Threads, FDs/Handles und Prozesszahl als Rohzeitreihe; gleicher ruhender Vergleichszustand nach Warmup sowie Tag 1/7/14/30; kein dauerhaft ansteigender Ressourcenboden bei gleichen Daten |
| Wiederholte Lebenszyklen | Suchen ersetzen, Dialoge regulär schließen, Ansichten wechseln, Fehler/Retry, Telefonpanels auf-/abbauen | Keine mit Wiederholungen wachsende Anzahl verwaister URLs, Timer, Listener oder Besitzer; gültige aktive Ressourcen bleiben erlaubt |
| Native Übergänge | Tray/Restore, Sperren, Standby/Resume, tatsächlicher Monitor-/DPIwechsel, Offline/Online; konfigurierte Sync-/Backupfunktionen bleiben an | Bedienung und Hintergrundfunktionen bleiben korrekt; kein Neustart oder Abschalten freigegebener Funktionen als Bestehensbedingung |

Ein begrenzter Cache darf sich nach dem Start füllen; ein höherer einzelner
Spitzenwert ist deshalb nicht automatisch ein Leak. Entscheidend ist der
vergleichbare Speicherboden über wiederholte gleiche Nutzung mit konstantem
Datenbestand. Datenwachstum und bewusst begrenzte Caches müssen vom Verlauf
getrennt erklärt werden. Heap-/Besitzerdiagnostik ergänzt die native
Prozessmessung, ersetzt sie aber nicht.

Linux GTK/WebKit und Windows WebView2 benötigen jeweils ihre native Abnahme.
Ein Mac-Statusleistenlauf und das unterschiedliche Android-Hintergrundmodell
werden separat ausgewiesen. In diesem Zusatz wurden keine Geräte, VMs oder
nativen Monatsläufe gestartet. Der eigene #759-Nachweis über 128 Wiederholungen
ohne zurückbleibende Pending-/Timerreste ist ein begrenzter Lebenszyklusnachweis,
ebenfalls kein Monatslauf.

## 6. Quellenbindung, Befehle und Grenzen

Volumen und Suche wurden auf `50b1512234a765635f82af4537f277594fbf9878`
gemessen. Der eingefrorene Folgestand ist
`24927cf94cfe9a7bb5c4f148a38d6b04b0bc732b`. Unter den geprüften Eingaben änderte
sich nur die Linux-Anwendungsdatei, und dort ausschließlich Telefonmedien-UI
außerhalb der gemessenen Suche, Listen, Terminblatt- und Workerfunktionen.
[source-delta-binding.json](source-delta-binding.json) und der vollständige
[Quelldiff](final-base-source-delta.diff) belegen diese begrenzte Übertragbarkeit.
Die beiden Patchlieferungen basieren direkt auf dem Folgestand. Weitere
integrierte Prüfungen der gesamten Restserie führt Root getrennt aus.

Umgebung: Linux-Host, Node 24.22.3, JSDOM 26.1.0, vorhandene `round3-tools`.
Der RSS-Sampler liest alle 0,25 Sekunden den Hostprozess; außerdem werden
`resource.getrusage`-Spitzen festgehalten. `--max-old-space-size=2048`, der
2,5-GiB-RSS-Wächter und 300 Sekunden sind Ausführungssicherungen, keine
Produktziele. Kein Wächter brach die angegebenen Läufe ab. Das nicht installierte
`/usr/bin/time` wurde durch diese vorhandenen Python-/Linux-Möglichkeiten ersetzt.

Exakte produktive Testbefehle und Umgebung stehen in jedem `*.manifest.json`;
die reproduzierbaren Orchestrierungsaufrufe waren:

```sh
cd /workspace/scratch/7203da5bd564
python open-audit/performance/run_existing.py --name ui-10000-linux --size 10000
python open-audit/performance/run_existing.py --name ui-50000-linux --size 50000
python open-audit/performance/run_existing.py --name core-search --script /workspace/scratch/7203da5bd564/open-audit/performance/core-search.cjs --seconds 120
```

Die normale Erzeugung fehlender Zeitzonen- und Sprachassets ist in
[preparation-commands.json](preparation-commands.json) dokumentiert. Vollständige
Eingabehashes stehen in [environment-and-inputs.json](environment-and-inputs.json).
Der vorhandene optionale Planner-Paritätstest hat unabhängig vom Patch einen
alten Regex-Ankerfehler; er wurde offengelegt, gegen die unveränderte Basis
bestätigt und nicht als vollständig grün ausgegeben. Der konkrete Funktionsinhalt
und beide tatsächlichen Zeitzonenprojektoradapter wurden separat geprüft.

Offen bleiben die native 30-Tage-Abnahme, die gesamte N100-Ursache, die gemessene
Ziffernsuche sowie die weitere Isolation des Import-/Zeichenblocks. Dieser
Zusatz eröffnet keine weiteren Optimierungsprojekte und beansprucht keine
Freigabe von Paketen oder vollständige Dauerbetriebsentwarnung.
