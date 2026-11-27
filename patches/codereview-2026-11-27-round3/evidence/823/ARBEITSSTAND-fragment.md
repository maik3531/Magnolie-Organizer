- [#823](https://github.com/maik3531/Magnolie-Organizer/issues/823):
  Ein zusätzlicher Kontaktfall wurde auf `0cdd6f99` bestätigt: Ein Import
  ergänzt die externe UID einer Karte, ihre lokale ID bleibt gleich.
  Die ergänzende Wiederherstellung erzeugte danach zwei Karten mit dieser ID.
  Der Patch `71c5cb22` erhält die eindeutige lokale Kontaktidentität samt
  aktueller UID und Bindungen; bei UID-Wechsel ergänzt er nur bekannte fehlende
  Kontaktinhalte. Mehrdeutige lokale Identitäten werden vor dem Schreiben
  abgewiesen. 49 gemeinsame Auswahlvektoren bestehen in Python und C#;
  insgesamt bestanden 136 fokussierte Python-Fälle und zwei C#-Gruppen.
  Der Importablauf wurde mit beiden vollständigen Frontends in JSDOM und
  anschließend in den tatsächlichen Python-/C#-Auswahlfunktionen geprüft.
  Reale isolierte Linux-Dateischreibvorgänge einschließlich Schutzsnapshot,
  Wiederholung, Neustart und Ablehnung eines alten Folge-Saves bestanden.
  Diese Hostprüfungen ersetzen keine installierte Windows-/Linux-GUI-Abnahme.
  Der Patch liegt zur späteren Einpflege bereit; dieser Review übernimmt
  keine Produktänderungen nach `main` und veröffentlicht keine Pakete.
