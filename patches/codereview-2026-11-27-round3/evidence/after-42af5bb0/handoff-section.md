## Codereview vom 27. November 2026: finale Nachtragsserie

Die finale Reviewserie ist auf die unabhängig weiterentwickelte Basis
`42af5bb030d5e0fb8a2bfc8b8f28459cfe31c2fe` festgelegt. Die bereits übernommenen
Korrekturen aus #840, #841, #842 und der ursprüngliche Kontaktfall aus #823
bleiben erhalten. Die historische Serie zur ursprünglichen Prüfbasis
`0cdd6f992e094cd724203713da3bf145c36958fc` wird gesondert dokumentiert.
Dieser Review führt keinen Merge nach `main` aus und gibt keine Pakete frei.

- #823: Die ursprüngliche Korrektur zur stabilen lokalen Kontaktidentität
  wurde unabhängig mit `42af5bb0` übernommen. Der zusätzliche Vergleich
  bestätigte einen engeren Feldrest: Bei einem UID-Wechsel fehlte
  `kontaktpersonen` in beiden Inhalts-Whitelists. Eine über den tatsächlichen
  vCard-Pfad erzeugte Liste mit zwei Notfallkontakten blieb beim Restore leer;
  nur die alten Einzelfelder der ersten Person wurden ergänzt.
  Der Nachtrag ergänzt ausschließlich dieses Inhaltsfeld in beiden bereits
  übernommenen Whitelists. Aktuelle UID und eine einzige Kontaktkarte bleiben
  erhalten. Alle 40 übernommenen Vektoren, zwölf weitere Reviewvektoren und
  der neue Feldfall bleiben enthalten: 53 gemeinsame Fälle ohne Dubletten.
  Vorher scheiterten der neue Python-Fall und die C#-Auswahlgruppe;
  danach bestanden 144 fokussierte Python-Prüfungen und die C#-Gruppe.
  Beide echten vCard-/Restore-Pfade erhalten danach beide Personen.
- #839: Der unveränderte Port-Nachtrag verhindert doppelte Meldungen für
  zusammenfallende absolute und gewöhnliche Alarme sowie erneute Meldungen
  nach Entfernen einer Alarmart. Alte verschlüsselte Tablet-Pläne werden
  ohne erneutes Web-Speichern abgeglichen. Die Eingaben der bereits
  bestandenen 398 Mac-Quell-/Controllerprüfungen, 30 Tablet-Oberflächenfälle
  und 23 JVM-Speicherprüfungen sind bytegleich gebunden; diese Suiten wurden
  für die neue Kontaktbasis nicht erneut ausgeführt.
- #841: Die mit `ecad9a05` übernommene RTL-Korrektur bleibt unverändert.
  Der Nachtrag ergänzt den Starttest im bestehenden Webtestlauf.
  Die Eingaben der 16 bestandenen DOM-Startfälle sind bytegleich erhalten.
  Das Handbuch verwendet die korrekte Untertagregel bereits.
- #842: Die mit `dd997f01` übernommene Ablehnung beschädigten UTF-16 mit BOM
  sowie deren neue Vertragstests bleiben unverändert. Der Nachtrag ergänzt
  die zusätzliche bestehend angebundene Regression mit 148 Datei-, ZIP-
  und Müllkalenderfällen. Diese Gruppe und die benachbarten Importgruppen
  bestanden erneut auf der finalen Kontaktbasis.

Der tatsächliche CoreTests-Bau mit gesperrten Abhängigkeitsversionen und
.NET SDK 8.0.408 bestand ohne Warnungen oder Fehler. Auf dem neuen Quellstand
bestanden alle sechs fokussierten C#-Gruppen: Kontaktidentität, Journal,
UTF-16-Import, Austauschformate, native Importdateileser und Aufgaben-CSV.
Die 144 Python-Prüfungen stammen aus den vier vorhandenen Restore-/Save-
Dateien. Der portable Runner führt seinen Build selbst aus und bindet
Quellstände, Prüfeingaben, Rückgabecodes und Protokolle an Prüfsummen.
Host-DOM-, C#- und JVM-Läufe ersetzen weder eine installierte Desktop-GUI
noch Android-NotificationManager, macOS-Mitteilungszustellung oder die
Paket-/Geräteabnahme aus #113/#121.

Vollständige Patches, Beschreibungen, rote/grüne Nachweise und Anwendungstests:
[Review-Patchindex](https://github.com/maik3531/Magnolie-Organizer/tree/work/codereview-20261127-round3-patches/patches/codereview-2026-11-27-round3).
Nächster Schritt ist die gezielte Einpflege des zusätzlichen Feldrests aus
#823, des Alarmnachtrags aus #839 und der ergänzenden Regressionen,
anschließend die jeweils erforderliche native Abnahme. Der gesonderte
offene CSV-Kontaktteil in #566 wird hier nicht als erledigt dargestellt.
